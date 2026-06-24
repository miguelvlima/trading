from datetime import UTC, datetime, timedelta

from app.services.backtest_engine import (
    AggregatedSignal,
    BacktestConfig,
    run_backtest_with_walkforward,
)
from app.services.backtest_export import render_equity_csv, render_trades_csv
from app.services.strategy_engine import BarInput


def _bars(count: int) -> list[BarInput]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    bars: list[BarInput] = []
    price = 100.0
    for index in range(count):
        bars.append(
            BarInput(
                timestamp=start + timedelta(days=index),
                open=price,
                high=price + 1,
                low=price - 1,
                close=price,
                volume=1000,
            )
        )
        price += 0.1
    return bars


def _config() -> BacktestConfig:
    return BacktestConfig(
        initial_capital=10_000.0,
        fee_bps=0.0,
        fee_model="fixed_bps",
        slippage_bps=0.0,
        slippage_model="fixed",
        position_size_pct=100.0,
        position_sizing_model="fixed_pct",
        risk_per_trade_pct=1.0,
        entry_confirmation_bars=1,
        execution_timing="signal_close",
        exit_mode="opposite_signal",
        stop_loss_pct=None,
        take_profit_pct=None,
        max_bars_in_trade=None,
        benchmark_enabled=False,
    )


def test_rolling_walkforward_returns_fold_summaries() -> None:
    bars = _bars(120)
    ts = bars[40].timestamp
    signals = {
        ts: AggregatedSignal(direction="BUY", confidence=0.8, rationale="test"),
    }
    output = run_backtest_with_walkforward(
        bars=bars,
        aggregated_signals=signals,
        config=_config(),
        split_pct=25,
        walkforward_mode="rolling",
        walkforward_folds=3,
    )
    walkforward = output.summary["walkforward"]
    assert isinstance(walkforward, dict)
    assert walkforward["mode"] == "rolling"
    assert walkforward["folds_count"] >= 1
    assert isinstance(walkforward["folds"], list)
    assert isinstance(walkforward["out_sample_aggregate"], dict)


def test_render_trades_csv_includes_header_and_row() -> None:
    csv_text = render_trades_csv(
        [
            {
                "direction": "LONG",
                "entry_timestamp": datetime(2024, 1, 1, tzinfo=UTC),
                "exit_timestamp": datetime(2024, 1, 2, tzinfo=UTC),
                "entry_price": 100.0,
                "exit_price": 101.0,
                "quantity": 10.0,
                "gross_pnl": 10.0,
                "fee_paid": 0.5,
                "net_pnl": 9.5,
                "return_pct": 0.01,
                "bars_held": 1,
                "entry_reason": "entry",
                "exit_reason": "exit",
            }
        ]
    )
    lines = csv_text.strip().splitlines()
    assert lines[0].startswith("direction,")
    assert "LONG" in lines[1]


def test_render_equity_csv_includes_benchmark_column() -> None:
    csv_text = render_equity_csv(
        [
            {
                "timestamp": "2024-01-01T00:00:00+00:00",
                "equity": 10000,
                "drawdown_pct": 0,
                "benchmark_equity": 10000,
            }
        ]
    )
    assert "benchmark_equity" in csv_text.splitlines()[0]
