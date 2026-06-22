from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.db.dependencies import get_db_session
from app.db.models import Instrument, MarketBar
from app.schemas.market_data import (
    CsvImportRequest,
    CsvImportResponse,
    InstrumentResponse,
    MarketBarResponse,
)
from app.services.csv_importer import import_ohlcv_csv

router = APIRouter(prefix="/market-data", tags=["market-data"])


@router.get("/instruments", response_model=list[InstrumentResponse])
def list_instruments(db: Session = Depends(get_db_session)) -> list[InstrumentResponse]:
    instruments = db.execute(select(Instrument).order_by(Instrument.symbol.asc())).scalars().all()
    return [InstrumentResponse.model_validate(item, from_attributes=True) for item in instruments]


@router.get("/bars", response_model=list[MarketBarResponse])
def list_market_bars(
    symbol: str = Query(min_length=1, max_length=32),
    timeframe: str = Query(default="1d", min_length=1, max_length=16),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=5000),
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


@router.post(
    "/import-csv",
    response_model=CsvImportResponse,
    status_code=status.HTTP_201_CREATED,
)
def import_market_data_csv(
    payload: CsvImportRequest,
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
