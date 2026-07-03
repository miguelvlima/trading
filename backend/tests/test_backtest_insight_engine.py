from datetime import UTC, datetime, timedelta
from decimal import Decimal

from types import SimpleNamespace

from app.db.models import BacktestTrade
from app.services.backtest_insight_engine import build_backtest_insight
from app.services.backtest_insight_types import PriorRunSnapshot


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
    sl_recommendation = next(
        item for item in payload.recommendations if item.get("param_hint") == "stop_loss_pct"
    )
    assert sl_recommendation.get("suggested_values") == {"stop_loss_pct": 2.5}


def test_build_backtest_insight_blocks_param_recommendations_on_spiral() -> None:
    metrics = SimpleNamespace(
        net_pnl_pct=-0.2445,
        win_rate=0.3,
        profit_factor=0.38,
        max_drawdown_pct=0.42,
        trades_count=10,
        bars_processed=200,
    )
    trades = [
        _trade(exit_reason="stop-loss hit"),
        _trade(exit_reason="stop-loss hit", net_pnl=Decimal("-40")),
    ]
    prior = [
        PriorRunSnapshot(
            run_id=17,
            created_at=datetime(2026, 6, 1, 10, 46, tzinfo=UTC),
            net_pnl_pct=-0.2231,
            win_rate=0.273,
            profit_factor=0.43,
            trades_count=11,
            stop_loss_pct=2.5,
        ),
        PriorRunSnapshot(
            run_id=16,
            created_at=datetime(2026, 6, 1, 10, 45, tzinfo=UTC),
            net_pnl_pct=-0.2076,
            win_rate=0.273,
            profit_factor=0.44,
            trades_count=11,
            stop_loss_pct=2.0,
        ),
    ]
    payload = build_backtest_insight(
        symbol="AMZN",
        timeframe="1d",
        strategy_names=["bollinger_breakout"],
        metrics=metrics,
        trades=trades,
        result_summary={
            "benchmark_return_pct": 0.12,
            "alpha_vs_benchmark_pct": -0.3,
            "config": {"stop_loss_pct": 3.0, "min_consensus_strength": 0.15},
        },
        config={"stop_loss_pct": 3.0, "min_consensus_strength": 0.15},
        prior_runs=prior,
    )

    assert any(item.get("area") == "strategy_pivot" for item in payload.recommendations)
    assert any(item.get("param_hint") == "strategies" for item in payload.recommendations)
    assert any(item["code"] == "parameter_tuning_spiral" for item in payload.failure_modes)


def test_build_backtest_insight_zero_trades_suggests_loosening() -> None:
    metrics = SimpleNamespace(
        net_pnl_pct=0.0,
        win_rate=0.0,
        profit_factor=0.0,
        max_drawdown_pct=0.0,
        trades_count=0,
        bars_processed=407,
    )
    payload = build_backtest_insight(
        symbol="AMZN",
        timeframe="1d",
        strategy_names=["macd_crossover"],
        metrics=metrics,
        trades=[],
        result_summary={
            "benchmark_return_pct": 0.0122,
            "alpha_vs_benchmark_pct": -0.0122,
            "config": {
                "stop_loss_pct": 2.0,
                "take_profit_pct": 4.0,
                "entry_confirmation_bars": 2,
                "min_consensus_strength": 0.1,
            },
        },
        config={
            "stop_loss_pct": 2.0,
            "take_profit_pct": 4.0,
            "entry_confirmation_bars": 2,
            "min_consensus_strength": 0.1,
        },
        prior_runs=[],
    )

    assert any(item["code"] == "no_trades_executed" for item in payload.failure_modes)
    assert not any(item["code"] == "negative_pnl" for item in payload.failure_modes)
    assert any(item.get("area") == "loosen_entry_confirmation" for item in payload.recommendations)
    assert not any(item.get("area") == "entry_confirmation" for item in payload.recommendations)


def test_build_backtest_insight_winning_run_has_no_recommendations() -> None:
    from types import SimpleNamespace

    metrics = SimpleNamespace(
        net_pnl_pct=0.086,
        win_rate=0.5,
        profit_factor=1.74,
        max_drawdown_pct=0.058,
        trades_count=8,
        bars_processed=407,
    )
    payload = build_backtest_insight(
        symbol="AMZN",
        timeframe="1d",
        strategy_names=["rsi_mean_reversion"],
        metrics=metrics,
        trades=[],
        result_summary={
            "benchmark_return_pct": 0.012,
            "alpha_vs_benchmark_pct": 0.074,
            "config": {"stop_loss_pct": 2.0, "take_profit_pct": 4.0},
        },
        config={"stop_loss_pct": 2.0, "take_profit_pct": 4.0},
        prior_runs=[],
    )
    assert payload.recommendations == []
    assert "Sem alterações sugeridas" in payload.narrative_summary
