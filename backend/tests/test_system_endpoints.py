from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_mode_endpoint() -> None:
    response = client.get("/mode")
    assert response.status_code == 200
    assert response.json() == {"mode": "PAPER"}


def test_version_endpoint() -> None:
    response = client.get("/version")
    assert response.status_code == 200
    assert response.json() == {"version": "0.1.0"}
