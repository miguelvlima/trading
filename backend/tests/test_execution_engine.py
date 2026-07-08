from datetime import UTC, datetime

from app.services.execution_engine import (
    apply_slippage,
    commission_for_order,
    compute_position_quantity,
    dynamic_slippage_bps,
    resolve_long_risk_exit,
    resolve_short_risk_exit,
)
from app.services.strategy_engine import BarInput


def make_bar(open_=100.0, high=101.0, low=99.0, close=100.5) -> BarInput:
    return BarInput(
        timestamp=datetime(2026, 7, 8, 14, 30, tzinfo=UTC),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=1_000.0,
    )


def test_apply_slippage_buy_pays_up_sell_receives_less() -> None:
    assert apply_slippage(100.0, "BUY", 0.001) == 100.1
    assert apply_slippage(100.0, "SELL", 0.001) == 99.9


def test_dynamic_slippage_scales_with_atr_and_volume() -> None:
    base = dynamic_slippage_bps(base_bps=10.0, atr_value=1.5, close=100.0, relative_vol=1.0)
    assert base == 10.0  # ATR% at baseline, normal volume => 1x

    volatile = dynamic_slippage_bps(base_bps=10.0, atr_value=6.0, close=100.0, relative_vol=1.0)
    assert volatile == 40.0  # 4x ATR multiple, capped

    thin = dynamic_slippage_bps(base_bps=10.0, atr_value=1.5, close=100.0, relative_vol=0.25)
    assert thin == 20.0  # 1/sqrt(0.25) = 2x volume multiplier


def test_dynamic_slippage_falls_back_to_base() -> None:
    assert dynamic_slippage_bps(base_bps=7.0, atr_value=None, close=100.0, relative_vol=1.0) == 7.0
    assert dynamic_slippage_bps(base_bps=7.0, atr_value=2.0, close=0.0, relative_vol=1.0) == 7.0


def test_fixed_pct_position_quantity() -> None:
    qty = compute_position_quantity(
        capital=10_000.0,
        exec_price=50.0,
        position_sizing_model="fixed_pct",
        risk_per_trade_pct=1.0,
        position_size_rate=0.20,
        stop_loss_rate=None,
        atr_value=None,
    )
    assert qty == 40.0  # 20% of 10k / 50


def test_atr_risk_sizes_by_stop_distance_and_caps_notional() -> None:
    qty = compute_position_quantity(
        capital=10_000.0,
        exec_price=100.0,
        position_sizing_model="atr_risk",
        risk_per_trade_pct=1.0,
        position_size_rate=1.0,
        stop_loss_rate=0.02,
        atr_value=None,
    )
    assert qty == 50.0  # risk $100 / stop distance $2

    capped = compute_position_quantity(
        capital=10_000.0,
        exec_price=100.0,
        position_sizing_model="atr_risk",
        risk_per_trade_pct=5.0,
        position_size_rate=0.10,
        stop_loss_rate=0.02,
        atr_value=None,
    )
    assert capped == 10.0  # 250 by risk, capped at 10% notional / price


def test_atr_risk_uses_atr_fallback_without_stop() -> None:
    qty = compute_position_quantity(
        capital=10_000.0,
        exec_price=100.0,
        position_sizing_model="atr_risk",
        risk_per_trade_pct=1.0,
        position_size_rate=1.0,
        stop_loss_rate=None,
        atr_value=2.5,
    )
    assert qty == 20.0  # risk $100 / (2 * ATR 2.5)


def test_position_quantity_zero_on_bad_inputs() -> None:
    common = dict(
        position_sizing_model="fixed_pct",
        risk_per_trade_pct=1.0,
        position_size_rate=0.2,
        stop_loss_rate=None,
        atr_value=None,
    )
    assert compute_position_quantity(capital=0.0, exec_price=50.0, **common) == 0.0
    assert compute_position_quantity(capital=1_000.0, exec_price=0.0, **common) == 0.0


def test_long_risk_exit_stop_beats_take_profit_intrabar() -> None:
    bar = make_bar(open_=100.0, high=106.0, low=97.0)
    result = resolve_long_risk_exit(bar, entry_price=100.0, stop_loss_rate=0.02, take_profit_rate=0.05)
    assert result is not None
    reason, price = result
    assert "Stop-loss" in reason and "intrabar" in reason
    assert price == 98.0


def test_long_risk_exit_gap_at_open() -> None:
    bar = make_bar(open_=95.0, high=96.0, low=94.0)
    result = resolve_long_risk_exit(bar, entry_price=100.0, stop_loss_rate=0.02, take_profit_rate=None)
    assert result is not None
    reason, price = result
    assert "gap at open" in reason
    assert price == 95.0


def test_short_risk_exit_take_profit() -> None:
    bar = make_bar(open_=99.0, high=99.5, low=94.0)
    result = resolve_short_risk_exit(bar, entry_price=100.0, stop_loss_rate=0.05, take_profit_rate=0.05)
    assert result is not None
    reason, price = result
    assert "Take-profit" in reason
    assert price == 95.0


def test_no_risk_exit_when_untouched() -> None:
    bar = make_bar(open_=100.0, high=101.0, low=99.5)
    assert resolve_long_risk_exit(bar, 100.0, 0.02, 0.05) is None
    assert resolve_short_risk_exit(bar, 100.0, 0.02, 0.05) is None


def test_commission_for_order_delegates_to_models() -> None:
    assert commission_for_order(fee_model="fixed_bps", shares=10, notional=10_000.0, fee_bps=10.0) == 10.0
    tiered = commission_for_order(fee_model="ibkr_us_tiered", shares=10, notional=1_000.0, fee_bps=0.0)
    assert tiered == 0.35  # minimum applies
