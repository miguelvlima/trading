from __future__ import annotations

from typing import Any


def is_protected_winning_run(
    *,
    trades_count: int | None,
    net_pnl_pct: float | None,
    profit_factor: float | None,
) -> bool:
    """Runs with real trades, positive PnL and PF >= 1 should keep their config."""
    if trades_count is None or net_pnl_pct is None or profit_factor is None:
        return False
    if trades_count <= 0:
        return False
    if net_pnl_pct <= 0:
        return False
    if profit_factor < 1.0:
        return False
    return True


def suppress_recommendations_for_winning_run(
    recommendations: list[dict[str, Any]],
    *,
    trades_count: int | None,
    net_pnl_pct: float | None,
    profit_factor: float | None,
) -> list[dict[str, Any]]:
    if is_protected_winning_run(
        trades_count=trades_count,
        net_pnl_pct=net_pnl_pct,
        profit_factor=profit_factor,
    ):
        return []
    return recommendations
