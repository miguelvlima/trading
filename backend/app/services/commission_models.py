"""Commission models for backtest fee simulation."""

from __future__ import annotations


def fixed_bps_commission(notional: float, fee_bps: float) -> float:
    return notional * max(0.0, fee_bps / 10000.0)


def ibkr_us_tiered_commission(shares: float, notional: float) -> float:
    """
    IBKR US stocks tiered (simplified for backtests):
    USD 0.0035 per share, minimum USD 0.35 per order, capped at 1% of trade value.
    """
    if notional <= 0 or shares <= 0:
        return 0.0
    per_share = 0.0035
    minimum = 0.35
    max_pct = 0.01
    raw = max(minimum, shares * per_share)
    return min(raw, notional * max_pct)


def compute_commission(
    *,
    fee_model: str,
    shares: float,
    notional: float,
    fee_bps: float,
) -> float:
    if fee_model == "ibkr_us_tiered":
        return ibkr_us_tiered_commission(shares, notional)
    return fixed_bps_commission(notional, fee_bps)
