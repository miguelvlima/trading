from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import User
from app.db.base import Base
from app.db.dependencies import get_db_session
from app.main import app
from app.services.security import hash_password


def _build_test_session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite:///{tmp_path / 'test_auth_and_combinations.db'}")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_auth_login_and_clone_combination(tmp_path: Path) -> None:
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
                email="a@example.com",
                password_hash=hash_password("StrongPass123"),
                display_name="User A",
                is_active=True,
            )
        )
        session.add(
            User(
                email="b@example.com",
                password_hash=hash_password("StrongPass123"),
                display_name="User B",
                is_active=True,
            )
        )
        session.commit()

    login_a = client.post("/auth/login", json={"email": "a@example.com", "password": "StrongPass123"})
    login_b = client.post("/auth/login", json={"email": "b@example.com", "password": "StrongPass123"})
    assert login_a.status_code == 200
    assert login_b.status_code == 200
    token_a = login_a.json()["access_token"]
    token_b = login_b.json()["access_token"]

    create_combination = client.post(
        "/strategy-combinations",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "name": "Momentum Blend",
            "description": "Setup de momentum",
            "strategies": ["macd_crossover", "sma_ema_crossover"],
            "is_shared": True,
        },
    )
    assert create_combination.status_code == 201
    combination_id = create_combination.json()["id"]

    list_b = client.get("/strategy-combinations", headers={"Authorization": f"Bearer {token_b}"})
    assert list_b.status_code == 200
    assert any(item["id"] == combination_id for item in list_b.json())

    clone_b = client.post(
        f"/strategy-combinations/{combination_id}/clone",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert clone_b.status_code == 201
    assert clone_b.json()["owner_email"] == "b@example.com"
    assert clone_b.json()["is_shared"] is False
    assert clone_b.json()["cloned_from_id"] == combination_id

    app.dependency_overrides.clear()
