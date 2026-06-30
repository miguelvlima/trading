from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from starlette.websockets import WebSocketDisconnect

from app.api.routes.realtime_ws import get_stream_provider_factory
from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.dependencies import get_db_session
from app.db.models import User
from app.main import app
from app.services.security import create_access_token
from fakes import FakeStreamingProvider


def _build_session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite:///{tmp_path / 'test_ws.db'}")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _override_db(session_factory: sessionmaker[Session]) -> Callable[[], object]:
    def _dep():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    return _dep


def _seed_user(session_factory: sessionmaker[Session], user_id: int = 1) -> None:
    with session_factory() as session:
        session.add(
            User(
                id=user_id,
                email="user@example.com",
                password_hash="hash",
                is_active=True,
            )
        )
        session.commit()


def _receive_until(ws, predicate, *, limit: int = 30) -> dict:
    """Drain messages until one matches ``predicate`` (guards against hangs)."""
    for _ in range(limit):
        message = ws.receive_json()
        if predicate(message):
            return message
    raise AssertionError("expected message not received within limit")


def test_ws_rejects_invalid_token(tmp_path: Path) -> None:
    session_factory = _build_session_factory(tmp_path)
    app.dependency_overrides[get_db_session] = _override_db(session_factory)
    app.dependency_overrides[get_stream_provider_factory] = lambda: (
        lambda: FakeStreamingProvider()
    )

    client = TestClient(app)
    try:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/realtime/ws?token=not-a-jwt") as ws:
                ws.receive_json()
    finally:
        app.dependency_overrides.clear()


def test_ws_rejects_missing_token(tmp_path: Path) -> None:
    session_factory = _build_session_factory(tmp_path)
    app.dependency_overrides[get_db_session] = _override_db(session_factory)
    app.dependency_overrides[get_stream_provider_factory] = lambda: (
        lambda: FakeStreamingProvider()
    )

    client = TestClient(app)
    try:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/realtime/ws") as ws:
                ws.receive_json()
    finally:
        app.dependency_overrides.clear()


def test_ws_streams_indices_on_connect(tmp_path: Path) -> None:
    from app.services.data_feed.indices import index_keys

    session_factory = _build_session_factory(tmp_path)
    _seed_user(session_factory)
    fake = FakeStreamingProvider()

    app.dependency_overrides[get_db_session] = _override_db(session_factory)
    app.dependency_overrides[get_stream_provider_factory] = lambda: (lambda: fake)

    token = create_access_token(1)
    client = TestClient(app)
    try:
        with client.websocket_connect(f"/realtime/ws?token={token}") as ws:
            # On connect the server emits one quote per index plus a "subscribed"
            # ack for the initial (symbol-less) state — collect them order-agnostic.
            messages = [ws.receive_json() for _ in range(len(index_keys()) + 1)]
    finally:
        app.dependency_overrides.clear()

    by_type = {m["type"] for m in messages}
    assert "index" in by_type
    assert "subscribed" in by_type

    index_msgs = [m for m in messages if m["type"] == "index"]
    assert any(m["last"] == "100.00" for m in index_msgs)
    # The bottom strip is wired up before any symbol is chosen.
    ack = next(m for m in messages if m["type"] == "subscribed")
    assert ack["symbol"] is None
    assert ack["active_lines"] >= 1

    assert fake.started is True
    # stop() clears the live set on teardown, so assert on the durable call log.
    assert "SPX" in fake.subscribe_calls
    assert fake.stopped is True


def test_ws_subscribe_emits_tick(tmp_path: Path) -> None:
    session_factory = _build_session_factory(tmp_path)
    _seed_user(session_factory)
    fake = FakeStreamingProvider()

    app.dependency_overrides[get_db_session] = _override_db(session_factory)
    app.dependency_overrides[get_stream_provider_factory] = lambda: (lambda: fake)

    token = create_access_token(1)
    client = TestClient(app)
    try:
        with client.websocket_connect(f"/realtime/ws?token={token}") as ws:
            ws.send_json({"action": "subscribe", "symbol": "aapl"})
            tick = _receive_until(
                ws, lambda m: m["type"] == "tick" and m["symbol"] == "AAPL"
            )
            assert tick["last"] == "300.42"
            assert tick["bid"] == "300.40"
            assert tick["ask"] == "300.44"
            assert tick["volume"] == "1240000"
    finally:
        app.dependency_overrides.clear()

    assert "AAPL" in fake.subscribe_calls


def test_ws_switch_symbol_cancels_previous_line(tmp_path: Path) -> None:
    session_factory = _build_session_factory(tmp_path)
    _seed_user(session_factory)
    fake = FakeStreamingProvider()

    app.dependency_overrides[get_db_session] = _override_db(session_factory)
    app.dependency_overrides[get_stream_provider_factory] = lambda: (lambda: fake)

    token = create_access_token(1)
    client = TestClient(app)
    try:
        with client.websocket_connect(f"/realtime/ws?token={token}") as ws:
            ws.send_json({"action": "subscribe", "symbol": "AAPL"})
            _receive_until(ws, lambda m: m["type"] == "tick" and m["symbol"] == "AAPL")
            ws.send_json({"action": "subscribe", "symbol": "MSFT"})
            _receive_until(ws, lambda m: m["type"] == "tick" and m["symbol"] == "MSFT")
    finally:
        app.dependency_overrides.clear()

    # Switching symbol must cancel the old line (no orphan accumulation) but keep
    # the index lines untouched.
    assert "AAPL" in fake.unsubscribe_calls
    assert "SPX" not in fake.unsubscribe_calls


def test_ws_line_budget_exceeded_degrades_gracefully(tmp_path: Path) -> None:
    session_factory = _build_session_factory(tmp_path)
    _seed_user(session_factory)
    fake = FakeStreamingProvider()

    # Cap at exactly the number of indices so adding a symbol overflows.
    from app.services.data_feed.indices import index_keys

    tight = Settings(realtime_max_market_data_lines=len(index_keys()))
    app.dependency_overrides[get_db_session] = _override_db(session_factory)
    app.dependency_overrides[get_settings] = lambda: tight
    app.dependency_overrides[get_stream_provider_factory] = lambda: (lambda: fake)

    token = create_access_token(1)
    client = TestClient(app)
    try:
        with client.websocket_connect(f"/realtime/ws?token={token}") as ws:
            ws.send_json({"action": "subscribe", "symbol": "AAPL"})
            err = _receive_until(ws, lambda m: m["type"] == "error")
            assert err["code"] == "line_budget"
    finally:
        app.dependency_overrides.clear()
