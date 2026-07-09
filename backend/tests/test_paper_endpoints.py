from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies.auth import get_current_user
from app.db.base import Base
from app.db.dependencies import get_db_session
from app.db.models import PaperOrder, PaperPortfolio, User
from app.main import app

RTH_NOW = datetime(2026, 7, 8, 15, 0, tzinfo=UTC)


def build_session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite:///{tmp_path / 'test_paper_endpoints.db'}")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def setup_client(tmp_path: Path) -> tuple[TestClient, sessionmaker[Session], int]:
    factory = build_session_factory(tmp_path)

    def override_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    with factory() as session:
        user = User(email="paper-api@example.com", password_hash="hash")
        session.add(user)
        session.commit()
        user_id = user.id

    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=user_id, is_active=True
    )
    return TestClient(app), factory, user_id


def teardown() -> None:
    app.dependency_overrides.clear()


def test_requires_auth_without_token(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)

    def override_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = override_db
    try:
        client = TestClient(app)
        response = client.get("/paper/portfolio")
        assert response.status_code == 401
    finally:
        teardown()


def test_portfolio_create_get_conflict_and_settings(tmp_path: Path) -> None:
    client, _factory, _user_id = setup_client(tmp_path)
    try:
        missing = client.get("/paper/portfolio")
        assert missing.status_code == 404

        created = client.post("/paper/portfolio", json={"initial_cash": 50_000})
        assert created.status_code == 201
        body = created.json()
        assert body["cash"] == 50_000
        assert body["risk_settings"]["max_position_pct"] == 10.0  # defaults filled in
        assert body["engine_running"] is False

        conflict = client.post("/paper/portfolio", json={"initial_cash": 25_000})
        assert conflict.status_code == 409

        # Below the tradeable minimum the API refuses outright (sizing would
        # round every proposal to 0 shares and the cockpit would look dead).
        too_small = client.post("/paper/portfolio", json={"initial_cash": 10})
        assert too_small.status_code == 422

        updated = client.put(
            "/paper/portfolio/risk-settings",
            json={"risk_settings": {"max_position_pct": 5.0, "rth_only": False}},
        )
        assert updated.status_code == 200
        assert updated.json()["risk_settings"]["max_position_pct"] == 5.0
        # Untouched keys keep their defaults.
        assert updated.json()["risk_settings"]["max_total_exposure_pct"] == 50.0
    finally:
        teardown()


def seed_proposed_order(factory: sessionmaker[Session], user_id: int) -> int:
    with factory() as session:
        portfolio = session.execute(
            select(PaperPortfolio).where(PaperPortfolio.owner_user_id == user_id)
        ).scalar_one()
        order = PaperOrder(
            portfolio_id=portfolio.id,
            symbol="AAPL",
            side="BUY",
            quantity=Decimal("10"),
            order_type="market",
            status="proposed",
            signal_snapshot={"strategy": "rsi_mean_reversion"},
            risk_snapshot={},
            data_liveness="DELAYED",
            proposed_at=RTH_NOW,
        )
        session.add(order)
        session.commit()
        return order.id


def test_order_decisions_and_listing(tmp_path: Path) -> None:
    client, factory, user_id = setup_client(tmp_path)
    try:
        client.post("/paper/portfolio", json={"initial_cash": 100_000})
        order_id = seed_proposed_order(factory, user_id)

        listed = client.get("/paper/orders", params={"status": "proposed"})
        assert listed.status_code == 200
        assert [o["id"] for o in listed.json()] == [order_id]

        # Approving with no engine runtime: order parks as approved (no quote).
        approved = client.post(f"/paper/orders/{order_id}/approve")
        assert approved.status_code == 200
        assert approved.json()["status"] == "approved"

        again = client.post(f"/paper/orders/{order_id}/reject")
        assert again.status_code == 409  # already decided

        second = seed_proposed_order(factory, user_id)
        rejected = client.post(f"/paper/orders/{second}/reject")
        assert rejected.status_code == 200
        assert rejected.json()["status"] == "rejected_user"

        missing = client.post("/paper/orders/99999/approve")
        assert missing.status_code == 404
    finally:
        teardown()


def test_positions_trades_pnl_empty_state(tmp_path: Path) -> None:
    client, _factory, _user_id = setup_client(tmp_path)
    try:
        client.post("/paper/portfolio", json={"initial_cash": 100_000})
        assert client.get("/paper/positions").json() == []
        assert client.get("/paper/trades").json() == []
        pnl = client.get("/paper/pnl").json()
        assert pnl["equity"] == 100_000
        assert pnl["day_pnl"] == 0.0
    finally:
        teardown()


def test_events_pagination(tmp_path: Path) -> None:
    client, _factory, _user_id = setup_client(tmp_path)
    try:
        client.post("/paper/portfolio", json={"initial_cash": 100_000})
        # Creation already wrote one ledger event.
        first_page = client.get("/paper/events", params={"limit": 10})
        assert first_page.status_code == 200
        events = first_page.json()
        assert len(events) == 1
        assert "Portfolio paper criado" in events[0]["message"]

        older = client.get(
            "/paper/events", params={"limit": 10, "before_id": events[0]["id"]}
        )
        assert older.json() == []
    finally:
        teardown()


def test_engine_status_and_kill_switch_reset(tmp_path: Path) -> None:
    client, factory, user_id = setup_client(tmp_path)
    try:
        client.post("/paper/portfolio", json={"initial_cash": 100_000})

        status = client.get("/paper/engine/status")
        assert status.status_code == 200
        body = status.json()
        assert body["running"] is False
        assert body["feed_status"] == "unavailable"
        assert body["feed_reason"] == "engine_stopped"

        not_active = client.post("/paper/engine/kill-switch/reset")
        assert not_active.status_code == 409

        with factory() as session:
            portfolio = session.execute(
                select(PaperPortfolio).where(PaperPortfolio.owner_user_id == user_id)
            ).scalar_one()
            portfolio.kill_switch_active = True
            portfolio.kill_switch_reason = "teste"
            session.commit()

        reset = client.post("/paper/engine/kill-switch/reset")
        assert reset.status_code == 200
        assert reset.json()["kill_switch_active"] is False
    finally:
        teardown()


def test_portfolio_reset_wipes_state_and_keeps_ledger(tmp_path: Path) -> None:
    client, factory, user_id = setup_client(tmp_path)
    try:
        client.post("/paper/portfolio", json={"initial_cash": 100_000})
        seed_proposed_order(factory, user_id)

        reset = client.post("/paper/portfolio/reset", json={"initial_cash": 50_000})
        assert reset.status_code == 200
        body = reset.json()
        assert body["initial_cash"] == 50_000
        assert body["cash"] == 50_000
        assert body["equity"] == 50_000
        assert body["engine_running"] is False
        assert body["kill_switch_active"] is False

        assert client.get("/paper/orders").json() == []
        assert client.get("/paper/positions").json() == []
        assert client.get("/paper/trades").json() == []

        # The old ledger survives, with the reset appended on top.
        events = client.get("/paper/events", params={"limit": 10}).json()
        assert "Portfolio paper reiniciado" in events[0]["message"]
        assert any("Portfolio paper criado" in event["message"] for event in events)

        too_small = client.post("/paper/portfolio/reset", json={"initial_cash": 10})
        assert too_small.status_code == 422
    finally:
        teardown()


def test_engine_stop_is_idempotent_in_the_ledger(tmp_path: Path) -> None:
    client, factory, user_id = setup_client(tmp_path)
    try:
        client.post("/paper/portfolio", json={"initial_cash": 100_000})

        with factory() as session:
            portfolio = session.execute(
                select(PaperPortfolio).where(PaperPortfolio.owner_user_id == user_id)
            ).scalar_one()
            portfolio.engine_running = True
            session.commit()

        first = client.post("/paper/engine/stop")
        assert first.status_code == 200
        assert first.json()["running"] is False

        # Repeated stops answer OK but must not append duplicate ledger rows.
        for _ in range(2):
            again = client.post("/paper/engine/stop")
            assert again.status_code == 200

        events = client.get("/paper/events", params={"limit": 50}).json()
        stopped = [e for e in events if e["event_type"] == "engine_stopped"]
        assert len(stopped) == 1
    finally:
        teardown()


def test_user_scoping_hides_other_users_data(tmp_path: Path) -> None:
    client, factory, _user_id = setup_client(tmp_path)
    try:
        client.post("/paper/portfolio", json={"initial_cash": 100_000})

        with factory() as session:
            other = User(email="other@example.com", password_hash="hash")
            session.add(other)
            session.commit()
            other_id = other.id

        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=other_id, is_active=True
        )
        assert client.get("/paper/portfolio").status_code == 404
        assert client.get("/paper/orders").status_code == 404
    finally:
        teardown()
