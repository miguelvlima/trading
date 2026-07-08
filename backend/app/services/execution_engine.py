"""Shared execution primitives for backtesting and paper trading.

Pure functions extracted from ``backtest_engine`` so the historical simulator
and the live paper-trading engine apply exactly the same rules for slippage,
commissions, position sizing and stop-loss / take-profit resolution. Nothing
here touches the database, a broker API or the clock.
"""

from __future__ import annotations

from app.services.commission_models import compute_commission
from app.services.strategy_engine import BarInput

# Typical daily ATR/close for liquid US equities; used to scale dynamic slippage around 1x.
DYNAMIC_SLIPPAGE_BASELINE_ATR_PCT = 0.015
ATR_RISK_STOP_ATR_MULTIPLIER = 2.0


def commission_for_order(
    *,
    fee_model: str,
    shares: float,
    notional: float,
    fee_bps: float,
) -> float:
    """Commission for one order under the configured fee model."""
    return compute_commission(
        fee_model=fee_model,
        shares=shares,
        notional=notional,
        fee_bps=fee_bps,
    )


def dynamic_slippage_bps(
    *,
    base_bps: float,
    atr_value: float | None,
    close: float,
    relative_vol: float | None,
) -> float:
    """Scale base slippage by volatility (ATR%) and inverse relative volume."""
    if close <= 0:
        return base_bps
    if atr_value is None:
        return base_bps

    atr_pct = atr_value / close
    atr_mult = max(0.5, min(4.0, atr_pct / DYNAMIC_SLIPPAGE_BASELINE_ATR_PCT))
    if relative_vol is None or relative_vol <= 0:
        vol_mult = 1.0
    else:
        vol_mult = max(0.75, min(2.5, 1.0 / (relative_vol**0.5)))
    return base_bps * atr_mult * vol_mult


def apply_slippage(raw_price: float, side: str, slippage_rate: float) -> float:
    """Execution price after slippage: BUY pays up, SELL receives less."""
    if side == "BUY":
        return raw_price * (1.0 + slippage_rate)
    return raw_price * (1.0 - slippage_rate)


def compute_position_quantity(
    *,
    capital: float,
    exec_price: float,
    position_sizing_model: str,
    risk_per_trade_pct: float,
    position_size_rate: float,
    stop_loss_rate: float | None,
    atr_value: float | None,
) -> float:
    """Order quantity under ``fixed_pct`` or ``atr_risk`` sizing.

    ``atr_risk`` sizes so that hitting the stop loses ``risk_per_trade_pct`` of
    capital, using the stop distance (or 2x ATR, or 2% of price as fallbacks),
    capped at the ``position_size_rate`` notional.
    """
    if exec_price <= 0 or capital <= 0:
        return 0.0

    if position_sizing_model == "atr_risk":
        risk_amount = capital * max(0.0, risk_per_trade_pct / 100.0)
        if stop_loss_rate:
            stop_distance = exec_price * stop_loss_rate
        else:
            stop_distance = (
                ATR_RISK_STOP_ATR_MULTIPLIER * atr_value
                if atr_value is not None and atr_value > 0
                else exec_price * 0.02
            )
        qty = risk_amount / stop_distance if stop_distance > 0 else 0.0
        max_notional = capital * position_size_rate
        if exec_price * qty > max_notional:
            qty = max_notional / exec_price
        return qty

    return (capital * position_size_rate) / exec_price


def resolve_long_risk_exit(
    bar: BarInput,
    entry_price: float,
    stop_loss_rate: float | None,
    take_profit_rate: float | None,
) -> tuple[str, float] | None:
    """Return (reason, raw_exit_price) when SL/TP is hit within the bar."""
    stop_price = entry_price * (1.0 - stop_loss_rate) if stop_loss_rate is not None else None
    tp_price = entry_price * (1.0 + take_profit_rate) if take_profit_rate is not None else None

    if stop_price is not None and bar.open <= stop_price:
        return "Stop-loss triggered (gap at open).", bar.open
    if tp_price is not None and bar.open >= tp_price:
        return "Take-profit triggered (gap at open).", bar.open

    stop_hit = stop_price is not None and bar.low <= stop_price
    tp_hit = tp_price is not None and bar.high >= tp_price
    if stop_hit and tp_hit:
        return "Stop-loss triggered (intrabar).", stop_price
    if stop_hit:
        return "Stop-loss triggered.", stop_price
    if tp_hit:
        return "Take-profit triggered.", tp_price
    return None


def resolve_short_risk_exit(
    bar: BarInput,
    entry_price: float,
    stop_loss_rate: float | None,
    take_profit_rate: float | None,
) -> tuple[str, float] | None:
    """Return (reason, raw_exit_price) when SL/TP is hit within the bar."""
    stop_price = entry_price * (1.0 + stop_loss_rate) if stop_loss_rate is not None else None
    tp_price = entry_price * (1.0 - take_profit_rate) if take_profit_rate is not None else None

    if stop_price is not None and bar.open >= stop_price:
        return "Stop-loss triggered (gap at open).", bar.open
    if tp_price is not None and bar.open <= tp_price:
        return "Take-profit triggered (gap at open).", bar.open

    stop_hit = stop_price is not None and bar.high >= stop_price
    tp_hit = tp_price is not None and bar.low <= tp_price
    if stop_hit and tp_hit:
        return "Stop-loss triggered (intrabar).", stop_price
    if stop_hit:
        return "Stop-loss triggered.", stop_price
    if tp_hit:
        return "Take-profit triggered.", tp_price
    return None
