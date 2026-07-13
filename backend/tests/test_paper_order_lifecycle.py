from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models import PaperEngineEvent, PaperOrder, PaperPortfolio, User
from app.services.data_feed.types import Tick
from app.services.paper_trading.engine import PaperEngine
from app.services.paper_trading.quotes import QuoteCache
from app.services.paper_trading.types import (
    STATUS_APPROVED,
    STATUS_EXPIRED,
    STATUS_FILLED,
    STATUS_PROPOSED,
    STATUS_REJECTED_RISK,
    STATUS_REJECTED_USER,
)

RTH_NOW = datetime(2026, 7, 8, 15, 0, tzinfo=UTC)  # Wednesday 15:00 UTC


class Clock:
    def __init__(self, now: datetime = RTH_NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now = self.now + timedelta(**kwargs)


def build_session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite:///{tmp_path / 'test_paper_lifecycle.db'}")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def seed_portfolio(
    session: Session, *, cash: float = 100_000.0, risk: dict | None = None
) -> PaperPortfolio:
    user = User(email="paper@example.com", password_hash="hash")
    session.add(user)
    session.flush()
    portfolio = PaperPortfolio(
        owner_user_id=user.id,
        initial_cash=Decimal(str(cash)),
        cash=Decimal(str(cash)),
        equity=Decimal(str(cash)),
        risk_settings=risk or {},
        engine_running=True,
    )
    session.add(portfolio)
    session.commit()
    return portfolio


def feed_quote(
    cache: QuoteCache,
    symbol: str,
    *,
    last: float | None = None,
    bid: float | None = None,
    ask: float | None = None,
) -> None:
    cache.update_from_tick(
        Tick(
            symbol=symbol,
            timestamp=RTH_NOW,
            last=Decimal(str(last)) if last is not None else None,
            bid=Decimal(str(bid)) if bid is not None else None,
            ask=Decimal(str(ask)) if ask is not None else None,
        )
    )


def build_engine(portfolio: PaperPortfolio, clock: Clock) -> tuple[PaperEngine, QuoteCache]:
    cache = QuoteCache(now_fn=clock)
    cache.set_liveness("DELAYED")
    engine = PaperEngine(portfolio.id, quotes=cache, hub=None, now_fn=clock)
    return engine, cache


def event_types(session: Session, portfolio_id: int) -> list[str]:
    return [
        event.event_type
        for event in session.execute(
            select(PaperEngineEvent)
            .where(PaperEngineEvent.portfolio_id == portfolio_id)
            .order_by(PaperEngineEvent.id)
        ).scalars()
    ]


def test_signal_to_proposal_to_fill(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    clock = Clock()
    with factory() as session:
        portfolio = seed_portfolio(session)
        engine, cache = build_engine(portfolio, clock)
        feed_quote(cache, "AAPL", last=100.0, bid=99.95, ask=100.05)

        order = engine.propose_from_signal(
            session,
            portfolio,
            symbol="AAPL",
            direction="BUY",
            strength=0.8,
            strategy="rsi_mean_reversion",
            rationale="RSI(14) em sobrevenda (25.00 < 30).",
            signal_timestamp=RTH_NOW,
        )
        assert order is not None and order.status == STATUS_PROPOSED
        assert float(order.quantity) == 100.0  # 10% of 100k at ~100
        assert order.stop_loss_pct is not None
        assert order.signal_snapshot["strategy"] == "rsi_mean_reversion"
        assert order.risk_snapshot["position_pct_of_equity"] is not None

        order, trade, deferral = engine.approve_order(session, portfolio, order)
        session.commit()

        assert deferral is None and trade is not None
        assert order.status == STATUS_FILLED
        assert float(trade.price) == 100.05  # BUY fills at the ask
        assert trade.fill_basis == "bid_ask"

        types = event_types(session, portfolio.id)
        assert types == [
            "signal_received",
            "order_proposed",
            "order_approved",
            "order_filled",
        ]


def test_user_rejection(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    clock = Clock()
    with factory() as session:
        portfolio = seed_portfolio(session)
        engine, cache = build_engine(portfolio, clock)
        feed_quote(cache, "AAPL", last=100.0, bid=99.9, ask=100.1)

        order = engine.propose_from_signal(
            session,
            portfolio,
            symbol="AAPL",
            direction="BUY",
            strength=0.9,
            strategy="macd_crossover",
            rationale="MACD cruzou acima.",
        )
        engine.reject_order(session, portfolio, order)
        session.commit()

        assert order.status == STATUS_REJECTED_USER
        assert "order_rejected" in event_types(session, portfolio.id)


def test_risk_veto_is_persisted_with_reason(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    clock = Clock()
    with factory() as session:
        # 10% cap but the sizing knobs ask for 40% positions.
        portfolio = seed_portfolio(
            session, risk={"max_position_pct": 10.0, "position_size_pct": 40.0}
        )
        engine, cache = build_engine(portfolio, clock)
        feed_quote(cache, "NVDA", last=200.0, bid=199.9, ask=200.1)

        order = engine.propose_from_signal(
            session,
            portfolio,
            symbol="NVDA",
            direction="BUY",
            strength=0.9,
            strategy="bollinger_breakout",
            rationale="Fecho acima da banda superior.",
        )
        session.commit()

        assert order is not None and order.status == STATUS_REJECTED_RISK
        assert "excede o máximo" in order.reject_reason
        assert "risk_veto" in event_types(session, portfolio.id)


def test_weak_signal_and_duplicate_order_are_skipped(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    clock = Clock()
    with factory() as session:
        portfolio = seed_portfolio(session)
        engine, cache = build_engine(portfolio, clock)
        feed_quote(cache, "AAPL", last=100.0, bid=99.9, ask=100.1)

        weak = engine.propose_from_signal(
            session, portfolio, symbol="AAPL", direction="BUY",
            strength=0.1, strategy="s", rationale="fraco",
        )
        assert weak is None

        first = engine.propose_from_signal(
            session, portfolio, symbol="AAPL", direction="BUY",
            strength=0.9, strategy="s", rationale="ok",
        )
        assert first is not None

        duplicate = engine.propose_from_signal(
            session, portfolio, symbol="AAPL", direction="BUY",
            strength=0.9, strategy="s", rationale="repetido",
        )
        assert duplicate is None
        session.commit()

        skips = [t for t in event_types(session, portfolio.id) if t == "signal_skipped"]
        assert len(skips) == 2


def test_sell_without_position_is_skipped(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    clock = Clock()
    with factory() as session:
        portfolio = seed_portfolio(session)
        engine, cache = build_engine(portfolio, clock)
        feed_quote(cache, "MSFT", last=300.0, bid=299.9, ask=300.1)

        order = engine.propose_from_signal(
            session, portfolio, symbol="MSFT", direction="SELL",
            strength=0.9, strategy="s", rationale="venda",
        )
        assert order is None
        assert "signal_skipped" in event_types(session, portfolio.id)


def test_approval_blocked_by_kill_switch(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    clock = Clock()
    with factory() as session:
        portfolio = seed_portfolio(session)
        engine, cache = build_engine(portfolio, clock)
        feed_quote(cache, "AAPL", last=100.0, bid=99.9, ask=100.1)

        order = engine.propose_from_signal(
            session, portfolio, symbol="AAPL", direction="BUY",
            strength=0.9, strategy="s", rationale="ok",
        )
        portfolio.kill_switch_active = True

        order, trade, _ = engine.approve_order(session, portfolio, order)
        session.commit()

        assert trade is None
        assert order.status == STATUS_REJECTED_RISK
        assert "kill switch" in order.reject_reason.lower()


def test_proposals_expire_after_window(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    clock = Clock()
    with factory() as session:
        portfolio = seed_portfolio(session, risk={"order_expiry_minutes": 30})
        engine, cache = build_engine(portfolio, clock)
        feed_quote(cache, "AAPL", last=100.0, bid=99.9, ask=100.1)

        order = engine.propose_from_signal(
            session, portfolio, symbol="AAPL", direction="BUY",
            strength=0.9, strategy="s", rationale="ok",
        )
        assert order.status == STATUS_PROPOSED

        clock.advance(minutes=31)
        expired = engine.expire_stale_proposals(session, portfolio)
        session.commit()

        assert expired == 1
        assert order.status == STATUS_EXPIRED
        assert "order_expired" in event_types(session, portfolio.id)


def test_approved_order_defers_without_quote_then_fills(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    clock = Clock()
    with factory() as session:
        portfolio = seed_portfolio(session)
        engine, cache = build_engine(portfolio, clock)
        feed_quote(cache, "AAPL", last=100.0, bid=99.9, ask=100.1)

        order = engine.propose_from_signal(
            session, portfolio, symbol="AAPL", direction="BUY",
            strength=0.9, strategy="s", rationale="ok",
        )

        clock.advance(minutes=10)  # quote is now older than quote_max_age_seconds
        order, trade, deferral = engine.approve_order(session, portfolio, order)
        assert trade is None
        assert deferral is not None and deferral.code == "stale_quote"
        assert order.status == STATUS_APPROVED  # parked, not lost

        feed_quote(cache, "AAPL", last=101.0, bid=100.9, ask=101.1)  # fresh again
        trade, deferral = engine.try_fill_order(session, portfolio, order)
        session.commit()

        assert deferral is None and trade is not None
        assert order.status == STATUS_FILLED
        assert "fill_deferred" in event_types(session, portfolio.id)
