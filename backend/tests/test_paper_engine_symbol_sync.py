"""Live reconciliation of the followed symbols on a running paper engine.

``tracked_symbols`` is captured at runtime start; editing the risk settings
only rewrites the DB row. ``_sync_tracked_symbols`` (called every poll) must
pick up the diff without a backend restart: subscribe new symbols, free the
lines of removed ones, drop their cached signal state and ledger the change.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models import PaperEngineEvent, PaperPortfolio, User
from app.services.paper_trading.runtime import PaperEngineRuntime
from app.services.paper_trading.types import RiskSettings


class FakeStreamingProvider:
    def __init__(self) -> None:
        self.subscribed: list[str] = []
        self.unsubscribed: list[str] = []

    def start(self, on_tick, on_index) -> None:  # pragma: no cover - unused here
        pass

    def stop(self) -> None:  # pragma: no cover - unused here
        pass

    def subscribe(self, symbol: str) -> None:
        self.subscribed.append(symbol)

    def unsubscribe(self, symbol: str) -> None:
        self.unsubscribed.append(symbol)

    def subscribe_index(self, symbol: str) -> None:  # pragma: no cover - unused
        pass


def build_session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite:///{tmp_path / 'test_symbol_sync.db'}")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def make_portfolio(session: Session, symbols: list[str]) -> int:
    user = User(email="sync@example.com", password_hash="hash")
    session.add(user)
    session.flush()
    portfolio = PaperPortfolio(
        owner_user_id=user.id,
        initial_cash=Decimal("100000"),
        cash=Decimal("100000"),
        equity=Decimal("100000"),
        risk_settings={"symbols": symbols},
        engine_running=True,
    )
    session.add(portfolio)
    session.commit()
    return portfolio.id


def make_runtime(portfolio_id: int, provider: FakeStreamingProvider) -> PaperEngineRuntime:
    settings = SimpleNamespace(
        ibkr_market_data_type=1,
        paper_engine_poll_seconds=5.0,
        realtime_feed_symbol_list=["SPY"],
    )
    return PaperEngineRuntime(
        portfolio_id, settings=settings, provider=provider, poll_seconds=5.0
    )


def test_sync_applies_added_and_removed_symbols(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    with factory() as session:
        portfolio_id = make_portfolio(session, ["AAPL", "MSFT"])

    provider = FakeStreamingProvider()
    runtime = make_runtime(portfolio_id, provider)
    runtime.tracked_symbols = ["AAPL", "MSFT"]  # as start() would have set
    now = datetime.now(UTC)
    runtime._last_signal_bar = {("MSFT", "sma"): now, ("AAPL", "sma"): now}
    runtime._signal_results = {
        ("MSFT", "sma"): {"strategy": "sma", "outcome": "none"},
        ("AAPL", "sma"): {"strategy": "sma", "outcome": "none"},
    }
    runtime.last_signals = {"MSFT": {"signals": []}, "AAPL": {"signals": []}}

    with factory() as session:
        runtime._sync_tracked_symbols(
            session, RiskSettings.from_json({"symbols": ["AAPL", "NVDA"]})
        )
        session.commit()

    assert runtime.tracked_symbols == ["AAPL", "NVDA"]
    assert provider.subscribed == ["NVDA"]
    assert provider.unsubscribed == ["MSFT"]
    # Cached signal state of the removed symbol is gone; the kept one stays.
    assert ("MSFT", "sma") not in runtime._last_signal_bar
    assert ("AAPL", "sma") in runtime._last_signal_bar
    assert "MSFT" not in runtime.last_signals
    with factory() as session:
        events = list(
            session.execute(
                select(PaperEngineEvent).where(
                    PaperEngineEvent.portfolio_id == portfolio_id
                )
            ).scalars()
        )
    assert [e.event_type for e in events] == ["symbols_updated"]
    assert events[0].payload["added"] == ["NVDA"]
    assert events[0].payload["removed"] == ["MSFT"]


def test_sync_is_a_noop_when_symbols_unchanged(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    with factory() as session:
        portfolio_id = make_portfolio(session, ["AAPL"])

    provider = FakeStreamingProvider()
    runtime = make_runtime(portfolio_id, provider)
    runtime.tracked_symbols = ["AAPL"]

    with factory() as session:
        runtime._sync_tracked_symbols(session, RiskSettings.from_json({"symbols": ["AAPL"]}))
        session.commit()

    assert provider.subscribed == []
    assert provider.unsubscribed == []
    with factory() as session:
        assert (
            session.execute(select(PaperEngineEvent)).scalars().first() is None
        )


def test_sync_falls_back_to_settings_default_when_emptied(tmp_path: Path) -> None:
    """Clearing the symbols in the cockpit falls back to the configured default."""
    factory = build_session_factory(tmp_path)
    with factory() as session:
        portfolio_id = make_portfolio(session, ["AAPL"])

    provider = FakeStreamingProvider()
    runtime = make_runtime(portfolio_id, provider)
    runtime.tracked_symbols = ["AAPL"]

    with factory() as session:
        runtime._sync_tracked_symbols(session, RiskSettings.from_json({"symbols": []}))
        session.commit()

    assert runtime.tracked_symbols == ["SPY"]
    assert provider.subscribed == ["SPY"]
    assert provider.unsubscribed == ["AAPL"]
