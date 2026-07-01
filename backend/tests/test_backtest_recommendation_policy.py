from app.services.backtest_recommendation_policy import (
    is_protected_winning_run,
    suppress_recommendations_for_winning_run,
)


def test_is_protected_winning_run_requires_positive_pnl_and_pf() -> None:
    assert is_protected_winning_run(trades_count=8, net_pnl_pct=0.086, profit_factor=1.74)
    assert not is_protected_winning_run(trades_count=0, net_pnl_pct=0.0, profit_factor=0.0)
    assert not is_protected_winning_run(trades_count=8, net_pnl_pct=-0.04, profit_factor=0.86)
    assert not is_protected_winning_run(trades_count=8, net_pnl_pct=0.02, profit_factor=0.95)


def test_suppress_recommendations_for_winning_run_clears_pivots() -> None:
    recommendations = [
        {
            "area": "strategy_pivot",
            "suggestion": "Trocar estratégia",
            "param_hint": "strategies",
            "suggested_values": {"strategies": ["bollinger_breakout"]},
        }
    ]
    suppressed = suppress_recommendations_for_winning_run(
        recommendations,
        trades_count=8,
        net_pnl_pct=0.086,
        profit_factor=1.74,
    )
    assert suppressed == []
