import pytest

from app.services.commission_models import compute_commission, ibkr_us_tiered_commission


def test_ibkr_us_tiered_uses_minimum() -> None:
    assert ibkr_us_tiered_commission(shares=10, notional=500) == 0.35


def test_ibkr_us_tiered_scales_with_shares() -> None:
    assert ibkr_us_tiered_commission(shares=200, notional=20_000) == pytest.approx(0.70)


def test_ibkr_us_tiered_caps_at_one_percent() -> None:
    assert ibkr_us_tiered_commission(shares=20_000, notional=5_000) == 50.0


def test_fixed_bps_commission_via_compute() -> None:
    fee = compute_commission(fee_model="fixed_bps", shares=100, notional=10_000, fee_bps=10)
    assert fee == 10.0


def test_ibkr_model_via_compute() -> None:
    fee = compute_commission(fee_model="ibkr_us_tiered", shares=50, notional=5_000, fee_bps=10)
    assert fee == 0.35
