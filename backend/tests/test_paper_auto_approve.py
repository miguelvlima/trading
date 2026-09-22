"""Auto-approve (modo automático): with ``auto_approve`` on, the runtime
approves its own proposals on the spot — no user click — while every risk
check (vetoes, kill switch, flat EOD) keeps applying. The ledger records
whether an approval was automatic or human."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models import PaperEngineEvent, PaperOrder, PaperPortfolio, User
from app.services.data_feed.types import Tick
from app.services.paper_trading.engine import PaperEngine
from app.services.paper_trading.quotes import QuoteCache
from app.services.paper_trading.runtime import MIN_STRATEGY_BARS, PaperEngineRuntime
from app.services.paper_trading.types import (
    STATUS_FILLED,
    STATUS_PROPOSED,
    RiskSettings,
)

RTH_NOW = datetime(2026, 7, 8, 15, 0, tzinfo=UTC)  # Wednesday 15:00 UTC


def build_session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite:///{tmp_path / 'test_auto_approve.db'}")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def seed_portfolio(session: Session, *, risk: dict | None = None) -> PaperPortfolio:
    user = User(email="auto@example.com", password_hash="hash")
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


def feed_quote(cache: QuoteCache, symbol: str, last: float) -> None:
    cache.update_from_tick(
        Tick(
            symbol=symbol,
            timestamp=RTH_NOW,
            last=Decimal(str(last)),
            bid=Decimal(str(last - 0.05)),
            ask=Decimal(str(last + 0.05)),
        )
    )


def approval_events(session: Session, portfolio_id: int) -> list[PaperEngineEvent]:
    return list(
        session.execute(
            select(PaperEngineEvent)
            .where(
                PaperEngineEvent.portfolio_id == portfolio_id,
                PaperEngineEvent.event_type == "order_approved",
            )
            .order_by(PaperEngineEvent.id)
        ).scalars()
    )


# -- engine level: the ledger tells human and automatic approvals apart ---------


def test_auto_approval_is_marked_in_the_ledger(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    with factory() as session:
        portfolio = seed_portfolio(session)
        cache = QuoteCache(now_fn=lambda: RTH_NOW)
        cache.set_liveness("DELAYED")
        engine = PaperEngine(portfolio.id, quotes=cache, hub=None, now_fn=lambda: RTH_NOW)
        feed_quote(cache, "AAPL", 100.0)

        order = engine.propose_from_signal(
            session,
            portfolio,
            symbol="AAPL",
            direction="BUY",
            strength=0.9,
            strategy="rsi_mean_reversion",
            rationale="RSI em sobrevenda.",
            signal_timestamp=RTH_NOW,
        )
        assert order is not None and order.status == STATUS_PROPOSED

        engine.approve_order(session, portfolio, order, auto=True)
        session.commit()

        assert order.status == STATUS_FILLED  # fresh quote fills immediately
        events = approval_events(session, portfolio.id)
        assert len(events) == 1
        assert events[0].payload["origin"] == "auto"
        assert "automaticamente" in events[0].message


def test_manual_approval_keeps_user_origin(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    with factory() as session:
        portfolio = seed_portfolio(session)
        cache = QuoteCache(now_fn=lambda: RTH_NOW)
        cache.set_liveness("DELAYED")
        engine = PaperEngine(portfolio.id, quotes=cache, hub=None, now_fn=lambda: RTH_NOW)
        feed_quote(cache, "AAPL", 100.0)

        order = engine.propose_from_signal(
            session,
            portfolio,
            symbol="AAPL",
            direction="BUY",
            strength=0.9,
            strategy="rsi_mean_reversion",
            rationale="RSI em sobrevenda.",
            signal_timestamp=RTH_NOW,
        )
        engine.approve_order(session, portfolio, order)
        session.commit()

        events = approval_events(session, portfolio.id)
        assert len(events) == 1
        assert events[0].payload["origin"] == "user"
        assert "pelo utilizador" in events[0].message


# -- runtime level: _evaluate_signals approves its own proposals ------------------


def build_runtime(portfolio_id: int) -> PaperEngineRuntime:
    settings = SimpleNamespace(
        ibkr_market_data_type=3,
        paper_engine_poll_seconds=5.0,
        paper_engine_bars_limit=300,
        paper_engine_intraday_enabled=False,
        realtime_feed_provider="none",
        realtime_feed_symbol_list=["SPY"],
    )
    runtime = PaperEngineRuntime(
        portfolio_id, settings=settings, provider=None, poll_seconds=5.0
    )
    runtime.tracked_symbols = ["AAPL"]
    return runtime


def patch_strategy_pipeline(monkeypatch: pytest.MonkeyPatch, *, bar_time: datetime) -> None:
    """One fake strategy that always fires a strong BUY on the last closed bar."""
    bars = [SimpleNamespace(timestamp=bar_time) for _ in range(MIN_STRATEGY_BARS)]
    monkeypatch.setattr(
        "app.services.paper_trading.runtime.load_strategy_bars",
        lambda db, symbol, timeframe, limit: bars,
    )
    monkeypatch.setattr(
        "app.services.paper_trading.runtime.run_strategy",
        lambda strategy, symbol, history: [
            SimpleNamespace(
                timestamp=bar_time,
                direction="BUY",
                strength=0.9,
                strategy=strategy,
                rationale="sinal de teste",
                suggested_stop_pct=None,
                suggested_take_profit_pct=None,
            )
        ],
    )


RUNTIME_RISK = {
    # rth_only off: the runtime engine uses the real clock, and this test must
    # not depend on the wall-clock hour it runs at.
    "rth_only": False,
    "strategies": ["fake_strategy"],
    "symbols": ["AAPL"],
}


def test_runtime_auto_approves_and_fills_proposals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = build_session_factory(tmp_path)
    with factory() as session:
        portfolio = seed_portfolio(session, risk={**RUNTIME_RISK, "auto_approve": True})
        portfolio_id = portfolio.id

    runtime = build_runtime(portfolio_id)
    runtime._on_tick(
        Tick(
            symbol="AAPL",
            timestamp=datetime.now(UTC),
            last=Decimal("100.00"),
            bid=Decimal("99.95"),
            ask=Decimal("100.05"),
        )
    )
    patch_strategy_pipeline(monkeypatch, bar_time=RTH_NOW)

    with factory() as session:
        portfolio = session.get(PaperPortfolio, portfolio_id)
        risk = RiskSettings.from_json(portfolio.risk_settings)
        runtime._evaluate_signals(session, portfolio, risk)
        session.commit()

        order = session.execute(
            select(PaperOrder).where(PaperOrder.portfolio_id == portfolio_id)
        ).scalar_one()
        assert order.status == STATUS_FILLED  # approved by the engine and filled
        events = approval_events(session, portfolio_id)
        assert len(events) == 1
        assert events[0].payload["origin"] == "auto"

    assert runtime._signal_results[("AAPL", "fake_strategy")]["outcome"] == "auto_approved"


def test_runtime_without_auto_approve_leaves_proposal_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = build_session_factory(tmp_path)
    with factory() as session:
        portfolio = seed_portfolio(session, risk=dict(RUNTIME_RISK))
        portfolio_id = portfolio.id

    runtime = build_runtime(portfolio_id)
    runtime._on_tick(
        Tick(
            symbol="AAPL",
            timestamp=datetime.now(UTC),
            last=Decimal("100.00"),
            bid=Decimal("99.95"),
            ask=Decimal("100.05"),
        )
    )
    patch_strategy_pipeline(monkeypatch, bar_time=RTH_NOW)

    with factory() as session:
        portfolio = session.get(PaperPortfolio, portfolio_id)
        risk = RiskSettings.from_json(portfolio.risk_settings)
        runtime._evaluate_signals(session, portfolio, risk)
        session.commit()

        order = session.execute(
            select(PaperOrder).where(PaperOrder.portfolio_id == portfolio_id)
        ).scalar_one()
        assert order.status == STATUS_PROPOSED  # still waiting for the user
        assert approval_events(session, portfolio_id) == []

    assert runtime._signal_results[("AAPL", "fake_strategy")]["outcome"] == "proposed"
