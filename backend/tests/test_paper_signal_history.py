"""Signal history for the cockpit: every signal the engine sees becomes one
``signal_received`` event whose payload carries the full context (strength,
rationale, bar time, threshold) plus the final outcome — weak signals included.
``GET /paper/signals`` exposes those rows to the chart/table."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies.auth import get_current_user
from app.db.base import Base
from app.db.dependencies import get_db_session
from app.db.models import PaperEngineEvent, PaperPortfolio, User
from app.main import app
from app.services.data_feed.types import Tick
from app.services.paper_trading.engine import PaperEngine
from app.services.paper_trading.quotes import QuoteCache

RTH_NOW = datetime(2026, 7, 8, 15, 0, tzinfo=UTC)  # Wednesday 15:00 UTC


def build_session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite:///{tmp_path / 'test_signal_history.db'}")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def seed_portfolio(session: Session, *, risk: dict | None = None) -> PaperPortfolio:
    user = User(email="signals@example.com", password_hash="hash")
    session.add(user)
    session.flush()
    portfolio = PaperPortfolio(
        owner_user_id=user.id,
        initial_cash=Decimal("100000"),
        cash=Decimal("100000"),
        equity=Decimal("100000"),
        risk_settings=risk or {},
        engine_running=True,
    )
    session.add(portfolio)
    session.commit()
    return portfolio


def build_engine(portfolio: PaperPortfolio) -> tuple[PaperEngine, QuoteCache]:
    cache = QuoteCache(now_fn=lambda: RTH_NOW)
    cache.set_liveness("DELAYED")
    engine = PaperEngine(portfolio.id, quotes=cache, hub=None, now_fn=lambda: RTH_NOW)
    return engine, cache


def feed_quote(cache: QuoteCache, symbol: str, last: float) -> None:
    cache.update_from_tick(
        Tick(
            symbol=symbol,
            timestamp=RTH_NOW,
            last=Decimal(str(last)),
            bid=Decimal(str(last - 0.05)),
            ask=Decimal(str(last + 0.05)),
        )
    )


def signal_events(session: Session, portfolio_id: int) -> list[PaperEngineEvent]:
    return list(
        session.execute(
            select(PaperEngineEvent)
            .where(
                PaperEngineEvent.portfolio_id == portfolio_id,
                PaperEngineEvent.event_type == "signal_received",
            )
            .order_by(PaperEngineEvent.id)
        ).scalars()
    )


def test_weak_signal_is_recorded_with_skip_outcome(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    with factory() as session:
        portfolio = seed_portfolio(session)
        engine, cache = build_engine(portfolio)
        feed_quote(cache, "AAPL", 100.0)

        order = engine.propose_from_signal(
            session,
            portfolio,
            symbol="AAPL",
            direction="BUY",
            strength=0.01,
            strategy="bollinger_breakout",
            rationale="Fecho acima da banda superior.",
            signal_timestamp=RTH_NOW,
        )
        session.commit()

        assert order is None
        events = signal_events(session, portfolio.id)
        assert len(events) == 1
        payload = events[0].payload
        assert payload["outcome"] == "skipped"
        assert payload["reason"] == "below_min_strength"
        assert payload["strength"] == 0.01
        assert payload["min_strength"] == 0.3
        assert payload["rationale"] == "Fecho acima da banda superior."
        assert payload["signal_timestamp"] == RTH_NOW.isoformat()


def test_strong_signal_is_recorded_with_proposed_outcome(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    with factory() as session:
        portfolio = seed_portfolio(session)
        engine, cache = build_engine(portfolio)
        feed_quote(cache, "AAPL", 100.0)

        order = engine.propose_from_signal(
            session,
            portfolio,
            symbol="AAPL",
            direction="BUY",
            strength=0.8,
            strategy="rsi_mean_reversion",
            rationale="RSI em sobrevenda.",
            signal_timestamp=RTH_NOW,
        )
        session.commit()

        assert order is not None
        payload = signal_events(session, portfolio.id)[0].payload
        assert payload["outcome"] == "proposed"
        assert payload["order_id"] == order.id


def test_vetoed_signal_is_recorded_with_veto_outcome(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    with factory() as session:
        portfolio = seed_portfolio(session)
        portfolio.kill_switch_active = True
        session.commit()
        engine, cache = build_engine(portfolio)
        feed_quote(cache, "AAPL", 100.0)

        order = engine.propose_from_signal(
            session,
            portfolio,
            symbol="AAPL",
            direction="BUY",
            strength=0.8,
            strategy="rsi_mean_reversion",
            rationale="RSI em sobrevenda.",
            signal_timestamp=RTH_NOW,
        )
        session.commit()

        assert order is not None and order.reject_reason is not None
        payload = signal_events(session, portfolio.id)[0].payload
        assert payload["outcome"] == "vetoed"
        assert payload["reason"]  # the veto code
        assert payload["order_id"] == order.id


def test_signals_endpoint_returns_history_newest_first(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)

    def override_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    with factory() as session:
        portfolio = seed_portfolio(session)
        user_id = portfolio.owner_user_id
        engine, cache = build_engine(portfolio)
        feed_quote(cache, "AAPL", 100.0)
        feed_quote(cache, "NVDA", 500.0)
        engine.propose_from_signal(
            session,
            portfolio,
            symbol="AAPL",
            direction="BUY",
            strength=0.01,
            strategy="bollinger_breakout",
            rationale="fraco",
            signal_timestamp=RTH_NOW,
        )
        engine.propose_from_signal(
            session,
            portfolio,
            symbol="NVDA",
            direction="BUY",
            strength=0.9,
            strategy="macd_crossover",
            rationale="forte",
            signal_timestamp=RTH_NOW,
        )
        session.commit()

    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=user_id, is_active=True
    )
    try:
        client = TestClient(app)
        response = client.get("/paper/signals")
        assert response.status_code == 200
        rows = response.json()
        assert [row["symbol"] for row in rows] == ["NVDA", "AAPL"]
        assert rows[0]["outcome"] == "proposed"
        assert rows[1]["outcome"] == "skipped"
        assert rows[1]["reason"] == "below_min_strength"
        assert rows[1]["strength"] == 0.01
        assert rows[1]["min_strength"] == 0.3
        assert rows[1]["bar_time"] == RTH_NOW.isoformat()

        only_aapl = client.get("/paper/signals", params={"symbol": "aapl"})
        assert [row["symbol"] for row in only_aapl.json()] == ["AAPL"]
    finally:
        app.dependency_overrides.clear()
