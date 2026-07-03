from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Instrument, MarketBar

BACKTEST_MIN_BARS = 200


def count_market_bars(db: Session, *, symbol: str, timeframe: str) -> int:
    instrument = db.execute(
        select(Instrument.id).where(Instrument.symbol == symbol.upper().strip())
    ).scalar_one_or_none()
    if instrument is None:
        return 0
    count = db.execute(
        select(func.count())
        .select_from(MarketBar)
        .where(
            MarketBar.instrument_id == instrument,
            MarketBar.timeframe == timeframe,
        )
    ).scalar_one()
    return int(count or 0)


def bar_counts_for_timeframes(
    db: Session,
    *,
    symbol: str,
    timeframes: list[str],
) -> dict[str, int]:
    return {timeframe: count_market_bars(db, symbol=symbol, timeframe=timeframe) for timeframe in timeframes}


def is_timeframe_viable(
    bar_counts: dict[str, int],
    timeframe: str,
    *,
    min_bars: int = BACKTEST_MIN_BARS,
) -> bool:
    return bar_counts.get(timeframe, 0) >= min_bars
