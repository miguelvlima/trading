from __future__ import annotations

import asyncio
import math
import threading
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import structlog

from app.services.data_feed.indices import index_spec
from app.services.data_feed.pacing import PacingThrottle
from app.services.data_feed.types import (
    BarQuote,
    IndexCallback,
    IndexQuote,
    SymbolMatch,
    Tick,
    TickCallback,
    is_period_closed,
)

logger = structlog.get_logger(__name__)


def _opt_decimal(value: object) -> Decimal | None:
    """Convert an IBKR numeric field to Decimal, or None if missing/NaN.

    ib_insync reports unset price/size fields as ``nan``; those must become None
    rather than a bogus ``Decimal('nan')`` in the tick payload.
    """
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number):
        return None
    return Decimal(str(value))

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

    def fetch_history_paginated(
        self,
        symbol: str,
        timeframe: str,
        *,
        page_duration: str = "1 Y",
        max_pages: int = 30,
        end: datetime | None = None,
    ) -> list[BarQuote]:
        """Fetch a long history by paging ``reqHistoricalData`` backwards.

        Large windows (e.g. the "All time" view) exceed IBKR's ~30000-bars and
        max-duration-per-request limits, so we walk ``endDateTime`` back one page
        at a time. Crucially, **every page goes through the PacingThrottle** (and
        the per-contract minimum interval): without that, the pagination would
        burst straight past IBKR's historical pacing cap. Pages are merged
        oldest-first and de-duplicated by timestamp.
        """
        normalized = symbol.strip().upper()
        try:
            bar_size = self._bar_size_for(timeframe)
        except ValueError as exc:
            logger.error("ibkr_unsupported_timeframe", symbol=normalized, error=str(exc))
            return []
        if not self._ensure_connected():
            return []

        from ib_insync import Stock

        contract = Stock(normalized, "SMART", "USD")
        cursor = end  # None => "now"
        by_timestamp: dict[datetime, BarQuote] = {}

        for page in range(max_pages):
            self._throttle.wait()  # pacing on EVERY page, not just the first
            try:
                raw_bars = self._ib.reqHistoricalData(
                    contract,
                    endDateTime=cursor if cursor is not None else "",
                    durationStr=page_duration,
                    barSizeSetting=bar_size,
                    whatToShow="TRADES",
                    useRTH=False,
                    formatDate=2,
                    keepUpToDate=False,
                )
                self._throttle.record_success()
            except Exception as exc:  # noqa: BLE001 - never let the worker die
                self._throttle.record_failure()
                logger.error(
                    "ibkr_history_page_failed", symbol=normalized, page=page, error=str(exc)
                )
                break

            if not raw_bars:
                break
            quotes = self._bars_to_quotes(normalized, timeframe, raw_bars)
            for quote in quotes:
                by_timestamp.setdefault(quote.timestamp, quote)
            earliest = min(quote.timestamp for quote in quotes)
            if cursor is not None and earliest >= cursor:
                break  # no backward progress -> stop rather than loop forever
            cursor = earliest - timedelta(seconds=1)

        return [by_timestamp[ts] for ts in sorted(by_timestamp)]

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


class IBKRStreamingProvider:
    """Live tick / index streaming over IBKR ``reqMktData`` (paper, read-only).

    ib_insync is asyncio-based, so this provider owns a **dedicated background
    thread running its own event loop** — the Gateway connection and every
    ``reqMktData`` callback live there. The WebSocket session (on uvicorn's loop)
    drives it through :class:`StreamingProvider`; subscribe/unsubscribe calls are
    marshalled onto the IB loop with ``call_soon_threadsafe``, and inbound ticks
    are forwarded back out via the session's sinks (which hop to the WS loop).

    Resilience mirrors the polling provider: any failure is logged and swallowed
    so a bad subscription never tears the socket down. Each active subscription
    is one market-data line; the session's SubscriptionManager keeps the total
    under IBKR's cap and cancels lines on symbol switch.
    """

    name = "ibkr-stream"

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 4002,
        client_id: int = 8,
        market_data_type: int = 3,
        connect_timeout_seconds: float = 8.0,
    ) -> None:
        self._host = host
        self._port = port
        self._client_id = client_id
        self._market_data_type = market_data_type
        self._connect_timeout = connect_timeout_seconds

        self._on_tick: TickCallback | None = None
        self._on_index: IndexCallback | None = None
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ib = None
        self._tickers: dict[str, object] = {}  # key -> ib_insync Ticker
        self._index_keys: set[str] = set()
        # Subscriptions requested before the IB loop exists are buffered here and
        # applied once it connects (guarded because they cross threads).
        self._pending: list[tuple[str, bool]] = []
        self._lock = threading.Lock()

    # -- lifecycle (called from the WebSocket loop thread) ---------------------

    def start(self, on_tick: TickCallback, on_index: IndexCallback) -> None:
        if self._thread is not None:
            return
        self._on_tick = on_tick
        self._on_index = on_index
        # Non-blocking: spawn the IB thread and return immediately. We must NEVER
        # wait on the Gateway connect here — doing so blocks the WebSocket's event
        # loop (uvicorn), which froze every other connection and timed out their
        # handshakes. The connect happens on the thread; subscriptions queue.
        self._thread = threading.Thread(target=self._run_loop, name="ibkr-stream", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        loop = self._loop
        if loop is None:
            # Never connected (e.g. Gateway down): just unblock the thread.
            return
        loop.call_soon_threadsafe(self._shutdown)
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def subscribe(self, symbol: str) -> None:
        self._queue_subscribe(symbol.upper(), False)

    def subscribe_index(self, symbol: str) -> None:
        key = symbol.upper()
        self._index_keys.add(key)
        self._queue_subscribe(key, True)

    def unsubscribe(self, symbol: str) -> None:
        key = symbol.upper()
        loop = self._loop
        if loop is not None:
            loop.call_soon_threadsafe(self._do_unsubscribe, key)
        else:
            with self._lock:
                self._pending = [(k, ix) for (k, ix) in self._pending if k != key]

    def _queue_subscribe(self, key: str, is_index: bool) -> None:
        loop = self._loop
        if loop is not None:
            loop.call_soon_threadsafe(self._do_subscribe, key, is_index)
        else:
            with self._lock:
                self._pending.append((key, is_index))

    # -- IB loop thread --------------------------------------------------------

    def _run_loop(self) -> None:
        try:
            from ib_insync import IB
        except ImportError:
            logger.error("ibkr_library_missing", hint="pip install ib_insync")
            return

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._ib = IB()
        try:
            loop.run_until_complete(self._connect())
        except Exception as exc:  # noqa: BLE001 - connection errors are opaque
            logger.error("ibkr_stream_connect_failed", error=str(exc))
        else:
            # Publish the loop only after a successful connect, then apply any
            # subscriptions queued while connecting.
            self._loop = loop
            self._drain_pending()
        if self._loop is None:
            # Connect failed: nothing will stream; close the loop and exit.
            loop.close()
            return
        loop.run_forever()
        # run_forever returns once _shutdown stops the loop.
        loop.close()

    def _drain_pending(self) -> None:
        with self._lock:
            pending = list(self._pending)
            self._pending.clear()
        for key, is_index in pending:
            self._do_subscribe(key, is_index)

    async def _connect(self) -> None:
        await self._ib.connectAsync(
            self._host,
            self._port,
            clientId=self._client_id,
            timeout=self._connect_timeout,
            readonly=True,
        )
        # Delayed (3) lets paper accounts without live-data entitlements still
        # receive ticks instead of nothing.
        self._ib.reqMarketDataType(self._market_data_type)
        self._ib.pendingTickersEvent += self._on_pending_tickers
        logger.info(
            "ibkr_stream_connected",
            host=self._host,
            port=self._port,
            client_id=self._client_id,
            market_data_type=self._market_data_type,
        )

    def _build_contract(self, key: str, is_index: bool):
        from ib_insync import Forex, Index, Stock

        if not is_index:
            return Stock(key, "SMART", "USD")
        spec = index_spec(key)
        if spec is None:
            return Stock(key, "SMART", "USD")
        if spec.sec_type == "CASH":
            return Forex(spec.symbol)  # e.g. EURUSD
        return Index(spec.symbol, spec.exchange, spec.currency)

    def _do_subscribe(self, key: str, is_index: bool) -> None:
        if key in self._tickers:
            return
        try:
            contract = self._build_contract(key, is_index)
            ticker = self._ib.reqMktData(contract, "", False, False)
            self._tickers[key] = ticker
            if is_index:
                self._index_keys.add(key)
            logger.info("ibkr_stream_subscribed", key=key, is_index=is_index)
        except Exception as exc:  # noqa: BLE001
            logger.error("ibkr_stream_subscribe_failed", key=key, error=str(exc))

    def _do_unsubscribe(self, key: str) -> None:
        ticker = self._tickers.pop(key, None)
        if ticker is None:
            return
        try:
            self._ib.cancelMktData(ticker.contract)
            logger.info("ibkr_stream_unsubscribed", key=key)
        except Exception as exc:  # noqa: BLE001
            logger.error("ibkr_stream_unsubscribe_failed", key=key, error=str(exc))

    def _shutdown(self) -> None:
        for key in list(self._tickers):
            self._do_unsubscribe(key)
        try:
            if self._ib is not None and self._ib.isConnected():
                self._ib.disconnect()
        except Exception as exc:  # noqa: BLE001
            logger.warning("ibkr_stream_disconnect_error", error=str(exc))
        if self._loop is not None:
            self._loop.stop()

    # -- inbound ticks (IB loop thread) ----------------------------------------

    def _on_pending_tickers(self, tickers) -> None:
        for ticker in tickers:
            contract = getattr(ticker, "contract", None)
            if contract is None:
                continue
            key = (contract.symbol or "").upper()
            timestamp = self._ticker_time(ticker)
            if key in self._index_keys:
                self._emit_index(key, ticker, timestamp)
            else:
                self._emit_tick(key, ticker, timestamp)

    @staticmethod
    def _ticker_time(ticker) -> datetime:
        value = getattr(ticker, "time", None)
        if isinstance(value, datetime):
            return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
        return datetime.now(UTC)

    def _emit_tick(self, key: str, ticker, timestamp: datetime) -> None:
        if self._on_tick is None:
            return
        self._on_tick(
            Tick(
                symbol=key,
                timestamp=timestamp,
                last=_opt_decimal(getattr(ticker, "last", None)),
                bid=_opt_decimal(getattr(ticker, "bid", None)),
                ask=_opt_decimal(getattr(ticker, "ask", None)),
                bid_size=_opt_decimal(getattr(ticker, "bidSize", None)),
                ask_size=_opt_decimal(getattr(ticker, "askSize", None)),
                last_size=_opt_decimal(getattr(ticker, "lastSize", None)),
                volume=_opt_decimal(getattr(ticker, "volume", None)),
                day_high=_opt_decimal(getattr(ticker, "high", None)),
                day_low=_opt_decimal(getattr(ticker, "low", None)),
            )
        )

    def _emit_index(self, key: str, ticker, timestamp: datetime) -> None:
        if self._on_index is None:
            return
        last = _opt_decimal(getattr(ticker, "last", None)) or _opt_decimal(
            getattr(ticker, "close", None)
        )
        prev_close = _opt_decimal(getattr(ticker, "close", None))
        change_pct: Decimal | None = None
        if last is not None and prev_close not in (None, Decimal("0")):
            change_pct = (last - prev_close) / prev_close * Decimal("100")
        spec = index_spec(key)
        self._on_index(
            IndexQuote(
                symbol=key,
                name=spec.name if spec else key,
                timestamp=timestamp,
                last=last,
                change_pct=change_pct,
            )
        )
