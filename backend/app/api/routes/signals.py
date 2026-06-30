from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user
from app.db.dependencies import get_db_session
from app.db.models import Instrument, MarketBar, Signal, User
from app.schemas.signals import (
    SignalBarInput,
    SignalFormingBarInput,
    SignalGenerateRequest,
    SignalLiveEvaluateRequest,
    SignalLiveEvaluateResponse,
    SignalResponse,
    SignalsGenerateResponse,
)
from app.services.strategy_engine import BarInput, get_available_strategies, run_strategy

router = APIRouter(prefix="/signals", tags=["signals"])

SIGNAL_SOURCE_HISTORICAL = "historical"
SIGNAL_SOURCE_LIVE = "live"


def _bar_input_from_schema(item: SignalBarInput | SignalFormingBarInput) -> BarInput:
    return BarInput(
        timestamp=item.timestamp,
        open=item.open,
        high=item.high,
        low=item.low,
        close=item.close,
        volume=item.volume,
    )


def _load_db_strategy_bars(
    db: Session,
    *,
    instrument_id: int,
    timeframe: str,
    start: datetime | None,
    end: datetime | None,
    limit: int,
) -> list[BarInput]:
    query = select(MarketBar).where(
        MarketBar.instrument_id == instrument_id,
        MarketBar.timeframe == timeframe,
    )
    if start is not None:
        query = query.where(MarketBar.timestamp >= start)
    if end is not None:
        query = query.where(MarketBar.timestamp <= end)
    rows = db.execute(query.order_by(MarketBar.timestamp.desc()).limit(limit)).scalars().all()
    return [
        BarInput(
            timestamp=bar.timestamp,
            open=float(bar.open),
            high=float(bar.high),
            low=float(bar.low),
            close=float(bar.close),
            volume=float(bar.volume),
        )
        for bar in reversed(rows)
    ]


def _normalize_ts(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _apply_forming_bar(
    strategy_bars: list[BarInput],
    forming: SignalFormingBarInput,
) -> tuple[list[BarInput], bool]:
    forming_bar = _bar_input_from_schema(forming)
    forming_bar = BarInput(
        timestamp=_normalize_ts(forming_bar.timestamp),
        open=forming_bar.open,
        high=forming_bar.high,
        low=forming_bar.low,
        close=forming_bar.close,
        volume=forming_bar.volume,
    )
    if not strategy_bars:
        return [forming_bar], True

    last = strategy_bars[-1]
    last_ts = _normalize_ts(last.timestamp)
    if forming_bar.timestamp == last_ts:
        return strategy_bars[:-1] + [forming_bar], True
    if forming_bar.timestamp > last_ts:
        return strategy_bars + [forming_bar], True
    return strategy_bars, False


def _to_signal_response(signal: Signal) -> SignalResponse:
    return SignalResponse(
        id=signal.id,
        symbol=signal.symbol,
        timeframe=signal.timeframe,
        strategy=signal.strategy,
        direction=signal.direction,
        strength=float(signal.strength),
        rationale=signal.rationale,
        timestamp=signal.timestamp,
        indicator_snapshot=signal.indicator_snapshot,
        source=signal.source,
    )


@router.get("/strategies", response_model=list[str])
def list_strategies(_: User = Depends(get_current_user)) -> list[str]:
    return get_available_strategies()


@router.get("", response_model=list[SignalResponse])
def list_signals(
    symbol: str | None = Query(default=None, min_length=1, max_length=32),
    timeframe: str | None = Query(default=None, min_length=1, max_length=16),
    strategy: str | None = Query(default=None, min_length=1, max_length=64),
    direction: Literal["BUY", "SELL"] | None = Query(default=None),
    source: Literal["historical", "live"] | None = Query(default=None),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    min_strength: float = Query(default=0.0, ge=0.0, le=1.0),
    limit: int = Query(default=200, ge=1, le=2000),
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> list[SignalResponse]:
    query = select(Signal).where(Signal.user_id == current_user.id)
    if symbol:
        query = query.where(Signal.symbol == symbol.upper().strip())
    if timeframe:
        query = query.where(Signal.timeframe == timeframe)
    if strategy:
        query = query.where(Signal.strategy == strategy)
    if direction:
        query = query.where(Signal.direction == direction)
    if source:
        query = query.where(Signal.source == source)
    if start is not None:
        query = query.where(Signal.timestamp >= start)
    if end is not None:
        query = query.where(Signal.timestamp <= end)
    if min_strength > 0:
        query = query.where(Signal.strength >= Decimal(f"{min_strength:.5f}"))

    signals = db.execute(query.order_by(Signal.timestamp.desc()).limit(limit)).scalars().all()
    return [_to_signal_response(signal) for signal in signals]


@router.post(
    "/evaluate-live",
    response_model=SignalLiveEvaluateResponse,
    status_code=status.HTTP_200_OK,
)
def evaluate_live_signals(
    payload: SignalLiveEvaluateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> SignalLiveEvaluateResponse:
    symbol = payload.symbol.upper().strip()
    strategies = sorted({name.strip() for name in payload.strategies if name.strip()})
    if not strategies:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one strategy is required.")

    available = set(get_available_strategies())
    invalid = sorted(name for name in strategies if name not in available)
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown strategies: {', '.join(invalid)}",
        )

    instrument = db.execute(select(Instrument).where(Instrument.symbol == symbol)).scalar_one_or_none()
    if instrument is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Instrument not found: {symbol}")

    if payload.context_bars:
        strategy_bars = [_bar_input_from_schema(item) for item in payload.context_bars]
        strategy_bars.sort(key=lambda bar: bar.timestamp)
    else:
        strategy_bars = _load_db_strategy_bars(
            db,
            instrument_id=instrument.id,
            timeframe=payload.timeframe,
            start=payload.start,
            end=payload.end,
            limit=payload.limit,
        )

    is_forming_bar = False
    if payload.forming_bar is not None:
        strategy_bars, is_forming_bar = _apply_forming_bar(strategy_bars, payload.forming_bar)

    if not strategy_bars:
        return SignalLiveEvaluateResponse(
            symbol=symbol,
            timeframe=payload.timeframe,
            evaluated_at=datetime.now(UTC),
            bar_timestamp=None,
            is_forming_bar=False,
            signals=[],
        )

    evaluation_bar_ts = strategy_bars[-1].timestamp
    evaluated_at = datetime.now(UTC)
    live_signals: list[SignalResponse] = []

    for strategy_name in strategies:
        try:
            generated = run_strategy(strategy_name, symbol=symbol, bars=strategy_bars)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        latest_on_bar = [item for item in generated if _normalize_ts(item.timestamp) == _normalize_ts(evaluation_bar_ts)]
        if not latest_on_bar:
            continue

        item = max(latest_on_bar, key=lambda signal: signal.strength)
        if item.strength < payload.min_strength:
            continue

        rationale = item.rationale
        if is_forming_bar:
            rationale = f"{rationale} (vela em formação)"

        if payload.persist:
            db.execute(
                delete(Signal).where(
                    Signal.user_id == current_user.id,
                    Signal.symbol == symbol,
                    Signal.timeframe == payload.timeframe,
                    Signal.strategy == strategy_name,
                    Signal.source == SIGNAL_SOURCE_LIVE,
                )
            )
            model = Signal(
                user_id=current_user.id,
                instrument_id=instrument.id,
                symbol=symbol,
                timeframe=payload.timeframe,
                strategy=strategy_name,
                direction=item.direction,
                strength=Decimal(f"{item.strength:.5f}"),
                rationale=rationale[:512],
                timestamp=item.timestamp,
                indicator_snapshot=item.indicator_snapshot,
                source=SIGNAL_SOURCE_LIVE,
            )
            db.add(model)
            db.flush()
            live_signals.append(_to_signal_response(model))
        else:
            live_signals.append(
                SignalResponse(
                    id=0,
                    symbol=symbol,
                    timeframe=payload.timeframe,
                    strategy=strategy_name,
                    direction=item.direction,
                    strength=item.strength,
                    rationale=rationale,
                    timestamp=item.timestamp,
                    indicator_snapshot=item.indicator_snapshot,
                    source=SIGNAL_SOURCE_LIVE,
                )
            )

    if payload.persist:
        db.commit()

    return SignalLiveEvaluateResponse(
        symbol=symbol,
        timeframe=payload.timeframe,
        evaluated_at=evaluated_at,
        bar_timestamp=evaluation_bar_ts,
        is_forming_bar=is_forming_bar,
        signals=live_signals,
    )


@router.post(
    "/generate",
    response_model=SignalsGenerateResponse,
    status_code=status.HTTP_201_CREATED,
)
def generate_signals(
    payload: SignalGenerateRequest,
    current_user: User = Depends(get_current_user),
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
            Signal.user_id == current_user.id,
            Signal.symbol == symbol,
            Signal.timeframe == payload.timeframe,
            Signal.strategy == payload.strategy,
            Signal.source == SIGNAL_SOURCE_HISTORICAL,
        )
    )

    inserted_signals: list[Signal] = []
    for item in generated:
        model = Signal(
            user_id=current_user.id,
            instrument_id=instrument.id,
            symbol=symbol,
            timeframe=payload.timeframe,
            strategy=payload.strategy,
            direction=item.direction,
            strength=Decimal(f"{item.strength:.5f}"),
            rationale=item.rationale,
            timestamp=item.timestamp,
            indicator_snapshot=item.indicator_snapshot,
            source=SIGNAL_SOURCE_HISTORICAL,
        )
        db.add(model)
        inserted_signals.append(model)

    db.commit()
    for signal in inserted_signals:
        db.refresh(signal)

    response_signals = [_to_signal_response(signal) for signal in inserted_signals]
    return SignalsGenerateResponse(
        strategy=payload.strategy,
        symbol=symbol,
        timeframe=payload.timeframe,
        generated_count=len(response_signals),
        signals=response_signals,
    )
