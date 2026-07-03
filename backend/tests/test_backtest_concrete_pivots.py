from app.services.backtest_concrete_pivots import (
    build_spiral_pivot_recommendations,
    build_strategy_pivot_recommendation,
    build_timeframe_pivot_recommendation,
    materialize_recommendations,
    suggest_alternative_strategy,
)


def test_suggest_alternative_strategy_skips_current() -> None:
    assert suggest_alternative_strategy(["bollinger_breakout"]) != "bollinger_breakout"


def test_build_spiral_pivot_recommendations_are_actionable() -> None:
    pivots = build_spiral_pivot_recommendations(
        config={"stop_loss_pct": 3.5, "take_profit_pct": 5.0, "entry_confirmation_bars": 1},
        strategy_names=["bollinger_breakout"],
        timeframe="1d",
    )
    assert len(pivots) >= 3
    assert all(item.get("param_hint") for item in pivots)
    assert all(item.get("suggested_values") for item in pivots)
    assert pivots[0]["area"] == "strategy_pivot"


def test_materialize_recommendations_replaces_vague_spiral_guidance() -> None:
    materialized = materialize_recommendations(
        [
            {
                "area": "tuning_spiral_guard",
                "suggestion": "Mudar o que quiseres.",
                "rationale": "Vago.",
            },
            {
                "area": "strategy_selection",
                "suggestion": "Testar outra estratégia.",
                "rationale": "Vago.",
            },
        ],
        config={"stop_loss_pct": 3.0, "take_profit_pct": 4.5},
        strategy_names=["bollinger_breakout"],
        timeframe="1d",
        recent_pnls_newest_first=[-0.30, -0.25, -0.20],
    )
    assert not any(item.get("area") == "tuning_spiral_guard" for item in materialized)
    assert any(item.get("area") == "strategy_pivot" for item in materialized)
    assert any(item.get("param_hint") == "strategies" for item in materialized)


def test_build_strategy_pivot_has_concrete_values() -> None:
    item = build_strategy_pivot_recommendation(["bollinger_breakout"])
    assert item["param_hint"] == "strategies"
    assert item["suggested_values"] == {"strategies": [suggest_alternative_strategy(["bollinger_breakout"])]}


def test_build_timeframe_pivot_skipped_when_insufficient_weekly_bars() -> None:
    pivot = build_timeframe_pivot_recommendation("1d", bar_counts={"1d": 407, "1w": 53})
    assert pivot is None


def test_build_spiral_pivot_skips_entry_confirmation_after_zero_trade_run() -> None:
    pivots = build_spiral_pivot_recommendations(
        config={"stop_loss_pct": 3.5, "take_profit_pct": 5.0, "entry_confirmation_bars": 1},
        strategy_names=["bollinger_breakout"],
        timeframe="1d",
        trades_count=0,
    )
    assert any(item.get("area") == "loosen_entry_confirmation" for item in pivots) is False
    assert not any(item.get("area") == "entry_confirmation" for item in pivots)
    assert any(item.get("area") == "loosen_signal_strength" for item in pivots)


def test_materialize_recommendations_winning_run_returns_empty() -> None:
    materialized = materialize_recommendations(
        [{"area": "strategy_pivot", "suggestion": "x", "param_hint": "strategies"}],
        config={"stop_loss_pct": 2.0, "take_profit_pct": 4.0},
        strategy_names=["rsi_mean_reversion"],
        timeframe="1d",
        trades_count=8,
        current_pnl_pct=0.086,
        profit_factor=1.74,
        recent_pnls_newest_first=[-0.09, -0.24, -0.20],
    )
    assert materialized == []


def test_materialize_recommendations_zero_trade_returns_recovery() -> None:
    materialized = materialize_recommendations(
        [{"area": "strategy_pivot", "suggestion": "x", "param_hint": "strategies"}],
        config={
            "stop_loss_pct": 2.0,
            "take_profit_pct": 4.0,
            "entry_confirmation_bars": 2,
            "min_consensus_strength": 0.1,
        },
        strategy_names=["macd_crossover"],
        timeframe="1d",
        trades_count=0,
    )
    assert any(item.get("area") == "loosen_entry_confirmation" for item in materialized)
    assert not any(item.get("area") == "entry_confirmation" for item in materialized)


def test_build_timeframe_pivot_included_when_enough_weekly_bars() -> None:
    pivot = build_timeframe_pivot_recommendation("1d", bar_counts={"1d": 407, "1w": 210})
    assert pivot is not None
    assert pivot["suggested_values"] == {"timeframe": "1w"}
