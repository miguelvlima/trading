from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies.auth import get_current_user
from app.db.base import Base
from app.db.dependencies import get_db_session
from app.db.models import Instrument, MarketBar, User
from app.main import app
from app.services.csv_importer import CsvImportResult


def _build_test_session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite:///{tmp_path / 'test_phase2.db'}")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_list_instruments_and_bars(tmp_path: Path) -> None:
    test_session_factory = _build_test_session_factory(tmp_path)

    def override_get_db_session():
        session = test_session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1, email="user@example.com", password_hash="hash"
    )

    with test_session_factory() as session:
        instrument = Instrument(symbol="AAPL", name="Apple", exchange="NASDAQ", currency="USD")
        session.add(instrument)
        session.flush()
        session.add(
            MarketBar(
                instrument_id=instrument.id,
                timeframe="1d",
                timestamp=datetime(2026, 6, 20, tzinfo=UTC),
                open=Decimal("100"),
                high=Decimal("110"),
                low=Decimal("95"),
                close=Decimal("105"),
                volume=Decimal("1000"),
            )
        )
        session.commit()

    client = TestClient(app)
    instruments_response = client.get("/market-data/instruments")
    bars_response = client.get("/market-data/bars", params={"symbol": "AAPL", "timeframe": "1d"})

    app.dependency_overrides.clear()

    assert instruments_response.status_code == 200
    assert instruments_response.json() == [
        {
            "id": 1,
            "symbol": "AAPL",
            "name": "Apple",
            "exchange": "NASDAQ",
            "currency": "USD",
        }
    ]

    assert bars_response.status_code == 200
    assert len(bars_response.json()) == 1
    assert bars_response.json()[0]["close"] == "105.00000000"


def test_import_csv_endpoint_uses_import_service(monkeypatch: pytest.MonkeyPatch) -> None:
    def override_get_db_session():
        yield object()

    def fake_importer(*_args, **_kwargs):
        return CsvImportResult(symbol="AAPL", timeframe="1d", imported_rows=2)

    import app.api.routes.market_data as market_data_route

    monkeypatch.setattr(market_data_route, "import_ohlcv_csv", fake_importer)
    app.dependency_overrides[get_db_session] = override_get_db_session

    user = User(id=1, email="user@example.com", password_hash="hash")
    app.dependency_overrides[get_current_user] = lambda: user

    client = TestClient(app)
    response = client.post(
        "/market-data/import-csv",
        json={"symbol": "AAPL", "timeframe": "1d", "csv_path": "C:/tmp/candles.csv"},
    )

    app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json() == {"symbol": "AAPL", "timeframe": "1d", "imported_rows": 2}


def test_load_demo_endpoint_uses_demo_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_load_symbol(symbol: str, period: str, include_weekly: bool) -> tuple[int, int]:
        assert symbol == "AAPL"
        assert period == "2y"
        assert include_weekly is False
        return 120, 0

    import app.api.routes.market_data as market_data_route

    monkeypatch.setattr(market_data_route, "load_symbol", fake_load_symbol)
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1, email="user@example.com", password_hash="hash"
    )

    client = TestClient(app)
    response = client.post(
        "/market-data/load-demo",
        json={"symbols": ["AAPL"], "period": "2y", "include_weekly": False},
    )

    app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json() == {
        "results": [{"symbol": "AAPL", "imported_rows_1d": 120, "imported_rows_1w": 0}],
    }


def test_get_indicators_endpoint_returns_rows(tmp_path: Path) -> None:
    test_session_factory = _build_test_session_factory(tmp_path)

    def override_get_db_session():
        session = test_session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1, email="user@example.com", password_hash="hash"
    )

    with test_session_factory() as session:
        instrument = Instrument(symbol="AAPL", name="Apple", exchange="NASDAQ", currency="USD")
        session.add(instrument)
        session.flush()
        start_date = datetime(2026, 1, 1, tzinfo=UTC)
        for day in range(1, 41):
            open_price = Decimal(str(100 + day))
            high_price = open_price + Decimal("2")
            low_price = open_price - Decimal("2")
            close_price = open_price + Decimal("1")
            volume = Decimal(str(1000 + day * 10))
            session.add(
                MarketBar(
                    instrument_id=instrument.id,
                    timeframe="1d",
                    timestamp=start_date + timedelta(days=day - 1),
                    open=open_price,
                    high=high_price,
                    low=low_price,
                    close=close_price,
                    volume=volume,
                )
            )
        session.commit()

    client = TestClient(app)
    response = client.get("/market-data/indicators", params={"symbol": "AAPL", "timeframe": "1d"})

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "AAPL"
    assert payload["timeframe"] == "1d"
    assert len(payload["rows"]) == 40
    last_row = payload["rows"][-1]
    assert last_row["sma_20"] is not None
    assert last_row["ema_20"] is not None
    assert last_row["rsi_14"] is not None
    assert last_row["macd"] is not None
    assert last_row["bollinger_upper"] is not None
    assert last_row["atr_14"] is not None
    assert last_row["vwap"] is not None


def test_get_indicators_endpoint_respects_date_range(tmp_path: Path) -> None:
    test_session_factory = _build_test_session_factory(tmp_path)

    def override_get_db_session():
        session = test_session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1, email="user@example.com", password_hash="hash"
    )

    with test_session_factory() as session:
        instrument = Instrument(symbol="MSFT", name="Microsoft", exchange="NASDAQ", currency="USD")
        session.add(instrument)
        session.flush()

        start_date = datetime(2026, 1, 1, tzinfo=UTC)
        for day in range(0, 10):
            open_price = Decimal(str(200 + day))
            session.add(
                MarketBar(
                    instrument_id=instrument.id,
                    timeframe="1d",
                    timestamp=start_date + timedelta(days=day),
                    open=open_price,
                    high=open_price + Decimal("2"),
                    low=open_price - Decimal("2"),
                    close=open_price + Decimal("1"),
                    volume=Decimal("1500"),
                )
            )
        session.commit()

    client = TestClient(app)
    response = client.get(
        "/market-data/indicators",
        params={
            "symbol": "MSFT",
            "timeframe": "1d",
            "start": "2026-01-03T00:00:00Z",
            "end": "2026-01-05T23:59:59Z",
        },
    )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["rows"]) == 3
    assert payload["rows"][0]["timestamp"].startswith("2026-01-03")
    assert payload["rows"][-1]["timestamp"].startswith("2026-01-05")
