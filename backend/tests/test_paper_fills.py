from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models import PaperEngineEvent, PaperOrder, PaperPortfolio, PaperPosition, User
from app.services.data_feed.types import Tick
from app.services.paper_trading.engine import PaperEngine
from app.services.paper_trading.fills import compute_fill
from app.services.paper_trading.quotes import QuoteCache
from app.services.paper_trading.types import (
    STATUS_FILLED,
    FillComputation,
    FillDeferral,
    QuoteSnapshot,
    RiskSettings,
)

RTH_NOW = datetime(2026, 7, 8, 15, 0, tzinfo=UTC)


class Clock:
    def __init__(self, now: datetime = RTH_NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now = self.now + timedelta(**kwargs)


def snapshot(
    *,
    age_seconds: float = 1.0,
    last: float | None = 100.0,
    bid: float | None = 99.9,
    ask: float | None = 100.1,
) -> QuoteSnapshot:
    return QuoteSnapshot(
        symbol="AAPL",
        received_at=RTH_NOW - timedelta(seconds=age_seconds),
        last=Decimal(str(last)) if last is not None else None,
        bid=Decimal(str(bid)) if bid is not None else None,
        ask=Decimal(str(ask)) if ask is not None else None,
        data_liveness="DELAYED",
    )


# -- compute_fill unit tests ------------------------------------------------------


def test_fill_buy_at_ask_sell_at_bid() -> None:
    settings = RiskSettings()
    buy = compute_fill(side="BUY", quantity=10, quote=snapshot(), settings=settings, now=RTH_NOW)
    sell = compute_fill(side="SELL", quantity=10, quote=snapshot(), settings=settings, now=RTH_NOW)
    assert isinstance(buy, FillComputation) and buy.price == 100.1 and buy.basis == "bid_ask"
    assert isinstance(sell, FillComputation) and sell.price == 99.9
    assert buy.data_liveness == "DELAYED"


def test_fill_falls_back_to_last_plus_slippage() -> None:
    settings = RiskSettings(slippage_bps=10.0)
    result = compute_fill(
        side="BUY",
        quantity=10,
        quote=snapshot(bid=None, ask=None, last=100.0),
        settings=settings,
        now=RTH_NOW,
    )
    assert isinstance(result, FillComputation)
    assert result.basis == "last_slippage"
    assert abs(result.price - 100.1) < 1e-9  # +10 bps


def test_fill_deferrals() -> None:
    settings = RiskSettings(quote_max_age_seconds=120.0, max_spread_bps=50.0)

    missing = compute_fill(side="BUY", quantity=1, quote=None, settings=settings, now=RTH_NOW)
    assert isinstance(missing, FillDeferral) and missing.code == "no_quote"

    stale = compute_fill(
        side="BUY", quantity=1, quote=snapshot(age_seconds=500), settings=settings, now=RTH_NOW
    )
    assert isinstance(stale, FillDeferral) and stale.code == "stale_quote"

    wide = compute_fill(
        side="BUY",
        quantity=1,
        quote=snapshot(bid=99.0, ask=101.0),  # ~200 bps
        settings=settings,
        now=RTH_NOW,
    )
    assert isinstance(wide, FillDeferral) and wide.code == "wide_spread"

    empty = compute_fill(
        side="BUY",
        quantity=1,
        quote=snapshot(bid=None, ask=None, last=None),
        settings=settings,
        now=RTH_NOW,
    )
    assert isinstance(empty, FillDeferral) and empty.code == "no_quote"


def test_fill_fee_uses_ibkr_tiered_model() -> None:
    result = compute_fill(
        side="BUY", quantity=10, quote=snapshot(), settings=RiskSettings(), now=RTH_NOW
    )
    assert isinstance(result, FillComputation)
    assert result.fee == 0.35  # minimum per order


# -- engine round-trip: position, cash, realized PnL, protective exits -------------


def build_session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite:///{tmp_path / 'test_paper_fills.db'}")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def seed_portfolio(session: Session, risk: dict | None = None) -> PaperPortfolio:
    user = User(email="fills@example.com", password_hash="hash")
    session.add(user)
    session.flush()
    portfolio = PaperPortfolio(
        owner_user_id=user.id,
        initial_cash=Decimal("100000"),
        cash=Decimal("100000"),
        equity=Decimal("100000"),
        risk_settings=risk or {},
        engine_running=True,
    )
    session.add(portfolio)
    session.commit()
    return portfolio


def feed_quote(cache: QuoteCache, symbol: str, last: float, bid: float, ask: float) -> None:
    cache.update_from_tick(
        Tick(
            symbol=symbol,
            timestamp=RTH_NOW,
            last=Decimal(str(last)),
            bid=Decimal(str(bid)),
            ask=Decimal(str(ask)),
        )
    )


def open_position(
    engine: PaperEngine,
    cache: QuoteCache,
    session: Session,
    portfolio: PaperPortfolio,
    *,
    price: float = 100.0,
) -> PaperOrder:
    feed_quote(cache, "AAPL", price, price - 0.05, price + 0.05)
    order = engine.propose_from_signal(
        session, portfolio, symbol="AAPL", direction="BUY",
        strength=0.9, strategy="s", rationale="entrada",
    )
    engine.approve_order(session, portfolio, order)
    session.commit()
    assert order.status == STATUS_FILLED
    return order


def test_round_trip_updates_cash_position_and_realized_pnl(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    clock = Clock()
    with factory() as session:
        portfolio = seed_portfolio(session)
        cache = QuoteCache(now_fn=clock)
        cache.set_liveness("DELAYED")
        engine = PaperEngine(portfolio.id, quotes=cache, hub=None, now_fn=clock)

        open_position(engine, cache, session, portfolio, price=100.0)

        position = session.execute(select(PaperPosition)).scalar_one()
        assert float(position.quantity) == 100.0
        assert float(position.avg_entry_price) == 100.05  # filled at the ask
        cash_after_entry = float(portfolio.cash)
        assert abs(cash_after_entry - (100_000 - 100 * 100.05 - 0.35)) < 1e-6

        # Price rises; a SELL signal closes the position at the bid.
        feed_quote(cache, "AAPL", 110.0, 109.95, 110.05)
        close = engine.propose_from_signal(
            session, portfolio, symbol="AAPL", direction="SELL",
            strength=0.9, strategy="s", rationale="saída",
        )
        engine.approve_order(session, portfolio, close)
        session.commit()

        position = session.execute(select(PaperPosition)).scalar_one()
        assert float(position.quantity) == 0.0
        expected_realized = (109.95 - 100.05) * 100 - 0.35
        assert abs(float(position.realized_pnl) - expected_realized) < 1e-6
        assert abs(
            float(portfolio.cash) - (cash_after_entry + 100 * 109.95 - 0.35)
        ) < 1e-6
        assert abs(float(portfolio.equity) - float(portfolio.cash)) < 1e-6


def test_stop_loss_auto_closes_position(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    clock = Clock()
    with factory() as session:
        portfolio = seed_portfolio(session, risk={"default_stop_loss_pct": 2.0})
        cache = QuoteCache(now_fn=clock)
        cache.set_liveness("DELAYED")
        engine = PaperEngine(portfolio.id, quotes=cache, hub=None, now_fn=clock)

        open_position(engine, cache, session, portfolio, price=100.0)

        # Crash through the 2% stop (entry 100.05 -> stop ~98.05).
        feed_quote(cache, "AAPL", 97.0, 96.95, 97.05)
        trades = engine.check_protective_exits(session, portfolio)
        session.commit()

        assert len(trades) == 1
        position = session.execute(select(PaperPosition)).scalar_one()
        assert float(position.quantity) == 0.0
        types = [
            e.event_type
            for e in session.execute(select(PaperEngineEvent)).scalars()
        ]
        assert "stop_loss_hit" in types
        protective = session.execute(
            select(PaperOrder).where(PaperOrder.side == "SELL")
        ).scalar_one()
        assert protective.signal_snapshot["origin"] == "protective"


def test_take_profit_auto_closes_position(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    clock = Clock()
    with factory() as session:
        portfolio = seed_portfolio(
            session, risk={"default_stop_loss_pct": 2.0, "default_take_profit_pct": 4.0}
        )
        cache = QuoteCache(now_fn=clock)
        cache.set_liveness("DELAYED")
        engine = PaperEngine(portfolio.id, quotes=cache, hub=None, now_fn=clock)

        open_position(engine, cache, session, portfolio, price=100.0)

        feed_quote(cache, "AAPL", 105.0, 104.95, 105.05)  # +4% do TP em 104.05
        trades = engine.check_protective_exits(session, portfolio)
        session.commit()

        assert len(trades) == 1
        assert trades[0].realized_pnl is not None and float(trades[0].realized_pnl) > 0
        types = [
            e.event_type for e in session.execute(select(PaperEngineEvent)).scalars()
        ]
        assert "take_profit_hit" in types


def test_daily_loss_kill_switch_trips_on_fill(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    clock = Clock()
    with factory() as session:
        # Tiny daily limit so the losing round-trip trips it.
        portfolio = seed_portfolio(
            session, risk={"daily_loss_limit_pct": 0.5, "default_stop_loss_pct": 10.0}
        )
        cache = QuoteCache(now_fn=clock)
        cache.set_liveness("DELAYED")
        engine = PaperEngine(portfolio.id, quotes=cache, hub=None, now_fn=clock)

        open_position(engine, cache, session, portfolio, price=100.0)

        # -7% is far beyond the 0.5% daily limit once realized.
        feed_quote(cache, "AAPL", 93.0, 92.95, 93.05)
        close = engine.propose_from_signal(
            session, portfolio, symbol="AAPL", direction="SELL",
            strength=0.9, strategy="s", rationale="corta a perda",
        )
        engine.approve_order(session, portfolio, close)
        session.commit()

        assert portfolio.kill_switch_active is True
        assert "Perda diária" in portfolio.kill_switch_reason
        types = [
            e.event_type for e in session.execute(select(PaperEngineEvent)).scalars()
        ]
        assert "kill_switch_on" in types


def test_pnl_snapshot_reflects_unrealized_and_fees(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    clock = Clock()
    with factory() as session:
        portfolio = seed_portfolio(session)
        cache = QuoteCache(now_fn=clock)
        cache.set_liveness("DELAYED")
        engine = PaperEngine(portfolio.id, quotes=cache, hub=None, now_fn=clock)

        open_position(engine, cache, session, portfolio, price=100.0)
        feed_quote(cache, "AAPL", 103.0, 102.95, 103.05)

        pnl = engine.pnl_snapshot(session, portfolio)
        assert abs(pnl["unrealized_pnl"] - (103.0 - 100.05) * 100) < 1e-6
        assert pnl["realized_pnl_today"] == 0.0
        assert pnl["fees_today"] == 0.35
        assert pnl["trades_today"] == 1
        assert abs(pnl["equity"] - (pnl["cash"] + 103.0 * 100)) < 1e-6
