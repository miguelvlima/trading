from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.db.models import Instrument, MarketBar
from app.db.session import SessionLocal


def _to_decimal(value: float) -> Decimal:
    return Decimal(f"{value:.6f}")


def _generate_daily_bars(base_price: float, days: int) -> list[tuple[datetime, float, float, float, float, float]]:
    start = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days)
    rows: list[tuple[datetime, float, float, float, float, float]] = []

    price = base_price
    for day in range(days):
        timestamp = start + timedelta(days=day)
        drift = ((day % 11) - 5) * 0.35
        open_price = price
        close_price = max(5.0, open_price + drift)
        high_price = max(open_price, close_price) + 1.8 + (day % 3) * 0.2
        low_price = min(open_price, close_price) - 1.7 - (day % 2) * 0.15
        volume = 1_000_000 + (day % 25) * 27_000

        rows.append((timestamp, open_price, high_price, low_price, close_price, float(volume)))
        price = close_price

    return rows


def _aggregate_weekly(
    daily_rows: list[tuple[datetime, float, float, float, float, float]]
) -> list[tuple[datetime, float, float, float, float, float]]:
    weekly: list[tuple[datetime, float, float, float, float, float]] = []
    for index in range(0, len(daily_rows), 7):
        chunk = daily_rows[index : index + 7]
        if not chunk:
            continue
        timestamp = chunk[-1][0]
        open_price = chunk[0][1]
        close_price = chunk[-1][4]
        high_price = max(item[2] for item in chunk)
        low_price = min(item[3] for item in chunk)
        volume = sum(item[5] for item in chunk)
        weekly.append((timestamp, open_price, high_price, low_price, close_price, volume))
    return weekly


def main() -> None:
    symbols = [
        ("AAPL", 190.0),
        ("MSFT", 410.0),
        ("NVDA", 120.0),
        ("TSLA", 185.0),
        ("SPY", 530.0),
        ("QQQ", 460.0),
    ]

    with SessionLocal() as session:
        instrument_count = session.execute(select(Instrument.id).limit(1)).first()
        if instrument_count is not None:
            print("Seed skipped: database already contains instruments.")
            return

        for symbol, base_price in symbols:
            instrument = Instrument(
                symbol=symbol,
                name=symbol,
                exchange="NASDAQ",
                currency="USD",
            )
            session.add(instrument)
            session.flush()

            daily_rows = _generate_daily_bars(base_price=base_price, days=380)
            weekly_rows = _aggregate_weekly(daily_rows)

            for row in daily_rows:
                session.add(
                    MarketBar(
                        instrument_id=instrument.id,
                        timeframe="1d",
                        timestamp=row[0],
                        open=_to_decimal(row[1]),
                        high=_to_decimal(row[2]),
                        low=_to_decimal(row[3]),
                        close=_to_decimal(row[4]),
                        volume=_to_decimal(row[5]),
                    )
                )

            for row in weekly_rows:
                session.add(
                    MarketBar(
                        instrument_id=instrument.id,
                        timeframe="1w",
                        timestamp=row[0],
                        open=_to_decimal(row[1]),
                        high=_to_decimal(row[2]),
                        low=_to_decimal(row[3]),
                        close=_to_decimal(row[4]),
                        volume=_to_decimal(row[5]),
                    )
                )

        session.commit()
        print("Seed completed: demo symbols and bars created.")


if __name__ == "__main__":
    main()
