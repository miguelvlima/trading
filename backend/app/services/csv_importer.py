import csv
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models import Instrument, MarketBar


@dataclass
class CsvImportResult:
    symbol: str
    timeframe: str
    imported_rows: int


def _parse_timestamp(raw_value: str) -> datetime:
    value = raw_value.strip()
    if not value:
        raise ValueError("timestamp column is empty")

    if value.endswith("Z"):
        value = value.replace("Z", "+00:00")

    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _get_instrument(
    session: Session,
    symbol: str,
    instrument_name: str | None,
    exchange: str | None,
    currency: str,
) -> Instrument:
    instrument = session.execute(
        select(Instrument).where(Instrument.symbol == symbol)
    ).scalar_one_or_none()
    if instrument:
        return instrument

    instrument = Instrument(
        symbol=symbol,
        name=instrument_name,
        exchange=exchange,
        currency=currency,
    )
    session.add(instrument)
    session.flush()
    return instrument


def parse_ohlcv_csv_rows(csv_path: str) -> list[dict[str, Decimal | datetime]]:
    path = Path(csv_path)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    parsed_rows: list[dict[str, Decimal | datetime]] = []
    with path.open(mode="r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        required_columns = {"timestamp", "open", "high", "low", "close", "volume"}
        if reader.fieldnames is None:
            raise ValueError("CSV is missing header row")
        missing = required_columns.difference(
            {name.strip().lower() for name in reader.fieldnames}
        )
        if missing:
            missing_text = ", ".join(sorted(missing))
            raise ValueError(f"CSV missing required columns: {missing_text}")

        for row in reader:
            parsed_rows.append(
                {
                    "timestamp": _parse_timestamp(row["timestamp"]),
                    "open": Decimal(row["open"]),
                    "high": Decimal(row["high"]),
                    "low": Decimal(row["low"]),
                    "close": Decimal(row["close"]),
                    "volume": Decimal(row["volume"]),
                }
            )

    return parsed_rows


def import_ohlcv_csv(
    session: Session,
    *,
    csv_path: str,
    symbol: str,
    timeframe: str,
    instrument_name: str | None = None,
    exchange: str | None = None,
    currency: str = "USD",
) -> CsvImportResult:
    instrument = _get_instrument(
        session=session,
        symbol=symbol.upper().strip(),
        instrument_name=instrument_name,
        exchange=exchange,
        currency=currency.upper().strip(),
    )

    parsed_rows = parse_ohlcv_csv_rows(csv_path)
    rows_to_insert: list[dict[str, object]] = []
    now_utc = datetime.now(UTC)
    for row in parsed_rows:
        rows_to_insert.append(
            {
                "instrument_id": instrument.id,
                "timeframe": timeframe,
                "timestamp": row["timestamp"],
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
                "created_at": now_utc,
            }
        )

    if not rows_to_insert:
        return CsvImportResult(symbol=instrument.symbol, timeframe=timeframe, imported_rows=0)

    insert_stmt = pg_insert(MarketBar).values(rows_to_insert)
    upsert_stmt = insert_stmt.on_conflict_do_update(
        constraint="uq_market_bars_instrument_timeframe_timestamp",
        set_={
            "open": insert_stmt.excluded.open,
            "high": insert_stmt.excluded.high,
            "low": insert_stmt.excluded.low,
            "close": insert_stmt.excluded.close,
            "volume": insert_stmt.excluded.volume,
        },
    )
    result = session.execute(upsert_stmt)
    session.commit()

    inserted_count = len(rows_to_insert)
    return CsvImportResult(
        symbol=instrument.symbol,
        timeframe=timeframe,
        imported_rows=inserted_count,
    )
