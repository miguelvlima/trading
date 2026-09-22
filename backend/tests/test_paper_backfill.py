"""History backfill (kills the intraday warm-up): when a tracked symbol has
fewer closed bars than the strategies need, the runtime fetches history from
the market-data provider once and persists it into ``MarketBar`` — the same
table the engine reads — so a new symbol is evaluable on the first poll.
Failures degrade gracefully to today's behaviour (bars build up from ticks)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models import Instrument, MarketBar, PaperEngineEvent, PaperPortfolio, User
from app.services.data_feed.types import BarQuote
from app.services.paper_trading.runtime import (
    _BACKFILL_MAX_ATTEMPTS,
    _BACKFILL_SYMBOLS_PER_POLL,
    MIN_STRATEGY_BARS,
    PaperEngineRuntime,
)
from app.services.paper_trading.types import RiskSettings

RTH_NOW = datetime(2026, 7, 8, 15, 0, tzinfo=UTC)  # Wednesday 15:00 UTC


def build_session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite:///{tmp_path / 'test_backfill.db'}")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def seed_portfolio(session: Session, *, risk: dict | None = None) -> int:
    user = User(email="backfill@example.com", password_hash="hash")
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
    return portfolio.id


def build_runtime(portfolio_id: int, *, backfill_enabled: bool = True) -> PaperEngineRuntime:
    settings = SimpleNamespace(
        ibkr_market_data_type=3,
        paper_engine_poll_seconds=5.0,
        paper_engine_bars_limit=300,
        paper_engine_intraday_enabled=False,
        paper_engine_backfill_enabled=backfill_enabled,
        realtime_feed_provider="none",
        realtime_feed_symbol_list=["SPY"],
    )
    return PaperEngineRuntime(
        portfolio_id, settings=settings, provider=None, poll_seconds=5.0
    )


class FakeHistoryProvider:
    """MarketDataProvider stub: N closed 5m bars ending at RTH_NOW, call-counted."""

    def __init__(self, bars_per_fetch: int = 300) -> None:
        self.bars_per_fetch = bars_per_fetch
        self.calls: list[tuple[str, str, int]] = []

    def fetch_recent_bars(self, symbol: str, timeframe: str, limit: int) -> list[BarQuote]:
        self.calls.append((symbol, timeframe, limit))
        count = min(self.bars_per_fetch, limit)
        return [
            BarQuote(
                symbol=symbol,
                timestamp=RTH_NOW - timedelta(minutes=5 * (count - i)),
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100.5"),
                volume=Decimal("1000"),
                is_final=True,
            )
            for i in range(count)
        ]


def use_provider(runtime: PaperEngineRuntime, provider: FakeHistoryProvider | None) -> None:
    runtime._history_provider_resolved = True
    runtime._history_provider_instance = provider


def bar_count(session: Session, symbol: str, timeframe: str) -> int:
    return len(
        list(
            session.execute(
                select(MarketBar)
                .join(Instrument, MarketBar.instrument_id == Instrument.id)
                .where(Instrument.symbol == symbol, MarketBar.timeframe == timeframe)
            ).scalars()
        )
    )


RISK_5M = RiskSettings.from_json({"timeframe": "5m", "symbols": ["AAPL"]})


def test_backfill_persists_history_once_and_records_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = build_session_factory(tmp_path)
    monkeypatch.setattr("app.services.paper_trading.runtime.SessionLocal", factory)
    with factory() as session:
        portfolio_id = seed_portfolio(session)

    runtime = build_runtime(portfolio_id)
    runtime.tracked_symbols = ["AAPL"]
    provider = FakeHistoryProvider()
    use_provider(runtime, provider)

    with factory() as session:
        runtime._backfill_history(session, RISK_5M)
        session.commit()

        assert bar_count(session, "AAPL", "5m") == 300
        events = list(
            session.execute(
                select(PaperEngineEvent).where(
                    PaperEngineEvent.portfolio_id == portfolio_id,
                    PaperEngineEvent.event_type == "history_backfilled",
                )
            ).scalars()
        )
        assert len(events) == 1
        assert events[0].symbol == "AAPL"
        assert events[0].payload["inserted"] == 300

        # One shot per (symbol, timeframe): a second poll must not refetch.
        runtime._backfill_history(session, RISK_5M)
        assert len(provider.calls) == 1


def test_backfill_skips_symbols_that_already_have_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = build_session_factory(tmp_path)
    monkeypatch.setattr("app.services.paper_trading.runtime.SessionLocal", factory)
    with factory() as session:
        portfolio_id = seed_portfolio(session)
        instrument = Instrument(symbol="AAPL", name=None, currency="USD")
        session.add(instrument)
        session.flush()
        for i in range(MIN_STRATEGY_BARS):
            session.add(
                MarketBar(
                    instrument_id=instrument.id,
                    timeframe="5m",
                    timestamp=RTH_NOW - timedelta(minutes=5 * (MIN_STRATEGY_BARS - i)),
                    open=Decimal("100"),
                    high=Decimal("101"),
                    low=Decimal("99"),
                    close=Decimal("100.5"),
                    volume=Decimal("1000"),
                )
            )
        session.commit()

    runtime = build_runtime(portfolio_id)
    runtime.tracked_symbols = ["AAPL"]
    provider = FakeHistoryProvider()
    use_provider(runtime, provider)

    with factory() as session:
        runtime._backfill_history(session, RISK_5M)

    assert provider.calls == []
    assert ("AAPL", "5m") in runtime._backfill_done


def test_backfill_disabled_or_without_provider_is_a_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = build_session_factory(tmp_path)
    monkeypatch.setattr("app.services.paper_trading.runtime.SessionLocal", factory)
    with factory() as session:
        portfolio_id = seed_portfolio(session)

    disabled = build_runtime(portfolio_id, backfill_enabled=False)
    disabled.tracked_symbols = ["AAPL"]
    provider = FakeHistoryProvider()
    use_provider(disabled, provider)
    with factory() as session:
        disabled._backfill_history(session, RISK_5M)
    assert provider.calls == []
    assert disabled._backfill_done == set()  # may run later if re-enabled

    # Provider resolution failed (e.g. provider "none", no Gateway): behave
    # like today — no fetch, symbols marked handled so we stop asking.
    no_provider = build_runtime(portfolio_id)
    no_provider.tracked_symbols = ["AAPL"]
    use_provider(no_provider, None)
    with factory() as session:
        no_provider._backfill_history(session, RISK_5M)
        assert bar_count(session, "AAPL", "5m") == 0
    assert ("AAPL", "5m") in no_provider._backfill_done


def test_backfill_caps_symbols_per_poll(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = build_session_factory(tmp_path)
    monkeypatch.setattr("app.services.paper_trading.runtime.SessionLocal", factory)
    with factory() as session:
        portfolio_id = seed_portfolio(session)

    symbols = ["AAPL", "AMD", "AMZN", "GOOGL", "MSFT", "NVDA"]
    runtime = build_runtime(portfolio_id)
    runtime.tracked_symbols = symbols
    provider = FakeHistoryProvider()
    use_provider(runtime, provider)
    risk = RiskSettings.from_json({"timeframe": "5m", "symbols": symbols})

    with factory() as session:
        runtime._backfill_history(session, risk)
        assert len(provider.calls) == _BACKFILL_SYMBOLS_PER_POLL
        # The next poll finishes the tail.
        runtime._backfill_history(session, risk)
        assert len(provider.calls) == len(symbols)


def test_backfill_gives_up_after_repeated_empty_fetches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = build_session_factory(tmp_path)
    monkeypatch.setattr("app.services.paper_trading.runtime.SessionLocal", factory)
    with factory() as session:
        portfolio_id = seed_portfolio(session)

    runtime = build_runtime(portfolio_id)
    runtime.tracked_symbols = ["AAPL"]
    provider = FakeHistoryProvider(bars_per_fetch=0)  # dead feed: always empty
    use_provider(runtime, provider)

    with factory() as session:
        for _ in range(_BACKFILL_MAX_ATTEMPTS):
            runtime._backfill_history(session, RISK_5M)
        assert len(provider.calls) == _BACKFILL_MAX_ATTEMPTS
        assert ("AAPL", "5m") in runtime._backfill_done
        # Given up: no further fetches.
        runtime._backfill_history(session, RISK_5M)
        assert len(provider.calls) == _BACKFILL_MAX_ATTEMPTS
