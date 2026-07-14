"""Backtest 5m ponta a ponta (Fase 5): POST /backtests/run com timeframe
intraday sobre barras importadas funciona offline e persiste as métricas."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.dependencies import get_db_session
from app.db.models import User
from app.main import app
from app.scripts.import_intraday_sample import BARS_PER_SESSION, import_intraday_sample
from app.services.security import hash_password

SESSIONS = 6


def build_session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite:///{tmp_path / 'test_backtest_intraday.db'}")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def setup_client(tmp_path: Path) -> tuple[TestClient, sessionmaker[Session], str]:
    factory = build_session_factory(tmp_path)

    def override_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    with factory() as session:
        session.add(
            User(
                email="intraday@example.com",
                password_hash=hash_password("StrongPass123"),
                display_name="Intraday",
                is_active=True,
            )
        )
        session.commit()
        import_intraday_sample(session, sessions=SESSIONS)

    app.dependency_overrides[get_db_session] = override_db
    client = TestClient(app)
    login = client.post(
        "/auth/login",
        json={"email": "intraday@example.com", "password": "StrongPass123"},
    )
    assert login.status_code == 200
    return client, factory, login.json()["access_token"]


def test_backtest_run_accepts_5m_timeframe_end_to_end(tmp_path: Path) -> None:
    client, _factory, token = setup_client(tmp_path)
    try:
        response = client.post(
            "/backtests/run",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "symbol": "AAPL",
                "timeframe": "5m",
                "strategies": ["opening_range_breakout", "vwap_reversion"],
                "limit": 2000,
                "initial_capital": 100_000,
                "fee_bps": 1,
                "slippage_bps": 5,
                "min_signal_strength": 0.1,
                "stop_loss_pct": 2.0,
                "take_profit_pct": 4.0,
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["timeframe"] == "5m"
        assert body["bars_processed"] == SESSIONS * BARS_PER_SESSION
        # Full metric set present — the run is a first-class BacktestRun.
        for metric in ("net_pnl_pct", "win_rate", "profit_factor", "max_drawdown_pct"):
            assert metric in body
        assert body["insight"] is not None

        # The run is listable and filterable by the intraday timeframe.
        listed = client.get(
            "/backtests",
            headers={"Authorization": f"Bearer {token}"},
            params={"symbol": "AAPL", "timeframe": "5m"},
        )
        assert listed.status_code == 200
        assert [run["id"] for run in listed.json()] == [body["id"]]
    finally:
        app.dependency_overrides.clear()
