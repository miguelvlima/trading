from pathlib import Path

import pytest

from app.services.csv_importer import parse_ohlcv_csv_rows


def test_parse_ohlcv_csv_rows_success(tmp_path: Path) -> None:
    csv_file = tmp_path / "candles.csv"
    csv_file.write_text(
        "timestamp,open,high,low,close,volume\n"
        "2026-06-20T00:00:00Z,100,110,95,105,12345\n",
        encoding="utf-8",
    )

    rows = parse_ohlcv_csv_rows(str(csv_file))

    assert len(rows) == 1
    assert str(rows[0]["close"]) == "105"


def test_parse_ohlcv_csv_rows_missing_required_column(tmp_path: Path) -> None:
    csv_file = tmp_path / "candles_invalid.csv"
    csv_file.write_text(
        "timestamp,open,high,low,close\n"
        "2026-06-20T00:00:00Z,100,110,95,105\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing required columns: volume"):
        parse_ohlcv_csv_rows(str(csv_file))
