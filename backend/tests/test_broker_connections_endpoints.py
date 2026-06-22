from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.dependencies import get_db_session
from app.db.models import User
from app.main import app
from app.services.security import hash_password


def _build_test_session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite:///{tmp_path / 'test_broker_connections.db'}")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_broker_connections_crud_and_user_scope(tmp_path: Path) -> None:
    test_session_factory = _build_test_session_factory(tmp_path)

    def override_get_db_session():
        session = test_session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
    client = TestClient(app)

    with test_session_factory() as session:
        session.add(
            User(
                email="owner@example.com",
                password_hash=hash_password("StrongPass123"),
                display_name="Owner",
                is_active=True,
            )
        )
        session.add(
            User(
                email="other@example.com",
                password_hash=hash_password("StrongPass123"),
                display_name="Other",
                is_active=True,
            )
        )
        session.commit()

    login_owner = client.post("/auth/login", json={"email": "owner@example.com", "password": "StrongPass123"})
    login_other = client.post("/auth/login", json={"email": "other@example.com", "password": "StrongPass123"})
    assert login_owner.status_code == 200
    assert login_other.status_code == 200
    owner_token = login_owner.json()["access_token"]
    other_token = login_other.json()["access_token"]

    create_response = client.post(
        "/broker-connections",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={
            "broker_name": "Binance",
            "account_label": "Principal",
            "environment": "paper",
            "connection_metadata": {"region": "EU", "leverage": 2},
            "is_active": True,
        },
    )
    assert create_response.status_code == 201
    created = create_response.json()
    connection_id = created["id"]
    assert created["broker_name"] == "Binance"
    assert created["owner_user_id"] > 0

    list_owner = client.get("/broker-connections", headers={"Authorization": f"Bearer {owner_token}"})
    list_other = client.get("/broker-connections", headers={"Authorization": f"Bearer {other_token}"})
    assert list_owner.status_code == 200
    assert list_other.status_code == 200
    assert len(list_owner.json()) == 1
    assert len(list_other.json()) == 0

    update_other = client.put(
        f"/broker-connections/{connection_id}",
        headers={"Authorization": f"Bearer {other_token}"},
        json={"environment": "live"},
    )
    assert update_other.status_code == 404

    update_owner = client.put(
        f"/broker-connections/{connection_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"environment": "live", "is_active": False},
    )
    assert update_owner.status_code == 200
    assert update_owner.json()["environment"] == "live"
    assert update_owner.json()["is_active"] is False

    delete_other = client.delete(
        f"/broker-connections/{connection_id}",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert delete_other.status_code == 404

    delete_owner = client.delete(
        f"/broker-connections/{connection_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert delete_owner.status_code == 204

    list_after_delete = client.get("/broker-connections", headers={"Authorization": f"Bearer {owner_token}"})
    assert list_after_delete.status_code == 200
    assert list_after_delete.json() == []

    app.dependency_overrides.clear()
