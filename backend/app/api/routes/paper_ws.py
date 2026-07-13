"""WebSocket streaming paper-engine events and state to the cockpit.

Mirrors ``realtime_ws.py``: the browser opens ``/paper/ws?token=<jwt>`` (token
in the query string — the WS handshake carries no Authorization header), the
session subscribes an asyncio queue on the process-wide :data:`EventHub`, and a
single sender task forwards messages. The engine publishes from its own
threads; the hub hops messages onto this loop with ``call_soon_threadsafe``.

Message types (server -> client): ``engine_event`` (one ledger row, same shape
as GET /paper/events), ``engine_state`` (status + PnL + positions, periodic),
``pong``.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress

import structlog
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.dependencies import get_db_session
from app.db.models import PaperPortfolio, User
from app.services.paper_trading.events import EventHub, hub as global_hub
from app.services.security import decode_access_token

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/paper", tags=["paper-trading"])


def get_event_hub() -> EventHub:
    return global_hub


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


@router.websocket("/ws")
async def paper_ws(
    websocket: WebSocket,
    token: str | None = Query(default=None),
    db: Session = Depends(get_db_session),
    event_hub: EventHub = Depends(get_event_hub),
) -> None:
    user = _authenticate(token, db)
    if user is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    portfolio = db.execute(
        select(PaperPortfolio).where(PaperPortfolio.owner_user_id == user.id)
    ).scalar_one_or_none()
    if portfolio is None:
        await websocket.accept()
        await websocket.send_json(
            {
                "type": "error",
                "code": "no_portfolio",
                "message": "Cria primeiro um portfolio paper (POST /paper/portfolio).",
            }
        )
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    logger.info("paper_ws_connected", user_id=user.id, portfolio_id=portfolio.id)

    queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=1000)
    loop = asyncio.get_running_loop()
    event_hub.subscribe(portfolio.id, queue, loop)

    async def send_loop() -> None:
        while True:
            message = await queue.get()
            await websocket.send_json(message)

    sender = asyncio.create_task(send_loop())
    try:
        while True:
            data = await websocket.receive_json()
            if isinstance(data, dict) and data.get("action") == "ping":
                await queue.put({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        sender.cancel()
        with suppress(asyncio.CancelledError):
            await sender
        event_hub.unsubscribe(portfolio.id, queue)
        logger.info("paper_ws_disconnected", user_id=user.id, portfolio_id=portfolio.id)
