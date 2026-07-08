from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from starlette.websockets import WebSocketDisconnect

from app.db.base import Base
from app.db.dependencies import get_db_session
from app.db.models import PaperPortfolio, User
from app.main import app
from app.services.paper_trading import events as ev
from app.services.paper_trading.events import hub
from app.services.security import create_access_token


def build_session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite:///{tmp_path / 'test_paper_ws.db'}")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def override_db(factory: sessionmaker[Session]):
    def _dep():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    return _dep


def seed_user_and_portfolio(factory: sessionmaker[Session]) -> tuple[int, int]:
    with factory() as session:
        user = User(email="ws@example.com", password_hash="hash", is_active=True)
        session.add(user)
        session.flush()
        portfolio = PaperPortfolio(
            owner_user_id=user.id,
            initial_cash=Decimal("100000"),
            cash=Decimal("100000"),
            equity=Decimal("100000"),
            risk_settings={},
        )
        session.add(portfolio)
        session.commit()
        return user.id, portfolio.id


def _receive_until(ws, predicate, *, limit: int = 30) -> dict:
    for _ in range(limit):
        message = ws.receive_json()
        if predicate(message):
            return message
    raise AssertionError("expected message not received within limit")


def test_ws_rejects_without_valid_token(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    app.dependency_overrides[get_db_session] = override_db(factory)
    try:
        client = TestClient(app)
        for url in ("/paper/ws", "/paper/ws?token=invalid"):
            try:
                with client.websocket_connect(url) as ws:
                    ws.receive_json()
                raise AssertionError("handshake should have been rejected")
            except WebSocketDisconnect as exc:
                assert exc.code == 1008
    finally:
        app.dependency_overrides.clear()


def test_ws_requires_portfolio(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    app.dependency_overrides[get_db_session] = override_db(factory)
    try:
        with factory() as session:
            user = User(email="nopf@example.com", password_hash="hash", is_active=True)
            session.add(user)
            session.commit()
            token = create_access_token(user.id)
        client = TestClient(app)
        with client.websocket_connect(f"/paper/ws?token={token}") as ws:
            message = ws.receive_json()
            assert message["type"] == "error"
            assert message["code"] == "no_portfolio"
    finally:
        app.dependency_overrides.clear()


def test_ws_streams_engine_events_and_pong(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    app.dependency_overrides[get_db_session] = override_db(factory)
    try:
        user_id, portfolio_id = seed_user_and_portfolio(factory)
        token = create_access_token(user_id)
        client = TestClient(app)

        with client.websocket_connect(f"/paper/ws?token={token}") as ws:
            ws.send_json({"action": "ping"})
            pong = _receive_until(ws, lambda m: m.get("type") == "pong")
            assert pong == {"type": "pong"}

            # An engine event recorded with broadcast reaches the socket.
            with factory() as session:
                ev.record_event(
                    session,
                    portfolio_id=portfolio_id,
                    event_type=ev.EVENT_ORDER_PROPOSED,
                    message="Ordem proposta: BUY 10 AAPL @ mercado.",
                    symbol="AAPL",
                    broadcast=hub,
                )
                session.commit()

            message = _receive_until(ws, lambda m: m.get("type") == "engine_event")
            assert message["event_type"] == "order_proposed"
            assert message["symbol"] == "AAPL"
            assert "Ordem proposta" in message["message"]
    finally:
        app.dependency_overrides.clear()
