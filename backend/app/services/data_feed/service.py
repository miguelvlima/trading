from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Instrument, MarketBar
from app.services.data_feed.types import BarQuote

logger = structlog.get_logger(__name__)

MAX_SYMBOL_LENGTH = 32
MAX_RECENT_ERRORS = 20


def normalize_symbol(symbol: str) -> str:
    cleaned = symbol.strip().upper()
    if not cleaned:
        raise ValueError("symbol must not be empty")
    if len(cleaned) > MAX_SYMBOL_LENGTH:
        raise ValueError(f"symbol exceeds {MAX_SYMBOL_LENGTH} characters: {symbol!r}")
    return cleaned


def _coerce_utc(value: datetime) -> datetime:
    """Return a timezone-aware UTC datetime (SQLite reads back naive values)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@dataclass
class IngestResult:
    symbol: str
    timeframe: str
    inserted: int
    updated: int

    @property
    def total(self) -> int:
        return self.inserted + self.updated


@dataclass
class FeedHealth:
    provider: str
    status: str  # "running" | "stale" | "empty"
    last_update: datetime | None
    lag_seconds: float | None
    tracked_symbols: list[str]
    recent_errors: list[str] = field(default_factory=list)


class DataFeedService:
    """Ingest provider quotes into ``market_bars`` and report feed health.

    The upsert is intentionally dialect-agnostic (select-then-write) so the same
    code path runs under the SQLite test harness and Postgres in production,
    honouring the ``uq_market_bars_instrument_timeframe_timestamp`` constraint.
    """

    def __init__(
        self,
        session: Session,
        *,
        provider_name: str = "unknown",
        now_fn: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session = session
        self._provider_name = provider_name
        self._now_fn = now_fn
        self._recent_errors: list[str] = []

    def record_error(self, message: str) -> None:
        self._recent_errors.append(message)
        if len(self._recent_errors) > MAX_RECENT_ERRORS:
            self._recent_errors = self._recent_errors[-MAX_RECENT_ERRORS:]

    def _get_or_create_instrument(self, symbol: str) -> Instrument:
        instrument = self._session.execute(
            select(Instrument).where(Instrument.symbol == symbol)
        ).scalar_one_or_none()
        if instrument is not None:
            return instrument

        instrument = Instrument(symbol=symbol, currency="USD")
        self._session.add(instrument)
        self._session.flush()
        logger.info("instrument_created", symbol=symbol)
        return instrument

    def _upsert_bar(self, instrument: Instrument, quote: BarQuote, timeframe: str) -> bool:
        """Insert or update a single bar. Returns True if a new row was inserted."""
        timestamp = _coerce_utc(quote.timestamp)
        existing = self._session.execute(
            select(MarketBar).where(
                MarketBar.instrument_id == instrument.id,
                MarketBar.timeframe == timeframe,
                MarketBar.timestamp == timestamp,
            )
        ).scalar_one_or_none()

        if existing is None:
            self._session.add(
                MarketBar(
                    instrument_id=instrument.id,
                    timeframe=timeframe,
                    timestamp=timestamp,
                    open=quote.open,
                    high=quote.high,
                    low=quote.low,
                    close=quote.close,
                    volume=quote.volume,
                )
            )
            return True

        existing.open = quote.open
        existing.high = quote.high
        existing.low = quote.low
        existing.close = quote.close
        existing.volume = quote.volume
        return False

    def ingest_bars(
        self,
        symbol: str,
        timeframe: str,
        quotes: Iterable[BarQuote],
    ) -> IngestResult:
        normalized = normalize_symbol(symbol)
        instrument = self._get_or_create_instrument(normalized)

        inserted = 0
        updated = 0
        for quote in quotes:
            if self._upsert_bar(instrument, quote, timeframe):
                inserted += 1
            else:
                updated += 1

        self._session.commit()
        logger.info(
            "bars_ingested",
            symbol=normalized,
            timeframe=timeframe,
            inserted=inserted,
            updated=updated,
        )
        return IngestResult(
            symbol=normalized, timeframe=timeframe, inserted=inserted, updated=updated
        )

    def get_health(
        self,
        symbols: Sequence[str],
        timeframe: str,
        *,
        stale_after_seconds: float = 120.0,
    ) -> FeedHealth:
        normalized = [normalize_symbol(symbol) for symbol in symbols]
        now = self._now_fn()

        last_update: datetime | None = None
        if normalized:
            last_update = self._session.execute(
                select(MarketBar.timestamp)
                .join(Instrument, MarketBar.instrument_id == Instrument.id)
                .where(
                    Instrument.symbol.in_(normalized),
                    MarketBar.timeframe == timeframe,
                )
                .order_by(MarketBar.timestamp.desc())
                .limit(1)
            ).scalar_one_or_none()

        if last_update is None:
            return FeedHealth(
                provider=self._provider_name,
                status="empty",
                last_update=None,
                lag_seconds=None,
                tracked_symbols=normalized,
                recent_errors=list(self._recent_errors[-10:]),
            )

        last_update = _coerce_utc(last_update)
        lag_seconds = (now - last_update).total_seconds()
        status = "stale" if lag_seconds > stale_after_seconds else "running"
        return FeedHealth(
            provider=self._provider_name,
            status=status,
            last_update=last_update,
            lag_seconds=lag_seconds,
            tracked_symbols=normalized,
            recent_errors=list(self._recent_errors[-10:]),
        )
