from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models import Instrument, MarketBar
from app.services.data_feed.pacing import PacingThrottle
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


def test_normalize_symbol() -> None:
    assert normalize_symbol("  aapl ") == "AAPL"
    try:
        normalize_symbol("   ")
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for empty symbol")


def test_pacing_throttle_enforces_min_interval_and_backoff() -> None:
    clock = {"t": 0.0}
    sleeps: list[float] = []

    def fake_time() -> float:
        return clock["t"]

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock["t"] += seconds

    throttle = PacingThrottle(
        min_interval_seconds=2.0, time_fn=fake_time, sleep_fn=fake_sleep
    )

    # First call: no wait.
    assert throttle.wait() == 0.0
    assert sleeps == []

    # Immediate second call: must wait the full interval.
    assert throttle.wait() == 2.0
    assert sleeps == [2.0]

    # Advance real time past the interval -> no wait needed.
    clock["t"] += 5.0
    assert throttle.wait() == 0.0

    # A failure grows backoff; next immediate call waits interval + backoff.
    throttle.record_failure()
    assert throttle.backoff_seconds == 2.0
    waited = throttle.wait()
    assert waited == 4.0  # 2.0 interval + 2.0 backoff

    # Success resets backoff.
    throttle.record_success()
    assert throttle.backoff_seconds == 0.0
