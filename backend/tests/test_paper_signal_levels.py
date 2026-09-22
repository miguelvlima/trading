"""Níveis de stop/take-profit por sinal (Fase 3): o sinal pode trazer os seus
próprios níveis; sem eles aplicam-se os defaults do portfolio, e o veto
missing_stop mantém-se quando nenhum dos dois dá stop."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models import PaperEngineEvent, PaperPortfolio, PaperPosition, User
from app.services.data_feed.types import Tick
from app.services.paper_trading.engine import PaperEngine
from app.services.paper_trading.quotes import QuoteCache
from app.services.paper_trading.types import STATUS_PROPOSED, STATUS_REJECTED_RISK

RTH_NOW = datetime(2026, 7, 6, 15, 0, tzinfo=UTC)  # Monday 11:00 New York


class Clock:
    def __init__(self, now: datetime = RTH_NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now = self.now + timedelta(**kwargs)


def build_session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite:///{tmp_path / 'test_paper_signal_levels.db'}")
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


def build_engine(portfolio: PaperPortfolio, clock: Clock) -> tuple[PaperEngine, QuoteCache]:
    cache = QuoteCache(now_fn=clock)
    cache.set_liveness("DELAYED")
    engine = PaperEngine(portfolio.id, quotes=cache, hub=None, now_fn=clock)
    return engine, cache


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


def propose_buy(
    engine: PaperEngine,
    session: Session,
    portfolio: PaperPortfolio,
    symbol: str = "AAPL",
    **levels,
):
    return engine.propose_from_signal(
        session,
        portfolio,
        symbol=symbol,
        direction="BUY",
        strength=0.9,
        strategy="rsi_mean_reversion",
        rationale="teste",
        signal_timestamp=RTH_NOW,
        **levels,
    )


def test_signal_levels_override_defaults(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    clock = Clock()
    with factory() as session:
        portfolio = seed_portfolio(session)  # defaults: stop 2%, TP 4%
        engine, cache = build_engine(portfolio, clock)
        feed_quote(cache, "AAPL", last=100.0, bid=99.9, ask=100.1)

        order = propose_buy(
            engine, session, portfolio, stop_loss_pct=1.2, take_profit_pct=2.5
        )
        session.commit()

        assert order is not None and order.status == STATUS_PROPOSED
        assert float(order.stop_loss_pct) == 1.2
        assert float(order.take_profit_pct) == 2.5
        # Levels used are recorded in the snapshot for audit.
        assert order.signal_snapshot["stop_loss_pct"] == 1.2
        assert order.signal_snapshot["take_profit_pct"] == 2.5


def test_defaults_apply_without_signal_levels(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    clock = Clock()
    with factory() as session:
        portfolio = seed_portfolio(session)
        engine, cache = build_engine(portfolio, clock)
        feed_quote(cache, "AAPL", last=100.0, bid=99.9, ask=100.1)

        order = propose_buy(engine, session, portfolio)
        session.commit()

        assert order is not None and order.status == STATUS_PROPOSED
        assert float(order.stop_loss_pct) == 2.0
        assert float(order.take_profit_pct) == 4.0
        assert order.signal_snapshot["stop_loss_pct"] == 2.0


def test_partial_levels_mix_signal_and_defaults(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    clock = Clock()
    with factory() as session:
        portfolio = seed_portfolio(session)
        engine, cache = build_engine(portfolio, clock)
        feed_quote(cache, "AAPL", last=100.0, bid=99.9, ask=100.1)

        # Signal only suggests a stop: the TP falls back to the default.
        order = propose_buy(engine, session, portfolio, stop_loss_pct=0.8)
        session.commit()

        assert float(order.stop_loss_pct) == 0.8
        assert float(order.take_profit_pct) == 4.0


def test_signal_stop_is_clamped_to_max_stop_loss_pct(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    clock = Clock()
    with factory() as session:
        portfolio = seed_portfolio(session)  # max_stop_loss_pct default 5.0
        engine, cache = build_engine(portfolio, clock)
        feed_quote(cache, "AAPL", last=100.0, bid=99.9, ask=100.1)
        feed_quote(cache, "MSFT", last=300.0, bid=299.9, ask=300.1)

        # An ORB-style stop across a wide range (8%) exceeds the user's bound:
        # clamp to 5%, never widen the per-trade loss silently.
        clamped = propose_buy(engine, session, portfolio, stop_loss_pct=8.0)
        assert float(clamped.stop_loss_pct) == 5.0
        assert clamped.signal_snapshot["stop_loss_pct"] == 5.0

        # Raising the bound lets the strategy's structural stop through.
        portfolio.risk_settings = {"max_stop_loss_pct": 10.0}
        session.flush()
        wide = propose_buy(engine, session, portfolio, symbol="MSFT", stop_loss_pct=8.0)
        session.commit()
        assert float(wide.stop_loss_pct) == 8.0


def test_missing_stop_still_vetoed_without_any_level(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    clock = Clock()
    with factory() as session:
        # No default stop and no signal stop: require_stop_loss must veto.
        portfolio = seed_portfolio(session, risk={"default_stop_loss_pct": 0})
        engine, cache = build_engine(portfolio, clock)
        feed_quote(cache, "AAPL", last=100.0, bid=99.9, ask=100.1)
        feed_quote(cache, "MSFT", last=300.0, bid=299.9, ask=300.1)

        vetoed = propose_buy(engine, session, portfolio)
        assert vetoed is not None and vetoed.status == STATUS_REJECTED_RISK
        assert "Stop-loss obrigatório" in vetoed.reject_reason

        # The signal's own stop satisfies require_stop_loss on its own.
        allowed = propose_buy(engine, session, portfolio, symbol="MSFT", stop_loss_pct=1.0)
        session.commit()
        assert allowed is not None and allowed.status == STATUS_PROPOSED
        assert float(allowed.stop_loss_pct) == 1.0


def test_protective_exit_uses_entry_order_levels(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    clock = Clock()
    with factory() as session:
        portfolio = seed_portfolio(session)  # default stop would be 2%
        engine, cache = build_engine(portfolio, clock)
        feed_quote(cache, "AAPL", last=100.0, bid=99.95, ask=100.05)

        order = propose_buy(engine, session, portfolio, stop_loss_pct=1.0)
        order, trade, deferral = engine.approve_order(session, portfolio, order)
        assert trade is not None
        entry_price = float(trade.price)  # fills at the ask: 100.05

        # Drop 1.1% below entry: crosses the signal's 1% stop but NOT the 2%
        # default — only the entry order's own level can trigger this exit.
        crash = round(entry_price * 0.989, 2)
        feed_quote(cache, "AAPL", last=crash, bid=crash - 0.05, ask=crash + 0.05)
        exits = engine.check_protective_exits(session, portfolio)
        session.commit()

        assert len(exits) == 1
        assert exits[0].symbol == "AAPL"
        events = [
            event.event_type
            for event in session.execute(
                select(PaperEngineEvent).where(
                    PaperEngineEvent.portfolio_id == portfolio.id
                )
            ).scalars()
        ]
        assert "stop_loss_hit" in events
        position = session.execute(
            select(PaperPosition).where(
                PaperPosition.portfolio_id == portfolio.id,
                PaperPosition.symbol == "AAPL",
            )
        ).scalar_one()
        assert float(position.quantity) == 0.0
