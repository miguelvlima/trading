from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from app.db.models import PaperTrade
from app.services.paper_trading.types import RiskSettings, RiskVeto


@dataclass(frozen=True)
class ProposalContext:
    """Everything the risk rules need to judge one order proposal."""

    side: str
    symbol: str
    quantity: float
    price: float  # reference price used for sizing (latest quote)
    stop_loss_pct: float | None
    equity: float
    cash: float
    open_exposure_notional: float  # market value of open positions
    is_closing: bool  # SELL that reduces an existing position
    kill_switch_active: bool
    cooldown_until: datetime | None
    market_session: str  # rth | closed
    # Inside the flat-EOD window (last minutes of the NY session): new entries
    # are vetoed; closing orders pass so the sweep can flatten positions.
    in_eod_window: bool = False


class RiskManager:
    """Vets every order before any fill. Each veto carries a PT reason that is
    written to the event ledger verbatim."""

    def __init__(self, settings: RiskSettings) -> None:
        self._settings = settings

    def evaluate_proposal(self, ctx: ProposalContext, *, now: datetime) -> RiskVeto | None:
        s = self._settings

        if ctx.kill_switch_active:
            return RiskVeto(
                code="kill_switch",
                reason="Kill switch ativo: novas ordens bloqueadas até rearme manual.",
            )

        if ctx.cooldown_until is not None and now < ctx.cooldown_until:
            remaining = int((ctx.cooldown_until - now).total_seconds() // 60) + 1
            return RiskVeto(
                code="cooldown",
                reason=(
                    f"Cooldown após {s.max_consecutive_losses} perdas consecutivas "
                    f"(~{remaining} min restantes)."
                ),
            )

        if s.rth_only and ctx.market_session != "rth":
            return RiskVeto(
                code="market_closed",
                reason="Fora do horário regular de mercado (rth_only ativo).",
            )

        if ctx.quantity <= 0 or ctx.price <= 0:
            return RiskVeto(code="invalid_order", reason="Quantidade ou preço inválidos.")

        # Closing an existing position reduces exposure: sizing/exposure/cash
        # rules below only apply to orders that ADD exposure.
        if ctx.is_closing:
            return None

        if ctx.in_eod_window:
            return RiskVeto(
                code="eod_window",
                reason=(
                    "Janela de fecho de fim de sessão (flat EOD): novas entradas "
                    "bloqueadas até à próxima sessão."
                ),
            )

        if s.require_stop_loss and not ctx.stop_loss_pct:
            return RiskVeto(
                code="missing_stop",
                reason="Stop-loss obrigatório e ausente na proposta.",
            )

        if ctx.equity <= 0:
            return RiskVeto(code="no_equity", reason="Portfolio sem equity disponível.")

        notional = ctx.price * ctx.quantity
        position_pct = notional / ctx.equity * 100.0
        if position_pct > s.max_position_pct + 1e-9:
            return RiskVeto(
                code="position_size",
                reason=(
                    f"Posição de {position_pct:.1f}% do portfolio excede o máximo "
                    f"de {s.max_position_pct:.1f}%."
                ),
            )

        total_pct = (ctx.open_exposure_notional + notional) / ctx.equity * 100.0
        if total_pct > s.max_total_exposure_pct + 1e-9:
            return RiskVeto(
                code="max_exposure",
                reason=(
                    f"Exposição total ficaria em {total_pct:.1f}%, acima do máximo "
                    f"de {s.max_total_exposure_pct:.1f}%."
                ),
            )

        if notional > ctx.cash:
            return RiskVeto(
                code="insufficient_cash",
                reason=f"Cash insuficiente (${ctx.cash:,.2f}) para notional de ${notional:,.2f}.",
            )

        return None


def daily_loss_breached(
    *, day_pnl: float, day_start_equity: float, limit_pct: float
) -> bool:
    """True when today's PnL breaches the daily loss limit (kill switch)."""
    if day_start_equity <= 0 or limit_pct <= 0:
        return False
    return day_pnl <= -(limit_pct / 100.0) * day_start_equity


def consecutive_losses(trades_today: list[PaperTrade]) -> int:
    """Current streak of consecutive losing closes today (most-recent-first)."""
    streak = 0
    for trade in trades_today:
        if trade.realized_pnl is None:
            continue
        if Decimal(trade.realized_pnl) < 0:
            streak += 1
        else:
            break
    return streak


def cooldown_until_from_trades(
    trades_today: list[PaperTrade], settings: RiskSettings
) -> datetime | None:
    """Cooldown expiry if the last N closing trades today were consecutive losses.

    ``trades_today`` must be ordered most-recent-first; only trades that
    realized PnL count (entries have ``realized_pnl`` None and are skipped).
    """
    if settings.max_consecutive_losses <= 0:
        return None
    consecutive = 0
    last_loss_at: datetime | None = None
    for trade in trades_today:
        if trade.realized_pnl is None:
            continue
        if Decimal(trade.realized_pnl) < 0:
            consecutive += 1
            if last_loss_at is None:
                last_loss_at = trade.executed_at
            if consecutive >= settings.max_consecutive_losses:
                return last_loss_at + timedelta(minutes=settings.cooldown_minutes)
        else:
            break
    return None
