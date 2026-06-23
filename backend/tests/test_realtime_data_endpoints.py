from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies.auth import get_current_user
from app.api.routes.realtime_data import get_provider
from app.db.base import Base
from app.db.dependencies import get_db_session
from app.db.models import Instrument, MarketBar, User
from app.main import app
from fakes import FakeProvider, build_bar_quotes


def _build_session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite:///{tmp_path / 'test_realtime.db'}")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _override_db(session_factory: sessionmaker[Session]):
    def _dep():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    return _dep


def test_quote_endpoint_returns_latest(tmp_path: Path) -> None:
    session_factory = _build_session_factory(tmp_path)
    quotes = build_bar_quotes("AAPL", count=3)
    provider = FakeProvider(bars={"AAPL": quotes})

    app.dependency_overrides[get_db_session] = _override_db(session_factory)
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1, email="user@example.com", password_hash="hash"
    )
    app.dependency_overrides[get_provider] = lambda: provider

    client = TestClient(app)
    response = client.get("/realtime/quote", params={"symbol": "aapl"})

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "AAPL"
    assert Decimal(payload["close"]) == quotes[-1].close
    assert payload["is_final"] is True


def test_quote_endpoint_404_when_no_data(tmp_path: Path) -> None:
    session_factory = _build_session_factory(tmp_path)
    provider = FakeProvider(bars={})

    app.dependency_overrides[get_db_session] = _override_db(session_factory)
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1, email="user@example.com", password_hash="hash"
    )
    app.dependency_overrides[get_provider] = lambda: provider

    client = TestClient(app)
    response = client.get("/realtime/quote", params={"symbol": "TSLA"})

    app.dependency_overrides.clear()

    assert response.status_code == 404


def test_history_endpoint_returns_bars(tmp_path: Path) -> None:
    session_factory = _build_session_factory(tmp_path)
    quotes = build_bar_quotes("AAPL", count=4)
    provider = FakeProvider(bars={"AAPL": quotes})

    app.dependency_overrides[get_db_session] = _override_db(session_factory)
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1, email="user@example.com", password_hash="hash"
    )
    app.dependency_overrides[get_provider] = lambda: provider

    client = TestClient(app)
    response = client.get(
        "/realtime/history", params={"symbol": "AAPL", "timeframe": "1d", "limit": 2}
    )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 2
    assert rows[-1]["symbol"] == "AAPL"


def test_health_endpoint_reports_running(tmp_path: Path) -> None:
    session_factory = _build_session_factory(tmp_path)

    with session_factory() as session:
        instrument = Instrument(symbol="AAPL", name="Apple", currency="USD")
        session.add(instrument)
        session.flush()
        session.add(
            MarketBar(
                instrument_id=instrument.id,
                timeframe="1d",
                timestamp=datetime.now(UTC),
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100.5"),
                volume=Decimal("1000"),
            )
        )
        session.commit()

    app.dependency_overrides[get_db_session] = _override_db(session_factory)
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1, email="user@example.com", password_hash="hash"
    )

    client = TestClient(app)
    response = client.get("/realtime/health")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "yfinance"
    assert payload["status"] == "running"
    assert "AAPL" in payload["tracked_symbols"]
    assert payload["last_update"] is not None


def test_health_endpoint_reports_stale_for_old_bar(tmp_path: Path) -> None:
    session_factory = _build_session_factory(tmp_path)

    with session_factory() as session:
        instrument = Instrument(symbol="AAPL", name="Apple", currency="USD")
        session.add(instrument)
        session.flush()
        session.add(
            MarketBar(
                instrument_id=instrument.id,
                timeframe="1d",
                # Far in the past -> lag well beyond the default 180s threshold.
                timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100.5"),
                volume=Decimal("1000"),
            )
        )
        session.commit()

    app.dependency_overrides[get_db_session] = _override_db(session_factory)
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1, email="user@example.com", password_hash="hash"
    )

    client = TestClient(app)
    response = client.get("/realtime/health")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "stale"
    assert payload["lag_seconds"] is not None and payload["lag_seconds"] > 180


def test_health_endpoint_reports_empty_without_data(tmp_path: Path) -> None:
    session_factory = _build_session_factory(tmp_path)

    app.dependency_overrides[get_db_session] = _override_db(session_factory)
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1, email="user@example.com", password_hash="hash"
    )

    client = TestClient(app)
    response = client.get("/realtime/health")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "empty"


def test_quote_endpoint_requires_auth() -> None:
    # No get_current_user override -> oauth2 scheme rejects the missing token.
    client = TestClient(app)
    response = client.get("/realtime/quote", params={"symbol": "AAPL"})
    assert response.status_code == 401
