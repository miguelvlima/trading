import argparse

from app.db.session import SessionLocal
from app.services.csv_importer import import_ohlcv_csv


def main() -> None:
    parser = argparse.ArgumentParser(description="Import OHLCV CSV into PostgreSQL")
    parser.add_argument("--symbol", required=True, help="Instrument symbol (e.g. AAPL)")
    parser.add_argument("--timeframe", default="1d", help="Bar timeframe (default: 1d)")
    parser.add_argument("--csv-path", required=True, help="Absolute or relative CSV path")
    parser.add_argument("--name", default=None, help="Instrument descriptive name")
    parser.add_argument("--exchange", default=None, help="Exchange (e.g. NASDAQ)")
    parser.add_argument("--currency", default="USD", help="Quote currency (default: USD)")
    args = parser.parse_args()

    with SessionLocal() as session:
        result = import_ohlcv_csv(
            session,
            csv_path=args.csv_path,
            symbol=args.symbol,
            timeframe=args.timeframe,
            instrument_name=args.name,
            exchange=args.exchange,
            currency=args.currency,
        )

    print(
        f"Imported {result.imported_rows} rows for {result.symbol} ({result.timeframe}) from {args.csv_path}"
    )


if __name__ == "__main__":
    main()
