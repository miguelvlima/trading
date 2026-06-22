from __future__ import annotations

import argparse
from datetime import UTC
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
import yfinance as yf

from app.db.session import SessionLocal
from app.services.csv_importer import import_ohlcv_csv


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)

    required_columns = ["Open", "High", "Low", "Close", "Volume"]
    cleaned = df[required_columns].dropna().copy()
    cleaned.index = pd.to_datetime(cleaned.index, utc=True)
    return cleaned


def _to_csv_with_timestamp(df: pd.DataFrame, csv_path: Path) -> None:
    out_df = df.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    ).copy()
    out_df.insert(0, "timestamp", out_df.index.tz_convert(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
    out_df.to_csv(csv_path, index=False)


def _weekly_from_daily(df_daily: pd.DataFrame) -> pd.DataFrame:
    weekly = (
        df_daily.resample("W-FRI")
        .agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
        .dropna()
    )
    return weekly


def load_symbol(symbol: str, period: str, include_weekly: bool) -> tuple[int, int]:
    raw = yf.download(symbol, period=period, interval="1d", progress=False, auto_adjust=False)
    if raw.empty:
        return 0, 0

    daily_df = _normalize_ohlcv(raw)
    weekly_df = _weekly_from_daily(daily_df) if include_weekly else pd.DataFrame()

    with TemporaryDirectory() as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        daily_csv = temp_dir / f"{symbol}_1d.csv"
        _to_csv_with_timestamp(daily_df, daily_csv)

        with SessionLocal() as session:
            daily_result = import_ohlcv_csv(
                session,
                csv_path=str(daily_csv),
                symbol=symbol,
                timeframe="1d",
                instrument_name=symbol,
                exchange=None,
                currency="USD",
            )

        weekly_rows = 0
        if include_weekly and not weekly_df.empty:
            weekly_csv = temp_dir / f"{symbol}_1w.csv"
            _to_csv_with_timestamp(weekly_df, weekly_csv)
            with SessionLocal() as session:
                weekly_result = import_ohlcv_csv(
                    session,
                    csv_path=str(weekly_csv),
                    symbol=symbol,
                    timeframe="1w",
                    instrument_name=symbol,
                    exchange=None,
                    currency="USD",
                )
                weekly_rows = weekly_result.imported_rows

    return daily_result.imported_rows, weekly_rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Load demo market data for multiple symbols")
    parser.add_argument(
        "--symbols",
        default="AAPL,MSFT,NVDA,TSLA,SPY,QQQ",
        help="Comma-separated symbols list",
    )
    parser.add_argument("--period", default="1y", help="Yahoo period, e.g. 1y, 2y")
    parser.add_argument(
        "--include-weekly",
        action="store_true",
        help="Also import 1w bars aggregated from 1d",
    )
    args = parser.parse_args()

    symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
    if not symbols:
        raise ValueError("No symbols provided.")

    print(f"Loading data for {len(symbols)} symbols: {', '.join(symbols)}")
    for symbol in symbols:
        daily_rows, weekly_rows = load_symbol(symbol, args.period, args.include_weekly)
        if args.include_weekly:
            print(f"{symbol}: imported {daily_rows} rows (1d), {weekly_rows} rows (1w)")
        else:
            print(f"{symbol}: imported {daily_rows} rows (1d)")

    print("Done.")


if __name__ == "__main__":
    main()
