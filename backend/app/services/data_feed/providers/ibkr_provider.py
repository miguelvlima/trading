from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import structlog

from app.services.data_feed.pacing import PacingThrottle
from app.services.data_feed.types import BarQuote, SymbolMatch, is_period_closed

logger = structlog.get_logger(__name__)

# We use ``ib_insync`` rather than the raw ``ibapi``: it wraps the asynchronous
# socket API in a synchronous, event-loop-managed client, which keeps this
# polling provider simple and lets us reconnect deterministically. ``ib_insync``
# is imported lazily so the package (and a running IB Gateway) is only required
# when this provider is actually selected — the test suite never instantiates it.

# Our short timeframe -> IB ``barSizeSetting``.
_TIMEFRAME_TO_BAR_SIZE: dict[str, str] = {
    "1m": "1 min",
    "2m": "2 mins",
    "5m": "5 mins",
    "15m": "15 mins",
    "30m": "30 mins",
    "60m": "1 hour",
    "1h": "1 hour",
    "2h": "2 hours",
    "4h": "4 hours",
    "1d": "1 day",
    "1wk": "1 week",
    "1mo": "1 month",
}

_INTRADAY_TIMEFRAMES = {"1m", "2m", "5m", "15m", "30m", "60m", "1h", "2h", "4h"}

# Lookback window per intraday timeframe. Finer bars have shorter IB history
# limits, so we request a window sized to the bar (and bounded by IB's caps).
_INTRADAY_DURATION: dict[str, str] = {
    "1m": "2 D",
    "2m": "3 D",
    "5m": "10 D",
    "15m": "20 D",
    "30m": "1 M",
    "60m": "2 M",
    "1h": "2 M",
    "2h": "3 M",
    "4h": "6 M",
}


def _to_decimal(value: object) -> Decimal:
    return Decimal(str(value))


class IBKRProvider:
    """IBKR market data via the IB Gateway / TWS socket API (paper, read-only).

    Resilience is mandatory here: the Gateway is known to drop and silently
    auto-reconnect (``DISCONNECT_ON_INACTIVITY`` / ``Connection reset`` /
    ``HOT_RESTART`` in the operator log). Every call lazily (re)connects with a
    timeout and bounded backoff; on any failure it logs a structured error and
    returns ``[]`` / ``None`` instead of raising, so the worker never dies.
    """

    name = "ibkr"

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 4002,
        client_id: int = 7,
        connect_timeout_seconds: float = 8.0,
        min_request_interval_seconds: float = 1.0,
    ) -> None:
        self._host = host
        self._port = port
        self._client_id = client_id
        self._connect_timeout = connect_timeout_seconds
        self._throttle = PacingThrottle(min_request_interval_seconds)
        self._ib = None  # lazily created ib_insync.IB instance

    # -- connection management -------------------------------------------------

    def _ensure_connected(self) -> bool:
        try:
            from ib_insync import IB
        except ImportError:
            logger.error(
                "ibkr_library_missing",
                hint="pip install ib_insync to use REALTIME_FEED_PROVIDER=ibkr",
            )
            return False

        if self._ib is None:
            self._ib = IB()

        if self._ib.isConnected():
            return True

        try:
            self._ib.connect(
                self._host,
                self._port,
                clientId=self._client_id,
                timeout=self._connect_timeout,
                readonly=True,
            )
            self._throttle.record_success()
            logger.info(
                "ibkr_connected", host=self._host, port=self._port, client_id=self._client_id
            )
            return True
        except Exception as exc:  # noqa: BLE001 - connection errors are opaque
            backoff = self._throttle.record_failure()
            logger.error(
                "ibkr_connect_failed",
                host=self._host,
                port=self._port,
                error=str(exc),
                backoff_seconds=backoff,
            )
            return False

    def disconnect(self) -> None:
        if self._ib is not None and self._ib.isConnected():
            try:
                self._ib.disconnect()
            except Exception as exc:  # noqa: BLE001
                logger.warning("ibkr_disconnect_error", error=str(exc))

    # -- helpers ---------------------------------------------------------------

    def _bar_size_for(self, timeframe: str) -> str:
        bar_size = _TIMEFRAME_TO_BAR_SIZE.get(timeframe.strip().lower())
        if bar_size is None:
            raise ValueError(f"Unsupported timeframe for IBKR: {timeframe!r}")
        return bar_size

    def _duration_for(self, timeframe: str, limit: int) -> str:
        key = timeframe.strip().lower()
        if key in _INTRADAY_DURATION:
            return _INTRADAY_DURATION[key]
        if key in {"1wk", "1mo"}:
            return f"{max(limit * 7, 30)} D"
        return f"{max(limit, 1)} D"

    @staticmethod
    def _coerce_utc(value: object) -> datetime:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=UTC)
            return value.astimezone(UTC)
        if isinstance(value, date):
            return datetime(value.year, value.month, value.day, tzinfo=UTC)
        # ib_insync may hand back an ISO string for some bar types.
        parsed = datetime.fromisoformat(str(value))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)

    def _bars_to_quotes(self, symbol: str, timeframe: str, raw_bars) -> list[BarQuote]:
        now = datetime.now(UTC)
        quotes: list[BarQuote] = []
        for bar in raw_bars:
            timestamp = self._coerce_utc(bar.date)
            quotes.append(
                BarQuote(
                    symbol=symbol,
                    timestamp=timestamp,
                    open=_to_decimal(bar.open),
                    high=_to_decimal(bar.high),
                    low=_to_decimal(bar.low),
                    close=_to_decimal(bar.close),
                    volume=_to_decimal(max(bar.volume, 0)),
                    is_final=is_period_closed(timestamp, timeframe, now=now),
                )
            )
        return quotes

    # -- MarketDataProvider ----------------------------------------------------

    def fetch_recent_bars(self, symbol: str, timeframe: str, limit: int) -> list[BarQuote]:
        normalized = symbol.strip().upper()
        try:
            bar_size = self._bar_size_for(timeframe)
        except ValueError as exc:
            logger.error("ibkr_unsupported_timeframe", symbol=normalized, error=str(exc))
            return []

        if not self._ensure_connected():
            return []

        self._throttle.wait()
        try:
            from ib_insync import Stock

            contract = Stock(normalized, "SMART", "USD")
            raw_bars = self._ib.reqHistoricalData(
                contract,
                endDateTime="",
                durationStr=self._duration_for(timeframe, limit),
                barSizeSetting=bar_size,
                whatToShow="TRADES",
                useRTH=False,
                formatDate=2,  # UTC, timezone-aware
                keepUpToDate=False,
            )
            self._throttle.record_success()
        except Exception as exc:  # noqa: BLE001 - never let the worker die
            self._throttle.record_failure()
            logger.error("ibkr_history_failed", symbol=normalized, error=str(exc))
            return []

        if not raw_bars:
            logger.info("ibkr_empty_result", symbol=normalized, timeframe=timeframe)
            return []

        quotes = self._bars_to_quotes(normalized, timeframe, raw_bars)
        return quotes[-limit:] if limit > 0 else quotes

    def fetch_latest_quote(self, symbol: str) -> BarQuote | None:
        bars = self.fetch_recent_bars(symbol, "1d", limit=1)
        return bars[-1] if bars else None

    def search_symbols(self, query: str, limit: int = 25) -> list[SymbolMatch]:
        """Look up matching contracts via IBKR (the full IBKR universe)."""
        cleaned = query.strip()
        if not cleaned:
            return []
        if not self._ensure_connected():
            return []

        self._throttle.wait()
        try:
            results = self._ib.reqMatchingSymbols(cleaned)
            self._throttle.record_success()
        except Exception as exc:  # noqa: BLE001 - never raise to the caller
            self._throttle.record_failure()
            logger.error("ibkr_search_failed", query=cleaned, error=str(exc))
            return []

        matches: list[SymbolMatch] = []
        for description in results or []:
            contract = getattr(description, "contract", None)
            if contract is None:
                continue
            matches.append(
                SymbolMatch(
                    symbol=contract.symbol,
                    name=getattr(contract, "description", None) or None,
                    sec_type=contract.secType or None,
                    exchange=(contract.primaryExchange or contract.exchange or None),
                    currency=contract.currency or None,
                )
            )
        return matches[:limit]
