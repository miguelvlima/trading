from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from datetime import UTC, datetime

import structlog
from sqlalchemy.orm import Session

from app.db.models import PaperEngineEvent

logger = structlog.get_logger(__name__)

# Event types (PaperEngineEvent.event_type). The cockpit colours by these.
EVENT_ENGINE_STARTED = "engine_started"
EVENT_ENGINE_STOPPED = "engine_stopped"
EVENT_PORTFOLIO_CREATED = "portfolio_created"
EVENT_PORTFOLIO_RESET = "portfolio_reset"
EVENT_SIGNAL_RECEIVED = "signal_received"
EVENT_SIGNAL_SKIPPED = "signal_skipped"
EVENT_ORDER_PROPOSED = "order_proposed"
EVENT_RISK_VETO = "risk_veto"
EVENT_ORDER_APPROVED = "order_approved"
EVENT_ORDER_REJECTED = "order_rejected"
EVENT_ORDER_CANCELLED = "order_cancelled"
EVENT_ORDER_EXPIRED = "order_expired"
EVENT_ORDER_FILLED = "order_filled"
EVENT_FILL_DEFERRED = "fill_deferred"
EVENT_STOP_LOSS_HIT = "stop_loss_hit"
EVENT_TAKE_PROFIT_HIT = "take_profit_hit"
EVENT_KILL_SWITCH_ON = "kill_switch_on"
EVENT_KILL_SWITCH_OFF = "kill_switch_off"
EVENT_COOLDOWN_STARTED = "cooldown_started"
EVENT_FEED_STALE = "feed_stale"
EVENT_FEED_RECOVERED = "feed_recovered"


def event_to_message(event: PaperEngineEvent) -> dict[str, object]:
    """Wire shape shared by the WS stream and the REST events endpoint."""
    return {
        "type": "engine_event",
        "id": event.id,
        "event_type": event.event_type,
        "severity": event.severity,
        "symbol": event.symbol,
        "message": event.message,
        "payload": event.payload,
        "created_at": event.created_at.isoformat(),
    }


class EventHub:
    """Fan-out of live engine messages to WebSocket subscribers per portfolio.

    Subscribers register an ``asyncio.Queue`` bound to their event loop; the
    engine may publish from any thread (tick callbacks arrive on the provider
    thread), so delivery hops onto each subscriber's loop with
    ``call_soon_threadsafe``. Full queues drop the message (live data: the next
    update supersedes it), mirroring the realtime WS session.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: dict[int, list[tuple[asyncio.Queue, asyncio.AbstractEventLoop]]] = {}

    def subscribe(
        self, portfolio_id: int, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop
    ) -> None:
        with self._lock:
            self._subscribers.setdefault(portfolio_id, []).append((queue, loop))

    def unsubscribe(self, portfolio_id: int, queue: asyncio.Queue) -> None:
        with self._lock:
            entries = self._subscribers.get(portfolio_id, [])
            self._subscribers[portfolio_id] = [(q, l) for (q, l) in entries if q is not queue]

    def publish(self, portfolio_id: int, message: dict[str, object]) -> None:
        with self._lock:
            entries = list(self._subscribers.get(portfolio_id, []))
        for queue, loop in entries:
            try:
                loop.call_soon_threadsafe(self._put_nowait, queue, message)
            except RuntimeError:
                # Subscriber loop already closed; it will unsubscribe on teardown.
                continue

    @staticmethod
    def _put_nowait(queue: asyncio.Queue, message: dict[str, object]) -> None:
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            logger.warning("paper_ws_queue_full_dropping")


# Process-wide hub: WS sessions subscribe here, the engine publishes here.
hub = EventHub()


def record_event(
    db: Session,
    *,
    portfolio_id: int,
    event_type: str,
    message: str,
    symbol: str | None = None,
    severity: str = "info",
    payload: dict[str, object] | None = None,
    now_fn: Callable[[], datetime] = lambda: datetime.now(UTC),
    broadcast: EventHub | None = None,
) -> PaperEngineEvent:
    """Append one ledger row and (optionally) push it to live subscribers.

    Flushes so the row has an id, but leaves the commit to the caller — events
    must land in the same transaction as the state change they describe.
    """
    event = PaperEngineEvent(
        portfolio_id=portfolio_id,
        event_type=event_type,
        severity=severity,
        symbol=symbol.upper() if symbol else None,
        message=message,
        payload=payload or {},
        created_at=now_fn(),
    )
    db.add(event)
    db.flush()
    logger.info(
        "paper_engine_event",
        portfolio_id=portfolio_id,
        event_type=event_type,
        symbol=event.symbol,
        severity=severity,
    )
    if broadcast is not None:
        broadcast.publish(portfolio_id, event_to_message(event))
    return event
