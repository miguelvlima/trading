from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models import Instrument, MarketBar
from app.services.data_feed.service import DataFeedService, normalize_symbol
from fakes import build_bar_quotes


def _build_session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite:///{tmp_path / 'test_data_feed.db'}")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_ingest_creates_instrument_and_bars(tmp_path: Path) -> None:
    session_factory = _build_session_factory(tmp_path)
    quotes = build_bar_quotes("aapl", count=5)

    with session_factory() as session:
        service = DataFeedService(session, provider_name="fake")
        result = service.ingest_bars("aapl", "1d", quotes)

    assert result.symbol == "AAPL"
    assert result.inserted == 5
    assert result.updated == 0

    with session_factory() as session:
        instrument = session.execute(
            select(Instrument).where(Instrument.symbol == "AAPL")
        ).scalar_one()
        bar_count = session.execute(
            select(func.count()).select_from(MarketBar).where(
                MarketBar.instrument_id == instrument.id
            )
        ).scalar_one()
    assert bar_count == 5


def test_ingest_is_idempotent_upsert(tmp_path: Path) -> None:
    session_factory = _build_session_factory(tmp_path)
    quotes = build_bar_quotes("MSFT", count=3)

    with session_factory() as session:
        DataFeedService(session, provider_name="fake").ingest_bars("MSFT", "1d", quotes)

    # Re-ingest the same timestamps with a mutated close price.
    mutated = [
        type(quote)(
            symbol=quote.symbol,
            timestamp=quote.timestamp,
            open=quote.open,
            high=quote.high,
            low=quote.low,
            close=quote.close + Decimal("10"),
            volume=quote.volume,
        )
        for quote in quotes
    ]

    with session_factory() as session:
        result = DataFeedService(session, provider_name="fake").ingest_bars("MSFT", "1d", mutated)

    assert result.inserted == 0
    assert result.updated == 3

    with session_factory() as session:
        instrument = session.execute(
            select(Instrument).where(Instrument.symbol == "MSFT")
        ).scalar_one()
        bars = session.execute(
            select(MarketBar)
            .where(MarketBar.instrument_id == instrument.id)
            .order_by(MarketBar.timestamp.asc())
        ).scalars().all()

    assert len(bars) == 3  # no duplicates created
    assert bars[0].close == Decimal("110")  # base 100 + mutation 10


def test_get_health_empty_running_and_stale(tmp_path: Path) -> None:
    session_factory = _build_session_factory(tmp_path)
    now = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)

    # No data yet -> empty.
    with session_factory() as session:
        service = DataFeedService(session, provider_name="fake", now_fn=lambda: now)
        health = service.get_health(["AAPL"], "1d", stale_after_seconds=120)
    assert health.status == "empty"
    assert health.last_update is None
    assert health.lag_seconds is None
    assert health.tracked_symbols == ["AAPL"]

    # Fresh bar -> running.
    fresh_ts = now - timedelta(seconds=30)
    with session_factory() as session:
        DataFeedService(session, provider_name="fake").ingest_bars(
            "AAPL", "1d", build_bar_quotes("AAPL", count=1, start=fresh_ts)
        )
        service = DataFeedService(session, provider_name="fake", now_fn=lambda: now)
        health = service.get_health(["AAPL"], "1d", stale_after_seconds=120)
    assert health.status == "running"
    assert health.lag_seconds is not None and 0 <= health.lag_seconds <= 120

    # Same data, tight staleness threshold -> stale.
    with session_factory() as session:
        service = DataFeedService(session, provider_name="fake", now_fn=lambda: now)
        health = service.get_health(["AAPL"], "1d", stale_after_seconds=5)
    assert health.status == "stale"


def test_non_final_bar_is_not_persisted(tmp_path: Path) -> None:
    session_factory = _build_session_factory(tmp_path)
    # 4 bars where the most recent is still in formation (is_final=False).
    quotes = build_bar_quotes("NVDA", count=4, last_is_non_final=True)

    with session_factory() as session:
        result = DataFeedService(session, provider_name="fake").ingest_bars("NVDA", "1d", quotes)

    assert result.inserted == 3
    assert result.skipped_non_final == 1

    with session_factory() as session:
        instrument = session.execute(
            select(Instrument).where(Instrument.symbol == "NVDA")
        ).scalar_one()
        timestamps = session.execute(
            select(MarketBar.timestamp)
            .where(MarketBar.instrument_id == instrument.id)
            .order_by(MarketBar.timestamp.asc())
        ).scalars().all()

    assert len(timestamps) == 3
    # The non-final bar (last timestamp in the series) must be absent.
    assert quotes[-1].timestamp not in timestamps


def test_get_or_create_instrument_recovers_from_race(tmp_path: Path) -> None:
    session_factory = _build_session_factory(tmp_path)

    # Simulate a concurrent writer having already created the instrument.
    with session_factory() as session:
        session.add(Instrument(symbol="AMD", currency="USD"))
        session.commit()

    with session_factory() as session:
        service = DataFeedService(session, provider_name="fake")
        result = service.ingest_bars("amd", "1d", build_bar_quotes("AMD", count=2))

    assert result.inserted == 2

    with session_factory() as session:
        count = session.execute(
            select(func.count()).select_from(Instrument).where(Instrument.symbol == "AMD")
        ).scalar_one()
    assert count == 1  # no duplicate instrument created


def test_get_health_reports_error_when_stale_with_recorded_error(tmp_path: Path) -> None:
    session_factory = _build_session_factory(tmp_path)
    now = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)

    with session_factory() as session:
        DataFeedService(session, provider_name="fake").ingest_bars(
            "AAPL", "1d", build_bar_quotes("AAPL", count=1, start=now - timedelta(days=2))
        )
        service = DataFeedService(session, provider_name="fake", now_fn=lambda: now)
        service.record_error("provider boom")
        health = service.get_health(["AAPL"], "1d", stale_after_seconds=180)

    assert health.status == "error"
    assert "provider boom" in health.recent_errors


def test_normalize_symbol() -> None:
    assert normalize_symbol("  aapl ") == "AAPL"
    try:
        normalize_symbol("   ")
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for empty symbol")
