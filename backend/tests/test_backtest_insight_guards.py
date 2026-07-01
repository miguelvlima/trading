from datetime import UTC, datetime

from app.services.backtest_insight_guards import (
    apply_recommendation_guards,
    detect_parameter_tuning_spiral,
    filter_recommendations_for_symbol_streak,
    is_worsening_negative_streak,
)
from app.services.backtest_insight_types import PriorRunSnapshot


def _prior(pnl: float, *, sl: float | None = None) -> PriorRunSnapshot:
    return PriorRunSnapshot(
        run_id=1,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        net_pnl_pct=pnl,
        win_rate=0.3,
        profit_factor=0.4,
        trades_count=10,
        stop_loss_pct=sl,
    )


def test_is_worsening_negative_streak_detects_amzn_like_sequence() -> None:
    pnls = [-0.3492, -0.2771, -0.2445, -0.2342]
    assert is_worsening_negative_streak(pnls, min_length=3) is True


def test_is_worsening_negative_streak_ignores_improving_run() -> None:
    pnls = [-0.08, -0.05, -0.12]
    assert is_worsening_negative_streak(pnls, min_length=3) is False


def test_detect_parameter_tuning_spiral_with_three_worsening_runs() -> None:
    prior = [_prior(-0.2231), _prior(-0.2076)]
    assert detect_parameter_tuning_spiral(prior, -0.2445) is True


def test_apply_recommendation_guards_replaces_incremental_with_pivots() -> None:
    prior = [_prior(-0.2231), _prior(-0.2076)]
    recommendations = [
        {
            "area": "risk",
            "suggestion": "Aumentar stop-loss.",
            "rationale": "Muitos stops.",
            "param_hint": "stop_loss_pct",
            "suggested_values": {"stop_loss_pct": 3.0},
        },
    ]
    guarded = apply_recommendation_guards(
        recommendations,
        prior_runs=prior,
        current_pnl_pct=-0.2445,
        config={"stop_loss_pct": 2.5},
        strategy_names=["bollinger_breakout"],
        timeframe="1d",
    )
    assert not any(item.get("param_hint") == "stop_loss_pct" for item in guarded)
    assert any(item.get("area") == "strategy_pivot" for item in guarded)
    assert any(item.get("param_hint") == "strategies" for item in guarded)


def test_apply_recommendation_guards_blocks_on_stop_loss_creep() -> None:
    prior = [_prior(-0.12, sl=2.0), _prior(-0.10, sl=1.5)]
    recommendations = [
        {
            "area": "risk",
            "suggestion": "Aumentar stop-loss.",
            "rationale": "Muitos stops.",
            "param_hint": "stop_loss_pct",
        }
    ]
    guarded = apply_recommendation_guards(
        recommendations,
        prior_runs=prior,
        current_pnl_pct=-0.15,
        config={"stop_loss_pct": 2.5},
        strategy_names=["bollinger_breakout"],
        timeframe="1d",
    )
    assert any(item.get("area") == "strategy_pivot" for item in guarded)


def test_filter_recommendations_for_symbol_streak_strips_incremental_hints() -> None:
    recommendations = [
        {
            "area": "risk",
            "suggestion": "Aumentar stop-loss.",
            "rationale": "Muitos stops.",
            "param_hint": "stop_loss_pct",
        }
    ]
    filtered = filter_recommendations_for_symbol_streak(
        recommendations,
        [-0.28, -0.24, -0.21],
    )
    assert filtered == []
