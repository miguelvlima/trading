from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class PriorRunSnapshot:
    run_id: int
    created_at: datetime
    net_pnl_pct: float
    win_rate: float
    profit_factor: float
    trades_count: int
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    min_consensus_strength: float | None = None
