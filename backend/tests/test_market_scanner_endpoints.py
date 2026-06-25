from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_user
from app.api.routes.realtime_data import get_provider
from app.db.models import User
from app.main import app
from app.services.data_feed.types import BarQuote, SymbolMatch
from fakes import FakeProvider


def _bars(symbol: str, opens_closes: list[tuple[str, str]]) -> list[BarQuote]:
    out: list[BarQuote] = []
    for index, (open_, close) in enumerate(opens_closes):
        out.append(
            BarQuote(
                symbol=symbol,
                timestamp=datetime(2026, 6, 25, 14, index, tzinfo=UTC),
                open=Decimal(open_),
                high=Decimal(close),
                low=Decimal(open_),
                close=Decimal(close),
                volume=Decimal("1000"),
                is_final=True,
            )
        )
    return out


def _auth() -> None:
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1, email="user@example.com", password_hash="hash"
    )


def test_hot_movers_returns_sorted_items_with_sparkline() -> None:
    provider = FakeProvider(
        scan_results=[
            SymbolMatch(symbol="AAA", name=None, sec_type="STK", exchange="SMART", currency="USD"),
            SymbolMatch(symbol="BBB", name=None, sec_type="STK", exchange="SMART", currency="USD"),
        ],
        bars={
            # AAA rises 100 -> 110 (+10%); BBB rises 100 -> 102 (+2%).
            "AAA": _bars("AAA", [("100", "100"), ("100", "105"), ("100", "110")]),
            "BBB": _bars("BBB", [("100", "100"), ("100", "101"), ("100", "102")]),
        },
    )

    _auth()
    app.dependency_overrides[get_provider] = lambda: provider
    client = TestClient(app)
    response = client.get(
        "/market-scanner/hot-movers", params={"sort": "change_pct", "direction": "both"}
    )
    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["sort"] == "change_pct"
    symbols = [item["symbol"] for item in payload["items"]]
    # Bigger mover (AAA, +10%) ranks ahead of BBB (+2%).
    assert symbols == ["AAA", "BBB"]
    assert payload["items"][0]["spark"]["points"][-1] == 110.0
    assert payload["items"][0]["spark"]["interval"] == "5m"


def test_hot_movers_min_price_filters_penny_stocks() -> None:
    provider = FakeProvider(
        scan_results=[
            SymbolMatch(symbol="PENNY", name=None, sec_type="STK", exchange="SMART", currency="USD"),
            SymbolMatch(symbol="REAL", name=None, sec_type="STK", exchange="SMART", currency="USD"),
        ],
        bars={
            "PENNY": _bars("PENNY", [("0.10", "0.11"), ("0.10", "0.12")]),
            "REAL": _bars("REAL", [("50", "51"), ("50", "55")]),
        },
    )

    _auth()
    app.dependency_overrides[get_provider] = lambda: provider
    client = TestClient(app)
    response = client.get("/market-scanner/hot-movers", params={"min_price": 1.0})
    app.dependency_overrides.clear()

    assert response.status_code == 200
    symbols = [item["symbol"] for item in response.json()["items"]]
    assert symbols == ["REAL"]  # PENNY (0.12) filtered out by min_price


def test_hot_movers_direction_up_excludes_fallers() -> None:
    provider = FakeProvider(
        scan_results=[
            SymbolMatch(symbol="UP", name=None, sec_type="STK", exchange="SMART", currency="USD"),
            SymbolMatch(symbol="DOWN", name=None, sec_type="STK", exchange="SMART", currency="USD"),
        ],
        bars={
            "UP": _bars("UP", [("100", "100"), ("100", "108")]),
            "DOWN": _bars("DOWN", [("100", "100"), ("100", "92")]),
        },
    )

    _auth()
    app.dependency_overrides[get_provider] = lambda: provider
    client = TestClient(app)
    response = client.get("/market-scanner/hot-movers", params={"direction": "up"})
    app.dependency_overrides.clear()

    assert response.status_code == 200
    symbols = [item["symbol"] for item in response.json()["items"]]
    assert symbols == ["UP"]


def test_hot_movers_requires_auth() -> None:
    client = TestClient(app)
    assert client.get("/market-scanner/hot-movers").status_code == 401
