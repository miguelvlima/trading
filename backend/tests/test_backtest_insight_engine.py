from datetime import UTC, datetime, timedelta
from decimal import Decimal

from types import SimpleNamespace

from app.db.models import BacktestTrade
from app.services.backtest_insight_engine import PriorRunSnapshot, build_backtest_insight


def _trade(**kwargs: object) -> BacktestTrade:
    defaults = {
        "direction": "BUY",
        "entry_timestamp": datetime(2026, 1, 1, tzinfo=UTC),
        "exit_timestamp": datetime(2026, 1, 5, tzinfo=UTC),
        "entry_price": Decimal("100"),
        "exit_price": Decimal("95"),
        "quantity": Decimal("10"),
        "gross_pnl": Decimal("-50"),
        "fee_paid": Decimal("1"),
        "net_pnl": Decimal("-51"),
        "return_pct": Decimal("-0.05"),
        "bars_held": 4,
        "entry_reason": "macd crossover",
        "exit_reason": "stop-loss hit",
    }
    defaults.update(kwargs)
    return BacktestTrade(
        id=1,
        run_id=1,
        direction=str(defaults["direction"]),
        entry_timestamp=defaults["entry_timestamp"],  # type: ignore[arg-type]
        exit_timestamp=defaults["exit_timestamp"],  # type: ignore[arg-type]
        entry_price=defaults["entry_price"],  # type: ignore[arg-type]
        exit_price=defaults["exit_price"],  # type: ignore[arg-type]
        quantity=defaults["quantity"],  # type: ignore[arg-type]
        gross_pnl=defaults["gross_pnl"],  # type: ignore[arg-type]
        fee_paid=defaults["fee_paid"],  # type: ignore[arg-type]
        net_pnl=defaults["net_pnl"],  # type: ignore[arg-type]
        return_pct=defaults["return_pct"],  # type: ignore[arg-type]
        bars_held=int(defaults["bars_held"]),  # type: ignore[arg-type]
        entry_reason=str(defaults["entry_reason"]),
        exit_reason=str(defaults["exit_reason"]),
    )


def test_build_backtest_insight_flags_negative_run() -> None:
    metrics = SimpleNamespace(
        net_pnl_pct=-0.08,
        win_rate=0.35,
        profit_factor=0.72,
        max_drawdown_pct=0.12,
        trades_count=6,
        bars_processed=200,
    )
    trades = [
        _trade(exit_reason="stop-loss hit"),
        _trade(exit_reason="stop-loss hit", net_pnl=Decimal("-40")),
        _trade(exit_reason="take-profit hit", net_pnl=Decimal("30")),
    ]
    prior = [
        PriorRunSnapshot(
            run_id=9,
            created_at=datetime(2026, 5, 1, tzinfo=UTC),
            net_pnl_pct=-0.05,
            win_rate=0.4,
            profit_factor=0.8,
            trades_count=4,
        )
    ]
    payload = build_backtest_insight(
        symbol="AAPL",
        timeframe="1d",
        strategy_names=["macd_crossover"],
        metrics=metrics,
        trades=trades,
        result_summary={
            "benchmark_return_pct": 0.12,
            "alpha_vs_benchmark_pct": -0.2,
            "config": {"stop_loss_pct": 2.0, "min_consensus_strength": 0.1},
        },
        config={"stop_loss_pct": 2.0, "min_consensus_strength": 0.1},
        prior_runs=prior,
    )

    assert "negativo" in payload.narrative_summary.lower() or "PnL" in payload.narrative_summary
    assert any(item["code"] == "negative_pnl" for item in payload.failure_modes)
    assert any(item["code"] == "underperformed_benchmark" for item in payload.failure_modes)
    assert len(payload.timeline) >= 2
    assert len(payload.lessons) >= 1
    assert payload.prior_runs_context["runs_considered"] == 1
