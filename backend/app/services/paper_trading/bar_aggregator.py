from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.services.data_feed.types import Tick

# Intraday timeframes the aggregator can build from ticks. Deliberately short:
# anything larger is resampled from these by whoever needs it.
SUPPORTED_TIMEFRAMES: dict[str, timedelta] = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
}


@dataclass(frozen=True)
class AggregatedBar:
    """One closed OHLCV bar produced from stream ticks (bucket start in UTC)."""

    symbol: str
    timeframe: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class _Bucket:
    __slots__ = ("open", "high", "low", "close", "volume")

    def __init__(self, price: float) -> None:
        self.open = price
        self.high = price
        self.low = price
        self.close = price
        self.volume = 0.0

    def update(self, price: float) -> None:
        self.high = max(self.high, price)
        self.low = min(self.low, price)
        self.close = price


def _floor_to_bucket(timestamp: datetime, delta: timedelta) -> datetime:
    """Start of the bucket containing ``timestamp``, aligned to the UTC clock."""
    seconds = delta.total_seconds()
    epoch = timestamp.astimezone(UTC).timestamp()
    return datetime.fromtimestamp(epoch // seconds * seconds, tz=UTC)


class BarAggregator:
    """Accumulates stream ticks into intraday OHLCV bars, per (symbol, timeframe).

    Two halves, on two threads:

    - ``update_from_tick`` runs on the provider thread — lock only, no DB, no
      I/O. Buckets are aligned to the UTC clock (floor of the tick timestamp to
      the timeframe multiple).
    - ``drain_closed_bars`` runs on the poll loop — returns and forgets every
      bucket whose period already ended, so the caller can persist them.

    Ticks without ``last`` are ignored for OHLC. ``Tick.volume`` is the
    CUMULATIVE session volume (see ``data_feed.types.Tick``), so per-bar volume
    is the delta between consecutive readings — never the raw field. A bucket
    that saw no ticks produces no bar (no forward-fill at this layer).
    """

    def __init__(self, timeframes: tuple[str, ...] = ("1m", "5m")) -> None:
        unknown = [tf for tf in timeframes if tf not in SUPPORTED_TIMEFRAMES]
        if unknown:
            raise ValueError(f"Unsupported intraday timeframes: {unknown}")
        self._timeframes = tuple(timeframes)
        self._lock = threading.Lock()
        # (symbol, timeframe) -> {bucket_start: _Bucket}; multiple buckets can
        # coexist briefly (a closed one awaiting drain plus the forming one).
        self._buckets: dict[tuple[str, str], dict[datetime, _Bucket]] = {}
        # Last cumulative session volume seen per symbol, the delta baseline.
        self._last_cum_volume: dict[str, float] = {}

    def update_from_tick(self, tick: Tick) -> None:
        symbol = tick.symbol.upper()
        with self._lock:
            volume_delta = self._volume_delta_locked(symbol, tick)
            if tick.last is None:
                return  # no price: nothing to anchor OHLC on
            price = float(tick.last)
            for timeframe in self._timeframes:
                start = _floor_to_bucket(tick.timestamp, SUPPORTED_TIMEFRAMES[timeframe])
                buckets = self._buckets.setdefault((symbol, timeframe), {})
                bucket = buckets.get(start)
                if bucket is None:
                    bucket = _Bucket(price)
                    buckets[start] = bucket
                else:
                    bucket.update(price)
                bucket.volume += volume_delta

    def _volume_delta_locked(self, symbol: str, tick: Tick) -> float:
        if tick.volume is None:
            return 0.0
        cumulative = float(tick.volume)
        previous = self._last_cum_volume.get(symbol)
        self._last_cum_volume[symbol] = cumulative
        if previous is None or cumulative < previous:
            # First reading (unknown baseline) or a session reset: no delta.
            return 0.0
        return cumulative - previous

    def drain_closed_bars(self, now: datetime) -> list[AggregatedBar]:
        """Remove and return every bucket whose period ended (bucket_end <= now)."""
        closed: list[AggregatedBar] = []
        with self._lock:
            for (symbol, timeframe), buckets in self._buckets.items():
                delta = SUPPORTED_TIMEFRAMES[timeframe]
                for start in [s for s in buckets if s + delta <= now]:
                    bucket = buckets.pop(start)
                    closed.append(
                        AggregatedBar(
                            symbol=symbol,
                            timeframe=timeframe,
                            timestamp=start,
                            open=bucket.open,
                            high=bucket.high,
                            low=bucket.low,
                            close=bucket.close,
                            volume=bucket.volume,
                        )
                    )
        closed.sort(key=lambda bar: (bar.timestamp, bar.symbol, bar.timeframe))
        return closed
