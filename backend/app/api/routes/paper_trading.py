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
    PaperEquityPoint,
    PaperOrder,
    PaperPortfolio,
    PaperPosition,
    PaperTrade,
    User,
)
from app.schemas.paper_trading import (
    EngineStatusResponse,
    PaperEquityPointResponse,
    PaperEventResponse,
    PaperOrderResponse,
    PaperPnlResponse,
    PaperPortfolioCreateRequest,
    PaperPortfolioResponse,
    PaperPositionResponse,
    PaperSignalResponse,
    PaperTradeResponse,
    RiskSettingsUpdateRequest,
)
from app.services.paper_trading import events as ev
from app.services.paper_trading.engine import PaperEngine
from app.services.paper_trading.events import hub, record_event
from app.services.paper_trading.quotes import QuoteCache
from app.services.paper_trading.runtime import registry
from app.services.paper_trading.types import (
    OPEN_STATUSES,
    STATUS_APPROVED,
    STATUS_PROPOSED,
    RiskSettings,
)

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
        event_type=ev.EVENT_PORTFOLIO_CREATED,
        message=f"Portfolio paper criado com ${payload.initial_cash:,.2f}.",
        broadcast=hub,
    )
    db.add(
        PaperEquityPoint(
            portfolio_id=portfolio.id,
            equity=payload.initial_cash,
            cash=payload.initial_cash,
        )
    )
    db.commit()
    db.refresh(portfolio)
    return _portfolio_response(portfolio)


@router.post("/portfolio/reset", response_model=PaperPortfolioResponse)
async def reset_portfolio(
    payload: PaperPortfolioCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> PaperPortfolioResponse:
    """Wipe orders/positions/trades and restart the portfolio with new cash.

    The ledger is kept: the reset itself becomes an auditable event on top of
    the old history instead of silently erasing it.
    """
    portfolio = _get_portfolio(db, current_user)
    await registry.stop(portfolio.id)

    for model in (PaperOrder, PaperTrade, PaperPosition, PaperEquityPoint):
        for row in db.execute(
            select(model).where(model.portfolio_id == portfolio.id)
        ).scalars():
            db.delete(row)

    portfolio.initial_cash = payload.initial_cash
    portfolio.cash = payload.initial_cash
    portfolio.equity = payload.initial_cash
    portfolio.engine_running = False
    portfolio.kill_switch_active = False
    portfolio.kill_switch_reason = None
    if payload.risk_settings is not None:
        portfolio.risk_settings = RiskSettings.from_json(payload.risk_settings).to_json()

    record_event(
        db,
        portfolio_id=portfolio.id,
        event_type=ev.EVENT_PORTFOLIO_RESET,
        message=f"Portfolio paper reiniciado com ${payload.initial_cash:,.2f}.",
        broadcast=hub,
    )
    db.add(
        PaperEquityPoint(
            portfolio_id=portfolio.id,
            equity=payload.initial_cash,
            cash=payload.initial_cash,
        )
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
    if payload.preset == "day_trading":
        preset = RiskSettings.day_trading_defaults()
        for name in RiskSettings.DAY_TRADING_PRESET_FIELDS:
            merged[name] = getattr(preset, name)
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


@router.post("/orders/{order_id}/cancel", response_model=PaperOrderResponse)
def cancel_order(
    order_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> PaperOrderResponse:
    """Cancel an approved order still waiting for a credible quote to fill."""
    portfolio = _get_portfolio(db, current_user)
    order = db.execute(
        select(PaperOrder).where(
            PaperOrder.id == order_id, PaperOrder.portfolio_id == portfolio.id
        )
    ).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")
    if order.status != STATUS_APPROVED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Order is '{order.status}', only 'approved' orders can be cancelled.",
        )
    engine = _engine_for(portfolio)
    engine.cancel_order(db, portfolio, order)
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

    engine = _engine_for(portfolio)
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
        provenance = engine.position_provenance(db, pos)
        responses.append(
            PaperPositionResponse(
                symbol=pos.symbol,
                quantity=float(pos.quantity),
                avg_entry_price=float(pos.avg_entry_price),
                realized_pnl=float(pos.realized_pnl),
                last_price=last_price,
                unrealized_pnl=unrealized,
                opened_at=provenance["opened_at"],
                strategy=provenance["strategy"],
                rationale=provenance["rationale"],
                stop_price=provenance["stop_price"],
                take_profit_price=provenance["take_profit_price"],
                updated_at=pos.updated_at,
            )
        )
    return responses


@router.get("/equity", response_model=list[PaperEquityPointResponse])
def equity_history(
    limit: int = Query(default=2000, ge=1, le=10000),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> list[PaperEquityPointResponse]:
    """Persisted equity snapshots, oldest first — seeds the cockpit curve."""
    portfolio = _get_portfolio(db, current_user)
    points = list(
        db.execute(
            select(PaperEquityPoint)
            .where(PaperEquityPoint.portfolio_id == portfolio.id)
            .order_by(PaperEquityPoint.at.desc())
            .limit(limit)
        ).scalars()
    )
    return [
        PaperEquityPointResponse(at=p.at, equity=float(p.equity), cash=float(p.cash))
        for p in reversed(points)
    ]


@router.post("/positions/{symbol}/close", response_model=PaperOrderResponse)
def close_position(
    symbol: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> PaperOrderResponse:
    """Manually sell the whole open position for ``symbol`` at market."""
    portfolio = _get_portfolio(db, current_user)
    symbol = symbol.upper()
    position = db.execute(
        select(PaperPosition).where(
            PaperPosition.portfolio_id == portfolio.id,
            PaperPosition.symbol == symbol,
            PaperPosition.quantity > 0,
        )
    ).scalar_one_or_none()
    if position is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sem posição aberta em {symbol}.",
        )
    open_order = db.execute(
        select(PaperOrder).where(
            PaperOrder.portfolio_id == portfolio.id,
            PaperOrder.symbol == symbol,
            PaperOrder.status.in_(OPEN_STATUSES),
        )
    ).scalar_one_or_none()
    if open_order is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Já existe uma ordem aberta (#{open_order.id}) para {symbol} — "
            "decide-a ou espera pelo fill antes de fechar manualmente.",
        )
    engine = _engine_for(portfolio)
    order, _trade, _deferral = engine.manual_close(db, portfolio, position)
    db.commit()
    db.refresh(order)
    return _order_response(order)


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


def _signal_response(event: PaperEngineEvent) -> PaperSignalResponse:
    """Map a signal_received event to the cockpit's signal-history row.

    Old rows may predate the enriched payload, so every field degrades
    gracefully (outcome "unknown", missing strength as None).
    """
    payload = event.payload or {}

    def _num(key: str) -> float | None:
        value = payload.get(key)
        return float(value) if isinstance(value, (int, float)) else None

    def _text(key: str) -> str | None:
        value = payload.get(key)
        return str(value) if value else None

    order_id = payload.get("order_id")
    return PaperSignalResponse(
        id=event.id,
        at=event.created_at,
        symbol=event.symbol or "",
        strategy=_text("strategy") or "?",
        direction=_text("direction") or "?",
        strength=_num("strength"),
        min_strength=_num("min_strength"),
        rationale=_text("rationale"),
        bar_time=_text("signal_timestamp"),
        outcome=_text("outcome") or "unknown",
        reason=_text("reason"),
        order_id=order_id if isinstance(order_id, int) else None,
    )


@router.get("/signals", response_model=list[PaperSignalResponse])
def list_signals(
    symbol: str | None = Query(default=None, min_length=1, max_length=32),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> list[PaperSignalResponse]:
    """Signal history, newest first — every signal the engine saw, including
    the weak ones it never turned into a proposal."""
    portfolio = _get_portfolio(db, current_user)
    query = select(PaperEngineEvent).where(
        PaperEngineEvent.portfolio_id == portfolio.id,
        PaperEngineEvent.event_type == ev.EVENT_SIGNAL_RECEIVED,
    )
    if symbol:
        query = query.where(PaperEngineEvent.symbol == symbol.upper().strip())
    events = db.execute(query.order_by(PaperEngineEvent.id.desc()).limit(limit)).scalars()
    return [_signal_response(event) for event in events]


@router.post("/engine/start", response_model=EngineStatusResponse)
async def start_engine(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> EngineStatusResponse:
    portfolio = _get_portfolio(db, current_user)
    # Idempotent: repeated clicks must not spam the ledger with duplicates.
    if not portfolio.engine_running:
        portfolio.engine_running = True
        mode = (
            "automático"
            if RiskSettings.from_json(portfolio.risk_settings).auto_approve
            else "semi-automático"
        )
        record_event(
            db,
            portfolio_id=portfolio.id,
            event_type=ev.EVENT_ENGINE_STARTED,
            message=f"Engine de paper trading iniciado (modo {mode}).",
            broadcast=hub,
        )
        db.commit()
    runtime = await registry.start(portfolio.id, settings)
    return EngineStatusResponse(
        **runtime.engine.status(
            db,
            portfolio,
            tracked_symbols=runtime.tracked_symbols,
            has_provider=runtime.has_provider,
        ).__dict__,
        last_evaluation=runtime.last_evaluation,
        poll_seconds=runtime.poll_seconds,
        last_signals=runtime.last_signals,
    )


@router.post("/engine/stop", response_model=EngineStatusResponse)
async def stop_engine(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> EngineStatusResponse:
    portfolio = _get_portfolio(db, current_user)
    # Idempotent: only record the transition once, even if the runtime is gone.
    if portfolio.engine_running:
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
    settings: Settings = Depends(get_settings),
) -> EngineStatusResponse:
    portfolio = _get_portfolio(db, current_user)
    runtime = registry.get(portfolio.id)
    engine = _engine_for(portfolio)
    if runtime is not None:
        tracked = runtime.tracked_symbols
    else:
        # Engine stopped: still show WHAT would be tracked, so the cockpit can
        # display the symbol list at all times.
        from app.services.paper_trading.runtime import compute_tracked_symbols

        risk = RiskSettings.from_json(portfolio.risk_settings)
        tracked = compute_tracked_symbols(db, risk, settings, portfolio.id)
    return EngineStatusResponse(
        **engine.status(
            db,
            portfolio,
            tracked_symbols=tracked,
            has_provider=runtime.has_provider if runtime is not None else False,
        ).__dict__,
        last_evaluation=runtime.last_evaluation if runtime is not None else None,
        poll_seconds=runtime.poll_seconds if runtime is not None else None,
        last_signals=runtime.last_signals if runtime is not None else None,
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
