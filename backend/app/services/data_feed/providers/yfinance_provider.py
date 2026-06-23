from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import structlog

from app.services.data_feed.pacing import PacingThrottle
from app.services.data_feed.types import BarQuote, is_period_closed

logger = structlog.get_logger(__name__)

# Map our short timeframe strings to yfinance ``interval`` values and a sensible
# default lookback ``period`` so a single ``history`` call covers the request.
_TIMEFRAME_TO_INTERVAL: dict[str, str] = {
    "1m": "1m",
    "2m": "2m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "60m": "60m",
    "1h": "60m",
    "90m": "90m",
    "1d": "1d",
    "5d": "5d",
    "1wk": "1wk",
    "1mo": "1mo",
    "3mo": "3mo",
}

# yfinance caps intraday history; pick a period generous enough for ``limit`` bars.
_INTRADAY_INTERVALS = {"1m", "2m", "5m", "15m", "30m", "60m", "90m"}


def _to_decimal(value: object) -> Decimal:
    return Decimal(str(value))


class YFinanceProvider:
    """REST/polling provider backed by the ``yfinance`` library.

    Network calls are paced by a :class:`PacingThrottle` with one retry on
    transient errors, to avoid tripping Yahoo's rate limiting.
    """

    name = "yfinance"

    def __init__(
        self,
        *,
        min_request_interval_seconds: float = 1.0,
        max_retries: int = 2,
    ) -> None:
        self._throttle = PacingThrottle(min_request_interval_seconds)
        self._max_retries = max(1, max_retries)

    def _interval_for(self, timeframe: str) -> str:
        interval = _TIMEFRAME_TO_INTERVAL.get(timeframe.strip().lower())
        if interval is None:
            raise ValueError(f"Unsupported timeframe for yfinance: {timeframe!r}")
        return interval

    def _period_for(self, interval: str, limit: int) -> str:
        if interval in _INTRADAY_INTERVALS:
            # Intraday data is only retained for a limited window by Yahoo.
            return "5d" if interval in {"1m", "2m"} else "1mo"
        # Daily+ data: request roughly ``limit`` calendar days with headroom.
        days = max(limit * 2, 30)
        return f"{days}d"

    def _download(self, symbol: str, interval: str, period: str):
        import yfinance as yf

        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            self._throttle.wait()
            try:
                ticker = yf.Ticker(symbol)
                frame = ticker.history(period=period, interval=interval, auto_adjust=False)
                self._throttle.record_success()
                return frame
            except Exception as exc:  # noqa: BLE001 - provider errors are opaque
                last_exc = exc
                self._throttle.record_failure()
                logger.warning(
                    "yfinance_fetch_failed",
                    symbol=symbol,
                    interval=interval,
                    attempt=attempt + 1,
                    error=str(exc),
                )
        assert last_exc is not None
        raise last_exc

    def _frame_to_quotes(self, symbol: str, timeframe: str, frame) -> list[BarQuote]:
        # ``now`` is used only to decide whether each bar's period has closed,
        # never as a bar timestamp (timestamps come from the provider, in UTC).
        now = datetime.now(UTC)
        quotes: list[BarQuote] = []
        for index, row in frame.iterrows():
            timestamp = index.to_pydatetime()
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=UTC)
            else:
                timestamp = timestamp.astimezone(UTC)
            quotes.append(
                BarQuote(
                    symbol=symbol,
                    timestamp=timestamp,
                    open=_to_decimal(row["Open"]),
                    high=_to_decimal(row["High"]),
                    low=_to_decimal(row["Low"]),
                    close=_to_decimal(row["Close"]),
                    volume=_to_decimal(row["Volume"]),
                    is_final=is_period_closed(timestamp, timeframe, now=now),
                )
            )
        return quotes

    def fetch_recent_bars(self, symbol: str, timeframe: str, limit: int) -> list[BarQuote]:
        normalized = symbol.strip().upper()
        interval = self._interval_for(timeframe)
        period = self._period_for(interval, limit)
        frame = self._download(normalized, interval, period)
        if frame is None or frame.empty:
            logger.info("yfinance_empty_result", symbol=normalized, timeframe=timeframe)
            return []
        quotes = self._frame_to_quotes(normalized, timeframe, frame.dropna())
        return quotes[-limit:] if limit > 0 else quotes

    def fetch_latest_quote(self, symbol: str) -> BarQuote | None:
        bars = self.fetch_recent_bars(symbol, "1d", limit=1)
        return bars[-1] if bars else None
