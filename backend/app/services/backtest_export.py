"""CSV export helpers for backtest runs."""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any


def _format_timestamp(value: datetime | str) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def render_trades_csv(trades: list[dict[str, Any]]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "direction",
            "entry_timestamp",
            "exit_timestamp",
            "entry_price",
            "exit_price",
            "quantity",
            "gross_pnl",
            "fee_paid",
            "net_pnl",
            "return_pct",
            "bars_held",
            "entry_reason",
            "exit_reason",
        ]
    )
    for trade in trades:
        writer.writerow(
            [
                trade.get("direction", ""),
                _format_timestamp(trade["entry_timestamp"]),
                _format_timestamp(trade["exit_timestamp"]),
                trade.get("entry_price", ""),
                trade.get("exit_price", ""),
                trade.get("quantity", ""),
                trade.get("gross_pnl", ""),
                trade.get("fee_paid", ""),
                trade.get("net_pnl", ""),
                trade.get("return_pct", ""),
                trade.get("bars_held", ""),
                trade.get("entry_reason", ""),
                trade.get("exit_reason", ""),
            ]
        )
    return output.getvalue()


def render_equity_csv(equity_curve: list[dict[str, Any]]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["timestamp", "equity", "drawdown_pct", "benchmark_equity"])
    for point in equity_curve:
        writer.writerow(
            [
                _format_timestamp(point["timestamp"]),
                point.get("equity", ""),
                point.get("drawdown_pct", ""),
                point.get("benchmark_equity", ""),
            ]
        )
    return output.getvalue()
