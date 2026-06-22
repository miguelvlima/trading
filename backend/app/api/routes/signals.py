from datetime import datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.dependencies import get_db_session
from app.db.models import Instrument, MarketBar, Signal
from app.schemas.signals import SignalGenerateRequest, SignalResponse, SignalsGenerateResponse
from app.services.strategy_engine import BarInput, get_available_strategies, run_strategy

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("/strategies", response_model=list[str])
def list_strategies() -> list[str]:
    return get_available_strategies()


@router.get("", response_model=list[SignalResponse])
def list_signals(
    symbol: str | None = Query(default=None, min_length=1, max_length=32),
    timeframe: str | None = Query(default=None, min_length=1, max_length=16),
    strategy: str | None = Query(default=None, min_length=1, max_length=64),
    direction: Literal["BUY", "SELL"] | None = Query(default=None),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    min_strength: float = Query(default=0.0, ge=0.0, le=1.0),
    limit: int = Query(default=200, ge=1, le=2000),
    db: Session = Depends(get_db_session),
) -> list[SignalResponse]:
    query = select(Signal)
    if symbol:
        query = query.where(Signal.symbol == symbol.upper().strip())
    if timeframe:
        query = query.where(Signal.timeframe == timeframe)
    if strategy:
        query = query.where(Signal.strategy == strategy)
    if direction:
        query = query.where(Signal.direction == direction)
    if start is not None:
        query = query.where(Signal.timestamp >= start)
    if end is not None:
        query = query.where(Signal.timestamp <= end)
    if min_strength > 0:
        query = query.where(Signal.strength >= Decimal(f"{min_strength:.5f}"))

    signals = db.execute(query.order_by(Signal.timestamp.desc()).limit(limit)).scalars().all()
    return [
        SignalResponse(
            id=signal.id,
            symbol=signal.symbol,
            timeframe=signal.timeframe,
            strategy=signal.strategy,
            direction=signal.direction,
            strength=float(signal.strength),
            rationale=signal.rationale,
            timestamp=signal.timestamp,
            indicator_snapshot=signal.indicator_snapshot,
        )
        for signal in signals
    ]


@router.post(
    "/generate",
    response_model=SignalsGenerateResponse,
    status_code=status.HTTP_201_CREATED,
)
def generate_signals(
    payload: SignalGenerateRequest,
    db: Session = Depends(get_db_session),
) -> SignalsGenerateResponse:
    symbol = payload.symbol.upper().strip()
    instrument = db.execute(select(Instrument).where(Instrument.symbol == symbol)).scalar_one_or_none()
    if instrument is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Instrument not found: {symbol}")

    query = select(MarketBar).where(
        MarketBar.instrument_id == instrument.id,
        MarketBar.timeframe == payload.timeframe,
    )
    if payload.start is not None:
        query = query.where(MarketBar.timestamp >= payload.start)
    if payload.end is not None:
        query = query.where(MarketBar.timestamp <= payload.end)

    bars = db.execute(query.order_by(MarketBar.timestamp.asc()).limit(payload.limit)).scalars().all()
    if not bars:
        return SignalsGenerateResponse(
            strategy=payload.strategy,
            symbol=symbol,
            timeframe=payload.timeframe,
            generated_count=0,
            signals=[],
        )

    strategy_bars = [
        BarInput(
            timestamp=bar.timestamp,
            open=float(bar.open),
            high=float(bar.high),
            low=float(bar.low),
            close=float(bar.close),
            volume=float(bar.volume),
        )
        for bar in bars
    ]
    try:
        generated = run_strategy(payload.strategy, symbol=symbol, bars=strategy_bars)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    db.execute(
        delete(Signal).where(
            Signal.symbol == symbol,
            Signal.timeframe == payload.timeframe,
            Signal.strategy == payload.strategy,
        )
    )

    inserted_signals: list[Signal] = []
    for item in generated:
        model = Signal(
            instrument_id=instrument.id,
            symbol=symbol,
            timeframe=payload.timeframe,
            strategy=payload.strategy,
            direction=item.direction,
            strength=Decimal(f"{item.strength:.5f}"),
            rationale=item.rationale,
            timestamp=item.timestamp,
            indicator_snapshot=item.indicator_snapshot,
        )
        db.add(model)
        inserted_signals.append(model)

    db.commit()
    for signal in inserted_signals:
        db.refresh(signal)

    response_signals = [
        SignalResponse(
            id=signal.id,
            symbol=signal.symbol,
            timeframe=signal.timeframe,
            strategy=signal.strategy,
            direction=signal.direction,
            strength=float(signal.strength),
            rationale=signal.rationale,
            timestamp=signal.timestamp,
            indicator_snapshot=signal.indicator_snapshot,
        )
        for signal in inserted_signals
    ]
    return SignalsGenerateResponse(
        strategy=payload.strategy,
        symbol=symbol,
        timeframe=payload.timeframe,
        generated_count=len(response_signals),
        signals=response_signals,
    )
