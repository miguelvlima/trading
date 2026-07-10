"""Fills de ordens SELL cuja posição desapareceu (ou encolheu) entre a
aprovação e o fill: cancelar/ajustar em vez de crashar ou corromper o cash."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models import (
    PaperEngineEvent,
    PaperOrder,
    PaperPortfolio,
    PaperPosition,
    User,
)
from app.services.data_feed.types import Tick
from app.services.execution_engine import commission_for_order
from app.services.paper_trading.engine import PaperEngine
from app.services.paper_trading.quotes import QuoteCache
from app.services.paper_trading.types import (
    STATUS_APPROVED,
    STATUS_CANCELLED,
    STATUS_FILLED,
)

RTH_NOW = datetime(2026, 7, 6, 15, 0, tzinfo=UTC)  # Monday 15:00 UTC (RTH)


class Clock:
    def __init__(self, now: datetime = RTH_NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now = self.now + timedelta(**kwargs)


def build_session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite:///{tmp_path / 'test_paper_position_gone.db'}")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def seed_portfolio(
    session: Session, *, cash: float = 100_000.0, risk: dict | None = None
) -> PaperPortfolio:
    user = User(email="paper@example.com", password_hash="hash")
    session.add(user)
    session.flush()
    portfolio = PaperPortfolio(
        owner_user_id=user.id,
        initial_cash=Decimal(str(cash)),
        cash=Decimal(str(cash)),
        equity=Decimal(str(cash)),
        risk_settings=risk or {},
        engine_running=True,
    )
    session.add(portfolio)
    session.commit()
    return portfolio


def feed_quote(
    cache: QuoteCache,
    symbol: str,
    *,
    last: float | None = None,
    bid: float | None = None,
    ask: float | None = None,
) -> None:
    cache.update_from_tick(
        Tick(
            symbol=symbol,
            timestamp=RTH_NOW,
            last=Decimal(str(last)) if last is not None else None,
            bid=Decimal(str(bid)) if bid is not None else None,
            ask=Decimal(str(ask)) if ask is not None else None,
        )
    )


def build_engine(portfolio: PaperPortfolio, clock: Clock) -> tuple[PaperEngine, QuoteCache]:
    cache = QuoteCache(now_fn=clock)
    cache.set_liveness("DELAYED")
    engine = PaperEngine(portfolio.id, quotes=cache, hub=None, now_fn=clock)
    return engine, cache


def approved_sell(
    session: Session, portfolio: PaperPortfolio, symbol: str, quantity: float
) -> PaperOrder:
    order = PaperOrder(
        portfolio_id=portfolio.id,
        symbol=symbol,
        side="SELL",
        quantity=Decimal(str(quantity)),
        order_type="market",
        status=STATUS_APPROVED,
        signal_snapshot={"origin": "protective", "trigger": "stop_loss"},
        risk_snapshot={},
        data_liveness="DELAYED",
        proposed_at=RTH_NOW,
        decided_at=RTH_NOW,
    )
    session.add(order)
    session.flush()
    return order


def events_with_code(session: Session, portfolio_id: int, code: str) -> list[PaperEngineEvent]:
    return [
        event
        for event in session.execute(
            select(PaperEngineEvent)
            .where(PaperEngineEvent.portfolio_id == portfolio_id)
            .order_by(PaperEngineEvent.id)
        ).scalars()
        if (event.payload or {}).get("code") == code
    ]


def test_sell_without_position_is_cancelled_not_crash(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    clock = Clock()
    with factory() as session:
        portfolio = seed_portfolio(session)
        engine, cache = build_engine(portfolio, clock)
        feed_quote(cache, "AAPL", last=100.0, bid=99.9, ask=100.1)
        cash_before = float(portfolio.cash)

        order = approved_sell(session, portfolio, "AAPL", 10.0)  # no position at all
        trade, deferral = engine.try_fill_order(session, portfolio, order)
        session.commit()

        assert (trade, deferral) == (None, None)
        assert order.status == STATUS_CANCELLED
        assert order.reject_reason is not None
        assert "não existia" in order.reject_reason
        assert float(portfolio.cash) == cash_before

        cancelled = events_with_code(session, portfolio.id, "position_gone")
        assert len(cancelled) == 1
        assert cancelled[0].event_type == "order_cancelled"
        assert cancelled[0].payload["order_id"] == order.id


def test_sell_clamped_to_partial_position(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    clock = Clock()
    with factory() as session:
        # fixed_bps fees scale linearly with notional, so a fee computed on 10
        # shares is unmistakably different from one computed on 4.
        portfolio = seed_portfolio(session, risk={"fee_model": "fixed_bps", "fee_bps": 100.0})
        engine, cache = build_engine(portfolio, clock)
        feed_quote(cache, "MSFT", last=300.0, bid=299.9, ask=300.1)
        session.add(
            PaperPosition(
                portfolio_id=portfolio.id,
                symbol="MSFT",
                quantity=Decimal("4"),
                avg_entry_price=Decimal("250"),
            )
        )
        session.flush()

        order = approved_sell(session, portfolio, "MSFT", 10.0)
        trade, deferral = engine.try_fill_order(session, portfolio, order)
        session.commit()

        assert deferral is None and trade is not None
        assert order.status == STATUS_FILLED
        assert float(trade.quantity) == 4.0

        position = session.execute(
            select(PaperPosition).where(
                PaperPosition.portfolio_id == portfolio.id,
                PaperPosition.symbol == "MSFT",
            )
        ).scalar_one()
        assert float(position.quantity) == 0.0

        fill_price = float(trade.price)  # SELL fills at the bid
        fee_on_4 = commission_for_order(
            fee_model="fixed_bps", shares=4.0, notional=fill_price * 4.0, fee_bps=100.0
        )
        fee_on_10 = commission_for_order(
            fee_model="fixed_bps", shares=10.0, notional=fill_price * 10.0, fee_bps=100.0
        )
        assert float(trade.fee_paid) == pytest.approx(fee_on_4)
        assert float(trade.fee_paid) != pytest.approx(fee_on_10)

        clamped = events_with_code(session, portfolio.id, "quantity_clamped")
        assert len(clamped) == 1
        assert clamped[0].severity == "warn"
