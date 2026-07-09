"""Auto-resume of paper engines on app startup (lifespan).

A backend restart wipes the in-memory RuntimeRegistry while the DB keeps
``engine_running=True``; ``resume_running_engines`` must recreate exactly
those runtimes and survive DB/startup failures without raising.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models import PaperEngineEvent, PaperPortfolio, User
from app.services.paper_trading import runtime as runtime_mod
from app.services.paper_trading.runtime import resume_running_engines


def build_session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite:///{tmp_path / 'test_paper_resume.db'}")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def make_portfolio(session: Session, email: str, *, running: bool) -> int:
    user = User(email=email, password_hash="hash")
    session.add(user)
    session.flush()
    portfolio = PaperPortfolio(
        owner_user_id=user.id,
        initial_cash=Decimal("100000"),
        cash=Decimal("100000"),
        equity=Decimal("100000"),
        risk_settings={},
        engine_running=running,
    )
    session.add(portfolio)
    session.commit()
    return portfolio.id


def test_resume_starts_only_flagged_portfolios(tmp_path: Path, monkeypatch) -> None:
    factory = build_session_factory(tmp_path)
    with factory() as session:
        running_id = make_portfolio(session, "resume-on@example.com", running=True)
        make_portfolio(session, "resume-off@example.com", running=False)

    monkeypatch.setattr(runtime_mod, "SessionLocal", factory)
    started: list[int] = []

    async def fake_start(portfolio_id: int, settings) -> None:
        started.append(portfolio_id)

    monkeypatch.setattr(runtime_mod.registry, "start", fake_start)

    resumed = asyncio.run(resume_running_engines(SimpleNamespace()))

    assert started == [running_id]
    assert resumed == [running_id]
    with factory() as session:
        events = list(
            session.execute(
                select(PaperEngineEvent).where(
                    PaperEngineEvent.portfolio_id == running_id
                )
            ).scalars()
        )
    assert len(events) == 1
    assert events[0].event_type == "engine_started"
    assert "retomado automaticamente" in events[0].message


def test_resume_survives_db_failure(monkeypatch) -> None:
    def broken_session_factory():
        raise RuntimeError("db down")

    monkeypatch.setattr(runtime_mod, "SessionLocal", broken_session_factory)

    resumed = asyncio.run(resume_running_engines(SimpleNamespace()))

    assert resumed == []


def test_resume_continues_past_one_bad_portfolio(tmp_path: Path, monkeypatch) -> None:
    factory = build_session_factory(tmp_path)
    with factory() as session:
        bad_id = make_portfolio(session, "resume-bad@example.com", running=True)
        good_id = make_portfolio(session, "resume-good@example.com", running=True)

    monkeypatch.setattr(runtime_mod, "SessionLocal", factory)

    async def fake_start(portfolio_id: int, settings) -> None:
        if portfolio_id == bad_id:
            raise RuntimeError("boom")

    monkeypatch.setattr(runtime_mod.registry, "start", fake_start)

    resumed = asyncio.run(resume_running_engines(SimpleNamespace()))

    assert resumed == [good_id]
