from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.dependencies import get_db_session
from app.db.models import Instrument, MarketBar
from app.main import app


def _build_test_session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite:///{tmp_path / 'test_phase4_signals.db'}")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_generate_and_list_signals_endpoints(tmp_path: Path) -> None:
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

        start_date = datetime(2026, 1, 1, tzinfo=UTC)
        closes = [100 + index for index in range(40)] + [140 - index for index in range(20)]
        for index, close in enumerate(closes):
            open_price = Decimal(str(close - 1))
            close_price = Decimal(str(close))
            session.add(
                MarketBar(
                    instrument_id=instrument.id,
                    timeframe="1d",
                    timestamp=start_date + timedelta(days=index),
                    open=open_price,
                    high=Decimal(str(close + 2)),
                    low=Decimal(str(close - 2)),
                    close=close_price,
                    volume=Decimal(str(1000 + index * 5)),
                )
            )
        session.commit()

    client = TestClient(app)
    generate_response = client.post(
        "/signals/generate",
        json={
            "symbol": "AAPL",
            "timeframe": "1d",
            "strategy": "macd_crossover",
            "limit": 500,
        },
    )
    assert generate_response.status_code == 201
    generate_payload = generate_response.json()
    assert generate_payload["strategy"] == "macd_crossover"
    assert generate_payload["generated_count"] >= 1
    assert len(generate_payload["signals"]) == generate_payload["generated_count"]

    list_response = client.get("/signals", params={"symbol": "AAPL", "strategy": "macd_crossover"})
    assert list_response.status_code == 200
    listed_signals = list_response.json()
    assert len(listed_signals) == generate_payload["generated_count"]
    assert listed_signals[0]["strategy"] == "macd_crossover"
    assert listed_signals[0]["symbol"] == "AAPL"

    strategies_response = client.get("/signals/strategies")
    assert strategies_response.status_code == 200
    assert "macd_crossover" in strategies_response.json()

    app.dependency_overrides.clear()
