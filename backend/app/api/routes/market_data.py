from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user
from app.db.dependencies import get_db_session
from app.db.models import Instrument, MarketBar, User
from app.schemas.market_data import (
    CsvImportRequest,
    CsvImportResponse,
    IndicatorResponse,
    IndicatorRowResponse,
    InstrumentResponse,
    MarketBarResponse,
)
from app.services.csv_importer import import_ohlcv_csv
from app.services.indicator_engine import (
    atr,
    bollinger_bands,
    ema,
    macd,
    relative_volume,
    rsi,
    sma,
    vwap,
)

router = APIRouter(prefix="/market-data", tags=["market-data"])


@router.get("/instruments", response_model=list[InstrumentResponse])
def list_instruments(
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> list[InstrumentResponse]:
    instruments = db.execute(select(Instrument).order_by(Instrument.symbol.asc())).scalars().all()
    return [InstrumentResponse.model_validate(item, from_attributes=True) for item in instruments]


@router.get("/bars", response_model=list[MarketBarResponse])
def list_market_bars(
    symbol: str = Query(min_length=1, max_length=32),
    timeframe: str = Query(default="1d", min_length=1, max_length=16),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=5000),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> list[MarketBarResponse]:
    instrument = db.execute(
        select(Instrument).where(Instrument.symbol == symbol.upper().strip())
    ).scalar_one_or_none()
    if instrument is None:
        return []

    query: Select[tuple[MarketBar]] = select(MarketBar).where(
        MarketBar.instrument_id == instrument.id,
        MarketBar.timeframe == timeframe,
    )
    if start is not None:
        query = query.where(MarketBar.timestamp >= start)
    if end is not None:
        query = query.where(MarketBar.timestamp <= end)

    bars = db.execute(query.order_by(MarketBar.timestamp.asc()).limit(limit)).scalars().all()
    return [MarketBarResponse.model_validate(item, from_attributes=True) for item in bars]


@router.get("/indicators", response_model=IndicatorResponse)
def get_indicators(
    symbol: str = Query(min_length=1, max_length=32),
    timeframe: str = Query(default="1d", min_length=1, max_length=16),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=5000),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> IndicatorResponse:
    instrument = db.execute(
        select(Instrument).where(Instrument.symbol == symbol.upper().strip())
    ).scalar_one_or_none()
    if instrument is None:
        return IndicatorResponse(symbol=symbol.upper().strip(), timeframe=timeframe, rows=[])

    query: Select[tuple[MarketBar]] = select(MarketBar).where(
        MarketBar.instrument_id == instrument.id,
        MarketBar.timeframe == timeframe,
    )
    if start is not None:
        query = query.where(MarketBar.timestamp >= start)
    if end is not None:
        query = query.where(MarketBar.timestamp <= end)

    bars = db.execute(query.order_by(MarketBar.timestamp.asc()).limit(limit)).scalars().all()
    if not bars:
        return IndicatorResponse(symbol=instrument.symbol, timeframe=timeframe, rows=[])

    close_values = [float(bar.close) for bar in bars]
    high_values = [float(bar.high) for bar in bars]
    low_values = [float(bar.low) for bar in bars]
    volume_values = [float(bar.volume) for bar in bars]

    sma_20 = sma(close_values, 20)
    ema_20 = ema(close_values, 20)
    rsi_14 = rsi(close_values, 14)
    macd_line, macd_signal_line, macd_histogram = macd(close_values, 12, 26, 9)
    bb_upper, bb_middle, bb_lower = bollinger_bands(close_values, 20, 2.0)
    atr_14 = atr(high_values, low_values, close_values, 14)
    vwap_values = vwap(high_values, low_values, close_values, volume_values)
    relative_volume_20 = relative_volume(volume_values, 20)

    rows: list[IndicatorRowResponse] = []
    for index, bar in enumerate(bars):
        rows.append(
            IndicatorRowResponse(
                timestamp=bar.timestamp,
                sma_20=sma_20[index],
                ema_20=ema_20[index],
                rsi_14=rsi_14[index],
                macd=macd_line[index],
                macd_signal=macd_signal_line[index],
                macd_histogram=macd_histogram[index],
                bollinger_upper=bb_upper[index],
                bollinger_middle=bb_middle[index],
                bollinger_lower=bb_lower[index],
                atr_14=atr_14[index],
                vwap=vwap_values[index],
                relative_volume_20=relative_volume_20[index],
            )
        )

    return IndicatorResponse(symbol=instrument.symbol, timeframe=timeframe, rows=rows)


@router.post(
    "/import-csv",
    response_model=CsvImportResponse,
    status_code=status.HTTP_201_CREATED,
)
def import_market_data_csv(
    payload: CsvImportRequest,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> CsvImportResponse:
    try:
        result = import_ohlcv_csv(
            db,
            csv_path=payload.csv_path,
            symbol=payload.symbol,
            timeframe=payload.timeframe,
            instrument_name=payload.instrument_name,
            exchange=payload.exchange,
            currency=payload.currency,
        )
        return CsvImportResponse(
            symbol=result.symbol,
            timeframe=result.timeframe,
            imported_rows=result.imported_rows,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
