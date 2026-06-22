from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.dependencies import get_db_session
from app.db.models import Instrument, MarketBar
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

    client = TestClient(app)
    response = client.post(
        "/market-data/import-csv",
        json={"symbol": "AAPL", "timeframe": "1d", "csv_path": "C:/tmp/candles.csv"},
    )

    app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json() == {"symbol": "AAPL", "timeframe": "1d", "imported_rows": 2}
