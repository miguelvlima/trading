from datetime import UTC, datetime, timedelta
from pathlib import Path
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.dependencies import get_db_session
from app.db.models import Instrument, MarketBar, User
from app.main import app
from app.services.security import hash_password


def _build_test_session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite:///{tmp_path / 'test_backtests.db'}")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_backtest_run_creation_and_user_scope(tmp_path: Path) -> None:
    test_session_factory = _build_test_session_factory(tmp_path)

    def override_get_db_session():
        session = test_session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
    client = TestClient(app)

    start = datetime(2024, 1, 1, tzinfo=UTC)
    with test_session_factory() as session:
        session.add(
            User(
                email="owner_backtest@example.com",
                password_hash=hash_password("StrongPass123"),
                display_name="Owner Backtest",
                is_active=True,
            )
        )
        session.add(
            User(
                email="other_backtest@example.com",
                password_hash=hash_password("StrongPass123"),
                display_name="Other Backtest",
                is_active=True,
            )
        )
        instrument = Instrument(symbol="AAPL", name="Apple", exchange="NASDAQ", currency="USD")
        session.add(instrument)
        session.flush()

        bars: list[MarketBar] = []
        for idx in range(60):
            if idx < 25:
                close = Decimal("100")
            elif idx == 25:
                close = Decimal("135")
            elif idx == 26:
                close = Decimal("85")
            else:
                close = Decimal("102")
            ts = start + timedelta(days=idx)
            bars.append(
                MarketBar(
                    instrument_id=instrument.id,
                    timeframe="1d",
                    timestamp=ts,
                    open=close,
                    high=close,
                    low=close,
                    close=close,
                    volume=Decimal("1000"),
                )
            )
        session.add_all(bars)
        session.commit()

    login_owner = client.post(
        "/auth/login",
        json={"email": "owner_backtest@example.com", "password": "StrongPass123"},
    )
    login_other = client.post(
        "/auth/login",
        json={"email": "other_backtest@example.com", "password": "StrongPass123"},
    )
    assert login_owner.status_code == 200
    assert login_other.status_code == 200
    owner_token = login_owner.json()["access_token"]
    other_token = login_other.json()["access_token"]

    create_run = client.post(
        "/backtests/run",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={
            "symbol": "AAPL",
            "timeframe": "1d",
            "strategies": ["bollinger_breakout"],
            "limit": 2000,
            "initial_capital": 10000,
            "fee_bps": 5,
            "slippage_bps": 2,
            "min_signal_strength": 0.1,
        },
    )
    assert create_run.status_code == 201
    created = create_run.json()
    run_id = created["id"]
    assert created["symbol"] == "AAPL"
    assert created["bars_processed"] == 60
    assert created["trades_count"] >= 1
    assert created["owner_user_id"] > 0

    owner_list = client.get("/backtests", headers={"Authorization": f"Bearer {owner_token}"})
    assert owner_list.status_code == 200
    assert len(owner_list.json()) == 1
    assert owner_list.json()[0]["id"] == run_id
    assert isinstance(owner_list.json()[0].get("insight_summary"), str)
    assert len(owner_list.json()[0]["insight_summary"]) > 0

    other_list = client.get("/backtests", headers={"Authorization": f"Bearer {other_token}"})
    assert other_list.status_code == 200
    assert other_list.json() == []

    owner_detail = client.get(f"/backtests/{run_id}", headers={"Authorization": f"Bearer {owner_token}"})
    assert owner_detail.status_code == 200
    detail_payload = owner_detail.json()
    assert detail_payload["id"] == run_id
    assert detail_payload["insight"] is not None
    assert detail_payload["insight"]["run_id"] == run_id
    assert len(detail_payload["insight"]["timeline"]) >= 1
    assert isinstance(detail_payload["insight"]["lessons"], list)

    lessons = client.get("/backtests/lessons", headers={"Authorization": f"Bearer {owner_token}"})
    assert lessons.status_code == 200
    assert len(lessons.json()) >= 1

    recommendations = client.get(
        "/backtests/recommendations",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert recommendations.status_code == 200
    assert isinstance(recommendations.json(), list)

    export_trades = client.get(
        f"/backtests/{run_id}/export?type=trades",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert export_trades.status_code == 200
    assert export_trades.headers["content-type"].startswith("text/csv")
    assert "direction,entry_timestamp" in export_trades.text

    export_equity = client.get(
        f"/backtests/{run_id}/export?type=equity",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert export_equity.status_code == 200
    assert "timestamp,equity" in export_equity.text

    other_detail = client.get(f"/backtests/{run_id}", headers={"Authorization": f"Bearer {other_token}"})
    assert other_detail.status_code == 404

    delete_other = client.delete(f"/backtests/{run_id}", headers={"Authorization": f"Bearer {other_token}"})
    assert delete_other.status_code == 404

    delete_owner = client.delete(f"/backtests/{run_id}", headers={"Authorization": f"Bearer {owner_token}"})
    assert delete_owner.status_code == 204

    owner_list_after_delete = client.get("/backtests", headers={"Authorization": f"Bearer {owner_token}"})
    assert owner_list_after_delete.status_code == 200
    assert owner_list_after_delete.json() == []

    app.dependency_overrides.clear()


def test_backtest_run_persists_period_mode_and_chart_window(tmp_path: Path) -> None:
    test_session_factory = _build_test_session_factory(tmp_path)

    def override_get_db_session():
        session = test_session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
    client = TestClient(app)

    start = datetime(2024, 1, 1, tzinfo=UTC)
    with test_session_factory() as session:
        session.add(
            User(
                email="period_mode@example.com",
                password_hash=hash_password("StrongPass123"),
                display_name="Period Mode",
                is_active=True,
            )
        )
        instrument = Instrument(symbol="MSFT", name="Microsoft", exchange="NASDAQ", currency="USD")
        session.add(instrument)
        session.flush()

        bars: list[MarketBar] = []
        for idx in range(250):
            close = Decimal("100") + Decimal(idx) * Decimal("0.01")
            bars.append(
                MarketBar(
                    instrument_id=instrument.id,
                    timeframe="1d",
                    timestamp=start + timedelta(days=idx),
                    open=close,
                    high=close,
                    low=close,
                    close=close,
                    volume=Decimal("1000"),
                )
            )
        session.add_all(bars)
        session.commit()

    login = client.post(
        "/auth/login",
        json={"email": "period_mode@example.com", "password": "StrongPass123"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    create_run = client.post(
        "/backtests/run",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "symbol": "MSFT",
            "timeframe": "1d",
            "strategies": ["rsi_mean_reversion"],
            "limit": 407,
            "period_mode": "bars",
            "chart_window": None,
            "initial_capital": 10000,
            "fee_bps": 5,
            "slippage_bps": 2,
            "min_signal_strength": 0.1,
        },
    )
    assert create_run.status_code == 201
    created = create_run.json()
    config = created["result_summary"]["config"]
    assert config["limit"] == 407
    assert config["period_mode"] == "bars"
    assert config["chart_window"] is None

    app.dependency_overrides.clear()
