from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from app.services.paper_trading.risk import (
    ProposalContext,
    RiskManager,
    cooldown_until_from_trades,
    daily_loss_breached,
)
from app.services.paper_trading.types import RiskSettings

NOW = datetime(2026, 7, 8, 15, 0, tzinfo=UTC)  # Wednesday, inside RTH


def make_ctx(**overrides) -> ProposalContext:
    defaults = dict(
        side="BUY",
        symbol="AAPL",
        quantity=10.0,
        price=100.0,
        stop_loss_pct=2.0,
        equity=100_000.0,
        cash=100_000.0,
        open_exposure_notional=0.0,
        is_closing=False,
        kill_switch_active=False,
        cooldown_until=None,
        market_session="rth",
    )
    defaults.update(overrides)
    return ProposalContext(**defaults)


def test_happy_path_has_no_veto() -> None:
    assert RiskManager(RiskSettings()).evaluate_proposal(make_ctx(), now=NOW) is None


def test_kill_switch_vetoes_everything() -> None:
    veto = RiskManager(RiskSettings()).evaluate_proposal(
        make_ctx(kill_switch_active=True), now=NOW
    )
    assert veto is not None and veto.code == "kill_switch"


def test_cooldown_vetoes_until_expiry() -> None:
    manager = RiskManager(RiskSettings())
    active = manager.evaluate_proposal(
        make_ctx(cooldown_until=NOW + timedelta(minutes=10)), now=NOW
    )
    assert active is not None and active.code == "cooldown"

    expired = manager.evaluate_proposal(
        make_ctx(cooldown_until=NOW - timedelta(minutes=1)), now=NOW
    )
    assert expired is None


def test_rth_only_vetoes_when_market_closed() -> None:
    veto = RiskManager(RiskSettings(rth_only=True)).evaluate_proposal(
        make_ctx(market_session="closed"), now=NOW
    )
    assert veto is not None and veto.code == "market_closed"

    allowed = RiskManager(RiskSettings(rth_only=False)).evaluate_proposal(
        make_ctx(market_session="closed"), now=NOW
    )
    assert allowed is None


def test_missing_stop_vetoed_when_required() -> None:
    veto = RiskManager(RiskSettings(require_stop_loss=True)).evaluate_proposal(
        make_ctx(stop_loss_pct=None), now=NOW
    )
    assert veto is not None and veto.code == "missing_stop"

    allowed = RiskManager(RiskSettings(require_stop_loss=False)).evaluate_proposal(
        make_ctx(stop_loss_pct=None), now=NOW
    )
    assert allowed is None


def test_position_size_cap() -> None:
    # 15% of equity vs a 10% cap.
    veto = RiskManager(RiskSettings(max_position_pct=10.0)).evaluate_proposal(
        make_ctx(quantity=150.0, price=100.0), now=NOW
    )
    assert veto is not None and veto.code == "position_size"


def test_total_exposure_cap() -> None:
    veto = RiskManager(
        RiskSettings(max_position_pct=10.0, max_total_exposure_pct=50.0)
    ).evaluate_proposal(
        make_ctx(quantity=100.0, price=100.0, open_exposure_notional=41_000.0),
        now=NOW,
    )
    assert veto is not None and veto.code == "max_exposure"


def test_insufficient_cash() -> None:
    veto = RiskManager(
        RiskSettings(max_position_pct=100.0, max_total_exposure_pct=100.0)
    ).evaluate_proposal(
        make_ctx(quantity=90.0, price=100.0, cash=5_000.0, equity=10_000.0),
        now=NOW,
    )
    assert veto is not None and veto.code == "insufficient_cash"


def test_closing_orders_skip_sizing_rules() -> None:
    # A close larger than any cap and without a stop is still allowed.
    veto = RiskManager(RiskSettings()).evaluate_proposal(
        make_ctx(
            side="SELL",
            is_closing=True,
            stop_loss_pct=None,
            quantity=10_000.0,
            cash=0.0,
        ),
        now=NOW,
    )
    assert veto is None


def test_daily_loss_breached_boundary() -> None:
    assert daily_loss_breached(day_pnl=-3_000.0, day_start_equity=100_000.0, limit_pct=3.0)
    assert not daily_loss_breached(day_pnl=-2_999.0, day_start_equity=100_000.0, limit_pct=3.0)
    assert not daily_loss_breached(day_pnl=-3_000.0, day_start_equity=0.0, limit_pct=3.0)


def _trade(pnl: float | None, minutes_ago: int) -> SimpleNamespace:
    return SimpleNamespace(
        realized_pnl=Decimal(str(pnl)) if pnl is not None else None,
        executed_at=NOW - timedelta(minutes=minutes_ago),
    )


def test_cooldown_after_consecutive_losses() -> None:
    settings = RiskSettings(max_consecutive_losses=3, cooldown_minutes=60)
    trades = [_trade(-10, 1), _trade(-5, 2), _trade(-1, 3)]  # newest first
    until = cooldown_until_from_trades(trades, settings)
    assert until == NOW - timedelta(minutes=1) + timedelta(minutes=60)


def test_cooldown_broken_by_win_or_entry_gap() -> None:
    settings = RiskSettings(max_consecutive_losses=3, cooldown_minutes=60)
    # A win between losses resets the streak.
    assert cooldown_until_from_trades(
        [_trade(-10, 1), _trade(20, 2), _trade(-5, 3), _trade(-1, 4)], settings
    ) is None
    # Entry fills (realized None) are skipped, not streak-breaking.
    assert (
        cooldown_until_from_trades(
            [_trade(-10, 1), _trade(None, 2), _trade(-5, 3), _trade(-1, 4)], settings
        )
        is not None
    )
