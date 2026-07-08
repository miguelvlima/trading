from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user
from app.core.config import Settings, get_settings
from app.db.dependencies import get_db_session
from app.db.models import (
    PaperEngineEvent,
    PaperOrder,
    PaperPortfolio,
    PaperPosition,
    PaperTrade,
    User,
)
from app.schemas.paper_trading import (
    EngineStatusResponse,
    PaperEventResponse,
    PaperOrderResponse,
    PaperPnlResponse,
    PaperPortfolioCreateRequest,
    PaperPortfolioResponse,
    PaperPositionResponse,
    PaperTradeResponse,
    RiskSettingsUpdateRequest,
)
from app.services.paper_trading import events as ev
from app.services.paper_trading.engine import PaperEngine
from app.services.paper_trading.events import hub, record_event
from app.services.paper_trading.quotes import QuoteCache
from app.services.paper_trading.runtime import registry
from app.services.paper_trading.types import STATUS_PROPOSED, RiskSettings

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/paper", tags=["paper-trading"])


def _get_portfolio(db: Session, user: User) -> PaperPortfolio:
    portfolio = db.execute(
        select(PaperPortfolio).where(PaperPortfolio.owner_user_id == user.id)
    ).scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Paper portfolio not found. Create one with POST /paper/portfolio.",
        )
    return portfolio


def _engine_for(portfolio: PaperPortfolio) -> PaperEngine:
    """Engine bound to the live runtime quotes when running, else an empty cache."""
    runtime = registry.get(portfolio.id)
    if runtime is not None:
        return runtime.engine
    return PaperEngine(portfolio.id, quotes=QuoteCache(), hub=hub)


def _portfolio_response(portfolio: PaperPortfolio) -> PaperPortfolioResponse:
    return PaperPortfolioResponse(
        id=portfolio.id,
        initial_cash=float(portfolio.initial_cash),
        cash=float(portfolio.cash),
        equity=float(portfolio.equity),
        risk_settings=RiskSettings.from_json(portfolio.risk_settings).to_json(),
        engine_running=portfolio.engine_running,
        kill_switch_active=portfolio.kill_switch_active,
        kill_switch_reason=portfolio.kill_switch_reason,
        created_at=portfolio.created_at,
        updated_at=portfolio.updated_at,
    )


def _order_response(order: PaperOrder) -> PaperOrderResponse:
    return PaperOrderResponse(
        id=order.id,
        symbol=order.symbol,
        side=order.side,
        quantity=float(order.quantity),
        order_type=order.order_type,
        status=order.status,
        stop_loss_pct=float(order.stop_loss_pct) if order.stop_loss_pct is not None else None,
        take_profit_pct=(
            float(order.take_profit_pct) if order.take_profit_pct is not None else None
        ),
        signal_snapshot=order.signal_snapshot,
        risk_snapshot=order.risk_snapshot,
        data_liveness=order.data_liveness,
        reject_reason=order.reject_reason,
        proposed_at=order.proposed_at,
        decided_at=order.decided_at,
        filled_at=order.filled_at,
    )


@router.post("/portfolio", response_model=PaperPortfolioResponse, status_code=status.HTTP_201_CREATED)
def create_portfolio(
    payload: PaperPortfolioCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> PaperPortfolioResponse:
    existing = db.execute(
        select(PaperPortfolio).where(PaperPortfolio.owner_user_id == current_user.id)
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Paper portfolio already exists for this user.",
        )
    settings_json = RiskSettings.from_json(payload.risk_settings).to_json()
    portfolio = PaperPortfolio(
        owner_user_id=current_user.id,
        initial_cash=payload.initial_cash,
        cash=payload.initial_cash,
        equity=payload.initial_cash,
        risk_settings=settings_json,
    )
    db.add(portfolio)
    db.flush()
    record_event(
        db,
        portfolio_id=portfolio.id,
        event_type=ev.EVENT_ENGINE_STOPPED,
        message=f"Portfolio paper criado com ${payload.initial_cash:,.2f}.",
        broadcast=hub,
    )
    db.commit()
    db.refresh(portfolio)
    return _portfolio_response(portfolio)


@router.get("/portfolio", response_model=PaperPortfolioResponse)
def get_portfolio(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> PaperPortfolioResponse:
    return _portfolio_response(_get_portfolio(db, current_user))


@router.put("/portfolio/risk-settings", response_model=PaperPortfolioResponse)
def update_risk_settings(
    payload: RiskSettingsUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> PaperPortfolioResponse:
    portfolio = _get_portfolio(db, current_user)
    merged = dict(portfolio.risk_settings or {})
    merged.update(payload.risk_settings)
    portfolio.risk_settings = RiskSettings.from_json(merged).to_json()
    db.commit()
    db.refresh(portfolio)
    return _portfolio_response(portfolio)


@router.get("/orders", response_model=list[PaperOrderResponse])
def list_orders(
    order_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=1000),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> list[PaperOrderResponse]:
    portfolio = _get_portfolio(db, current_user)
    query = select(PaperOrder).where(PaperOrder.portfolio_id == portfolio.id)
    if order_status:
        query = query.where(PaperOrder.status == order_status)
    orders = db.execute(query.order_by(PaperOrder.proposed_at.desc()).limit(limit)).scalars()
    return [_order_response(order) for order in orders]


def _decidable_order(db: Session, portfolio: PaperPortfolio, order_id: int) -> PaperOrder:
    order = db.execute(
        select(PaperOrder).where(
            PaperOrder.id == order_id, PaperOrder.portfolio_id == portfolio.id
        )
    ).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")
    if order.status != STATUS_PROPOSED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Order is '{order.status}', only 'proposed' orders can be decided.",
        )
    return order


@router.post("/orders/{order_id}/approve", response_model=PaperOrderResponse)
def approve_order(
    order_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> PaperOrderResponse:
    portfolio = _get_portfolio(db, current_user)
    order = _decidable_order(db, portfolio, order_id)
    engine = _engine_for(portfolio)
    order, _trade, _deferral = engine.approve_order(db, portfolio, order)
    db.commit()
    db.refresh(order)
    return _order_response(order)


@router.post("/orders/{order_id}/reject", response_model=PaperOrderResponse)
def reject_order(
    order_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> PaperOrderResponse:
    portfolio = _get_portfolio(db, current_user)
    order = _decidable_order(db, portfolio, order_id)
    engine = _engine_for(portfolio)
    engine.reject_order(db, portfolio, order)
    db.commit()
    db.refresh(order)
    return _order_response(order)


@router.get("/positions", response_model=list[PaperPositionResponse])
def list_positions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> list[PaperPositionResponse]:
    portfolio = _get_portfolio(db, current_user)
    runtime = registry.get(portfolio.id)
    positions = db.execute(
        select(PaperPosition).where(
            PaperPosition.portfolio_id == portfolio.id, PaperPosition.quantity > 0
        )
    ).scalars()

    responses: list[PaperPositionResponse] = []
    for pos in positions:
        last_price: float | None = None
        if runtime is not None:
            quote = runtime.quotes.get(pos.symbol)
            if quote is not None and quote.last is not None:
                last_price = float(quote.last)
        unrealized = (
            (last_price - float(pos.avg_entry_price)) * float(pos.quantity)
            if last_price is not None
            else None
        )
        responses.append(
            PaperPositionResponse(
                symbol=pos.symbol,
                quantity=float(pos.quantity),
                avg_entry_price=float(pos.avg_entry_price),
                realized_pnl=float(pos.realized_pnl),
                last_price=last_price,
                unrealized_pnl=unrealized,
                updated_at=pos.updated_at,
            )
        )
    return responses


@router.get("/trades", response_model=list[PaperTradeResponse])
def list_trades(
    limit: int = Query(default=200, ge=1, le=2000),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> list[PaperTradeResponse]:
    portfolio = _get_portfolio(db, current_user)
    trades = db.execute(
        select(PaperTrade)
        .where(PaperTrade.portfolio_id == portfolio.id)
        .order_by(PaperTrade.executed_at.desc())
        .limit(limit)
    ).scalars()
    return [
        PaperTradeResponse(
            id=trade.id,
            order_id=trade.order_id,
            symbol=trade.symbol,
            side=trade.side,
            quantity=float(trade.quantity),
            price=float(trade.price),
            fee_paid=float(trade.fee_paid),
            fill_basis=trade.fill_basis,
            quote_age_seconds=(
                float(trade.quote_age_seconds) if trade.quote_age_seconds is not None else None
            ),
            data_liveness=trade.data_liveness,
            realized_pnl=float(trade.realized_pnl) if trade.realized_pnl is not None else None,
            executed_at=trade.executed_at,
        )
        for trade in trades
    ]


@router.get("/pnl", response_model=PaperPnlResponse)
def get_pnl(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> PaperPnlResponse:
    portfolio = _get_portfolio(db, current_user)
    engine = _engine_for(portfolio)
    return PaperPnlResponse(**engine.pnl_snapshot(db, portfolio))


@router.get("/events", response_model=list[PaperEventResponse])
def list_events(
    limit: int = Query(default=100, ge=1, le=500),
    before_id: int | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> list[PaperEventResponse]:
    """Ledger page, newest first; pass ``before_id`` to walk further back."""
    portfolio = _get_portfolio(db, current_user)
    query = select(PaperEngineEvent).where(PaperEngineEvent.portfolio_id == portfolio.id)
    if before_id is not None:
        query = query.where(PaperEngineEvent.id < before_id)
    events = db.execute(query.order_by(PaperEngineEvent.id.desc()).limit(limit)).scalars()
    return [
        PaperEventResponse(
            id=event.id,
            event_type=event.event_type,
            severity=event.severity,
            symbol=event.symbol,
            message=event.message,
            payload=event.payload,
            created_at=event.created_at,
        )
        for event in events
    ]


@router.post("/engine/start", response_model=EngineStatusResponse)
async def start_engine(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> EngineStatusResponse:
    portfolio = _get_portfolio(db, current_user)
    portfolio.engine_running = True
    record_event(
        db,
        portfolio_id=portfolio.id,
        event_type=ev.EVENT_ENGINE_STARTED,
        message="Engine de paper trading iniciado (modo semi-automático).",
        broadcast=hub,
    )
    db.commit()
    runtime = await registry.start(portfolio.id, settings)
    return EngineStatusResponse(
        **runtime.engine.status(
            db, portfolio, tracked_symbols=runtime.tracked_symbols
        ).__dict__
    )


@router.post("/engine/stop", response_model=EngineStatusResponse)
async def stop_engine(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> EngineStatusResponse:
    portfolio = _get_portfolio(db, current_user)
    portfolio.engine_running = False
    record_event(
        db,
        portfolio_id=portfolio.id,
        event_type=ev.EVENT_ENGINE_STOPPED,
        message="Engine de paper trading parado.",
        broadcast=hub,
    )
    db.commit()
    await registry.stop(portfolio.id)
    engine = _engine_for(portfolio)
    return EngineStatusResponse(**engine.status(db, portfolio, tracked_symbols=[]).__dict__)


@router.get("/engine/status", response_model=EngineStatusResponse)
def engine_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> EngineStatusResponse:
    portfolio = _get_portfolio(db, current_user)
    runtime = registry.get(portfolio.id)
    engine = _engine_for(portfolio)
    tracked = runtime.tracked_symbols if runtime is not None else []
    return EngineStatusResponse(
        **engine.status(db, portfolio, tracked_symbols=tracked).__dict__
    )


@router.post("/engine/kill-switch/reset", response_model=EngineStatusResponse)
def reset_kill_switch(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> EngineStatusResponse:
    portfolio = _get_portfolio(db, current_user)
    if not portfolio.kill_switch_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Kill switch is not active."
        )
    engine = _engine_for(portfolio)
    engine.reset_kill_switch(db, portfolio)
    db.commit()
    runtime = registry.get(portfolio.id)
    tracked = runtime.tracked_symbols if runtime is not None else []
    return EngineStatusResponse(
        **engine.status(db, portfolio, tracked_symbols=tracked).__dict__
    )
