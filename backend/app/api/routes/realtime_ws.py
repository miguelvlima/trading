"""WebSocket endpoint streaming live ticks and index quotes to the Realtime tab.

The browser opens ``/realtime/ws?token=<jwt>`` (the token rides in the query
string because the WebSocket handshake cannot carry an ``Authorization``
header). After validating the JWT, the session bridges a
:class:`~app.services.data_feed.types.StreamingProvider` to the socket:

* the provider pushes ticks/indices from its own thread/loop;
* the session hops them onto the WebSocket loop via a queue and a single sender
  task (one writer — concurrent sends on one socket are unsafe);
* incoming ``{"action": "subscribe", "symbol": ...}`` messages switch the active
  symbol, and a :class:`SubscriptionManager` cancels the previous line before
  opening the new one so subscriptions never outgrow IBKR's ~100 line cap.

The session is provider-agnostic, so the suite exercises it fully offline
against ``FakeStreamingProvider`` (no Gateway).
"""

from __future__ import annotations

import asyncio
import itertools
from collections.abc import Callable
from contextlib import suppress
from decimal import Decimal

import structlog
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.dependencies import get_db_session
from app.db.models import User
from app.services.data_feed.indices import index_keys
from app.services.data_feed.streaming import (
    DEFAULT_MAX_LINES,
    LineBudgetExceeded,
    SubscriptionManager,
)
from app.services.data_feed.types import (
    IndexQuote,
    StreamingProvider,
    Tick,
)
from app.services.security import decode_access_token

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/realtime", tags=["realtime"])

# A factory yields a fresh streaming provider per WebSocket session (each owns
# its own Gateway connection / line budget). Returns None when the configured
# provider cannot stream (e.g. yfinance), so the route degrades gracefully.
StreamProviderFactory = Callable[[], StreamingProvider | None]

# Rotating client-id offset per streaming session. A fixed id collides ("326
# client id in use" -> handshake timeout) when a previous session has not fully
# released — common with rapid reconnects or React StrictMode double-mounts — so
# each new session takes a distinct id, well clear of the polling worker's.
_stream_client_seq = itertools.count()


def _build_ibkr_streaming_provider(settings: Settings) -> StreamingProvider | None:
    """Best-effort IBKR streaming provider; None if unavailable.

    Imported lazily so neither ib_insync nor a running Gateway is required for
    the REST path or the test suite (which overrides this factory).
    """
    if settings.realtime_feed_provider.strip().lower() not in {"ibkr", "ib"}:
        return None
    try:
        from app.services.data_feed.providers.ibkr_provider import IBKRStreamingProvider
    except ImportError:
        logger.error("ibkr_streaming_unavailable", hint="pip install ib_insync")
        return None
    # base+10 .. base+209, distinct from the worker (base) and per session.
    client_id = settings.ibkr_client_id + 10 + (next(_stream_client_seq) % 200)
    return IBKRStreamingProvider(
        host=settings.ibkr_gateway_host,
        port=settings.ibkr_gateway_port,
        client_id=client_id,
        market_data_type=settings.ibkr_market_data_type,
    )


def get_stream_provider_factory(
    settings: Settings = Depends(get_settings),
) -> StreamProviderFactory:
    return lambda: _build_ibkr_streaming_provider(settings)


def _authenticate(token: str | None, db: Session) -> User | None:
    if not token:
        return None
    try:
        payload = decode_access_token(token)
    except Exception:  # noqa: BLE001 - any decode failure is an auth failure
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    user = db.execute(select(User).where(User.id == int(user_id))).scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    return user


def _dec(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def tick_to_message(tick: Tick) -> dict:
    return {
        "type": "tick",
        "symbol": tick.symbol,
        "timestamp": tick.timestamp.isoformat(),
        "last": _dec(tick.last),
        "bid": _dec(tick.bid),
        "ask": _dec(tick.ask),
        "bid_size": _dec(tick.bid_size),
        "ask_size": _dec(tick.ask_size),
        "last_size": _dec(tick.last_size),
        "volume": _dec(tick.volume),
        "day_high": _dec(tick.day_high),
        "day_low": _dec(tick.day_low),
    }


def index_to_message(quote: IndexQuote) -> dict:
    return {
        "type": "index",
        "symbol": quote.symbol,
        "name": quote.name,
        "timestamp": quote.timestamp.isoformat(),
        "last": _dec(quote.last),
        "change_pct": _dec(quote.change_pct),
    }


class RealtimeStreamSession:
    """Drive one WebSocket connection: subscriptions in, ticks/indices out."""

    def __init__(
        self,
        websocket: WebSocket,
        provider: StreamingProvider,
        *,
        index_keys: list[str],
        max_lines: int = DEFAULT_MAX_LINES,
        queue_size: int = 1000,
    ) -> None:
        self._ws = websocket
        self._provider = provider
        self._index_keys = [key.upper() for key in index_keys]
        self._index_set = set(self._index_keys)
        self._subs = SubscriptionManager(max_lines=max_lines)
        self._symbol: str | None = None
        self._queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=queue_size)
        self._loop: asyncio.AbstractEventLoop | None = None

    # -- provider sinks (may be called from the provider's own thread) ---------

    def _enqueue(self, message: dict) -> None:
        loop = self._loop
        if loop is None:
            return
        loop.call_soon_threadsafe(self._put_nowait, message)

    def _put_nowait(self, message: dict) -> None:
        try:
            self._queue.put_nowait(message)
        except asyncio.QueueFull:
            # The stream is live data: if the consumer falls behind, drop this
            # update rather than block the provider. The next tick supersedes it.
            logger.warning("realtime_ws_queue_full_dropping")

    def _on_tick(self, tick: Tick) -> None:
        self._enqueue(tick_to_message(tick))

    def _on_index(self, quote: IndexQuote) -> None:
        self._enqueue(index_to_message(quote))

    # -- subscription reconciliation -------------------------------------------

    def _subscribe_key(self, key: str) -> None:
        if key in self._index_set:
            self._provider.subscribe_index(key)
        else:
            self._provider.subscribe(key)

    async def _reconcile(self) -> None:
        desired = set(self._index_keys)
        if self._symbol:
            desired.add(self._symbol)
        try:
            plan = self._subs.plan(desired)
        except LineBudgetExceeded as exc:
            await self._queue.put(
                {"type": "error", "code": "line_budget", "message": str(exc)}
            )
            return
        for key in plan.to_remove:
            with suppress(Exception):
                self._provider.unsubscribe(key)
        for key in plan.to_add:
            with suppress(Exception):
                self._subscribe_key(key)
        self._subs.apply(plan)
        await self._queue.put(
            {
                "type": "subscribed",
                "symbol": self._symbol,
                "active_lines": self._subs.count,
            }
        )

    # -- run loops -------------------------------------------------------------

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._provider.start(self._on_tick, self._on_index)
        sender = asyncio.create_task(self._send_loop())
        try:
            await self._reconcile()  # subscribe indices up front
            await self._receive_loop()
        except WebSocketDisconnect:
            pass
        finally:
            sender.cancel()
            with suppress(asyncio.CancelledError):
                await sender
            self._teardown()

    async def _send_loop(self) -> None:
        while True:
            message = await self._queue.get()
            await self._ws.send_json(message)

    async def _receive_loop(self) -> None:
        while True:
            data = await self._ws.receive_json()
            await self._handle_client_message(data)

    async def _handle_client_message(self, data: object) -> None:
        if not isinstance(data, dict):
            return
        action = data.get("action")
        if action == "subscribe":
            symbol = str(data.get("symbol") or "").strip().upper()
            if symbol and symbol != self._symbol:
                self._symbol = symbol
                await self._reconcile()
        elif action == "unsubscribe":
            if self._symbol is not None:
                self._symbol = None
                await self._reconcile()
        elif action == "ping":
            await self._queue.put({"type": "pong"})

    def _teardown(self) -> None:
        with suppress(Exception):
            self._provider.stop()
        self._subs.clear()


@router.websocket("/ws")
async def realtime_ws(
    websocket: WebSocket,
    token: str | None = Query(default=None),
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    make_provider: StreamProviderFactory = Depends(get_stream_provider_factory),
) -> None:
    user = _authenticate(token, db)
    if user is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    provider = make_provider()
    if provider is None:
        await websocket.accept()
        await websocket.send_json(
            {
                "type": "error",
                "code": "provider_unsupported",
                "message": "The configured feed provider does not support live streaming.",
            }
        )
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return

    await websocket.accept()
    logger.info("realtime_ws_connected", user_id=user.id)
    session = RealtimeStreamSession(
        websocket,
        provider,
        index_keys=index_keys(),
        max_lines=settings.realtime_max_market_data_lines,
    )
    try:
        await session.run()
    finally:
        logger.info("realtime_ws_disconnected", user_id=user.id)
