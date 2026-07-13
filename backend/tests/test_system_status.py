from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies.auth import get_current_user
from app.core.config import Settings
from app.db.base import Base
from app.db.dependencies import get_db_session
from app.db.models import Instrument, MarketBar, User
from app.main import app
from app.services.system_diagnostics import (
    STATUS_FAIL,
    STATUS_OK,
    STATUS_WARN,
    CheckResult,
    check_bar_freshness,
    check_gateway_socket,
    freshness_verdict,
    worst_status,
)

NOW = datetime(2026, 7, 9, 16, 0, 0, tzinfo=UTC)


def _build_test_session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite:///{tmp_path / 'test_system_status.db'}")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


# -- pure verdict helpers -------------------------------------------------------


def test_freshness_verdict_fresh_stale_and_missing() -> None:
    fresh, age = freshness_verdict("5m", NOW - timedelta(hours=1), NOW)
    assert fresh == STATUS_OK
    assert age == pytest.approx(3600)

    stale, _ = freshness_verdict("5m", NOW - timedelta(days=15), NOW)
    assert stale == STATUS_WARN

    missing, missing_age = freshness_verdict("5m", None, NOW)
    assert missing == STATUS_FAIL
    assert missing_age is None


def test_worst_status_picks_most_severe() -> None:
    def result(status: str) -> CheckResult:
        return CheckResult(key="k", label="l", status=status, detail="d")

    assert worst_status([result(STATUS_OK), result(STATUS_OK)]) == STATUS_OK
    assert worst_status([result(STATUS_OK), result(STATUS_WARN)]) == STATUS_WARN
    assert worst_status([result(STATUS_WARN), result(STATUS_FAIL)]) == STATUS_FAIL
    assert worst_status([]) == STATUS_WARN


# -- gateway socket check -------------------------------------------------------


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def test_gateway_check_ok_when_configured_port_open() -> None:
    result = check_gateway_socket(_settings(), probe=lambda _h, _p, _t: True)
    assert result.status == STATUS_OK


def test_gateway_check_hints_at_open_sibling_port() -> None:
    # Configured 4002 closed, but the Gateway answers on 4001 (the live default)
    # — exactly the misconfiguration diagnosed live on 2026-07-09.
    result = check_gateway_socket(
        _settings(ibkr_gateway_port=4002),
        probe=lambda _h, port, _t: port == 4001,
    )
    assert result.status == STATUS_FAIL
    assert result.data["open_sibling_port"] == 4001
    assert "4001" in (result.hint or "")


def test_gateway_check_fails_when_everything_closed() -> None:
    result = check_gateway_socket(_settings(), probe=lambda _h, _p, _t: False)
    assert result.status == STATUS_FAIL
    assert "fechada" in result.detail


# -- bar freshness check --------------------------------------------------------


def test_bar_freshness_flags_stale_and_missing_series(tmp_path: Path) -> None:
    factory = _build_test_session_factory(tmp_path)
    with factory() as session:
        followed = Instrument(symbol="AMD", name="AMD", exchange="NASDAQ", currency="USD")
        session.add(followed)
        session.flush()
        # Fresh 1d bar, but no 5m bars at all -> the 5m series must be flagged.
        session.add(
            MarketBar(
                instrument_id=followed.id,
                timeframe="1d",
                timestamp=NOW - timedelta(hours=20),
                open=Decimal("100"),
                high=Decimal("110"),
                low=Decimal("95"),
                close=Decimal("105"),
                volume=Decimal("1000"),
            )
        )
        session.commit()

        settings = _settings(realtime_feed_timeframes="5m,1d")
        result = check_bar_freshness(session, settings, now=NOW)

    assert result.status == STATUS_WARN
    assert "AMD 5m (sem barras)" in result.detail
    assert result.data["series_total"] == 2
    assert result.data["series_stale"] == 1


def test_bar_freshness_ok_when_everything_fresh(tmp_path: Path) -> None:
    factory = _build_test_session_factory(tmp_path)
    with factory() as session:
        followed = Instrument(symbol="AAPL", name="Apple", exchange="NASDAQ", currency="USD")
        session.add(followed)
        session.flush()
        for timeframe, age in (("5m", timedelta(minutes=10)), ("1d", timedelta(hours=20))):
            session.add(
                MarketBar(
                    instrument_id=followed.id,
                    timeframe=timeframe,
                    timestamp=NOW - age,
                    open=Decimal("100"),
                    high=Decimal("110"),
                    low=Decimal("95"),
                    close=Decimal("105"),
                    volume=Decimal("1000"),
                )
            )
        session.commit()

        settings = _settings(realtime_feed_timeframes="5m,1d")
        result = check_bar_freshness(session, settings, now=NOW)

    assert result.status == STATUS_OK
    assert result.data["series_total"] == 2


# -- endpoint -------------------------------------------------------------------


def test_system_status_endpoint_returns_aggregated_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.services.system_diagnostics as diagnostics

    # Deterministic offline probe: whatever runs on this machine's ports must
    # not influence the test.
    monkeypatch.setattr(diagnostics, "default_port_probe", lambda _h, _p, _t=1.5: False)

    factory = _build_test_session_factory(tmp_path)

    def override_get_db_session():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1, email="user@example.com", password_hash="hash"
    )

    client = TestClient(app)
    response = client.get("/system/status")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["overall"] in {"ok", "warn", "fail"}
    keys = {check["key"] for check in payload["checks"]}
    assert {
        "database",
        "gateway",
        "feed_worker",
        "bar_freshness",
        "paper_engine",
        "environment",
    } <= keys

    by_key = {check["key"]: check for check in payload["checks"]}
    # All IBKR ports closed in the fake probe -> gateway must fail with a hint.
    assert by_key["gateway"]["status"] == "fail"
    assert by_key["gateway"]["hint"]
    # Sorted worst-first: no check may be more severe than its predecessor.
    severity = {"fail": 2, "warn": 1, "ok": 0}
    ranks = [severity[check["status"]] for check in payload["checks"]]
    assert ranks == sorted(ranks, reverse=True)


def test_system_status_requires_auth() -> None:
    client = TestClient(app)
    assert client.get("/system/status").status_code == 401
