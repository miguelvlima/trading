from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PaperOrder, PaperPortfolio, PaperPosition, PaperTrade
from app.services.execution_engine import compute_position_quantity
from app.services.paper_trading import events as ev
from app.services.paper_trading.events import EventHub, record_event
from app.services.paper_trading.fills import compute_fill
from app.services.paper_trading.quotes import QuoteCache, market_session
from app.services.paper_trading.risk import (
    ProposalContext,
    RiskManager,
    consecutive_losses,
    cooldown_until_from_trades,
    daily_loss_breached,
)
from app.services.paper_trading.types import (
    STATUS_APPROVED,
    STATUS_CANCELLED,
    STATUS_EXPIRED,
    STATUS_FILLED,
    STATUS_PROPOSED,
    STATUS_REJECTED_RISK,
    STATUS_REJECTED_USER,
    EngineStatus,
    FillComputation,
    FillDeferral,
    QuoteSnapshot,
    RiskSettings,
)

logger = structlog.get_logger(__name__)

_DEC = lambda value: Decimal(str(value))  # noqa: E731 - tiny float->Decimal bridge


class PaperEngine:
    """Core semi-automatic paper-trading logic for one portfolio.

    Every method is synchronous and takes the DB session explicitly, so the
    whole lifecycle is unit-testable offline with a fake clock and hand-fed
    quotes. The async runtime (streaming ticks, periodic signal evaluation)
    lives in ``runtime.py`` and only ever calls into these methods.

    PAPER invariant: this class never talks to a broker; its only market input
    is the :class:`QuoteCache`.
    """

    def __init__(
        self,
        portfolio_id: int,
        *,
        quotes: QuoteCache,
        hub: EventHub | None = None,
        now_fn: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.portfolio_id = portfolio_id
        self.quotes = quotes
        self.hub = hub
        self._now_fn = now_fn

    # -- helpers ---------------------------------------------------------------

    def _emit(
        self,
        db: Session,
        event_type: str,
        message: str,
        *,
        symbol: str | None = None,
        severity: str = "info",
        payload: dict[str, object] | None = None,
    ) -> None:
        record_event(
            db,
            portfolio_id=self.portfolio_id,
            event_type=event_type,
            message=message,
            symbol=symbol,
            severity=severity,
            payload=payload,
            now_fn=self._now_fn,
            broadcast=self.hub,
        )

    @staticmethod
    def settings_for(portfolio: PaperPortfolio) -> RiskSettings:
        return RiskSettings.from_json(portfolio.risk_settings)

    def _positions(self, db: Session) -> list[PaperPosition]:
        return list(
            db.execute(
                select(PaperPosition).where(
                    PaperPosition.portfolio_id == self.portfolio_id,
                    PaperPosition.quantity > 0,
                )
            ).scalars()
        )

    def _position_for(self, db: Session, symbol: str) -> PaperPosition | None:
        return db.execute(
            select(PaperPosition).where(
                PaperPosition.portfolio_id == self.portfolio_id,
                PaperPosition.symbol == symbol.upper(),
            )
        ).scalar_one_or_none()

    def _mark_price(self, position: PaperPosition) -> float:
        quote = self.quotes.get(position.symbol)
        if quote is not None and quote.last is not None:
            return float(quote.last)
        return float(position.avg_entry_price)

    def open_exposure_notional(self, db: Session) -> float:
        return sum(
            float(pos.quantity) * self._mark_price(pos) for pos in self._positions(db)
        )

    def equity_now(self, db: Session, portfolio: PaperPortfolio) -> float:
        return float(portfolio.cash) + self.open_exposure_notional(db)

    def _trades_today(self, db: Session) -> list[PaperTrade]:
        day_start = self._now_fn().astimezone(UTC).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return list(
            db.execute(
                select(PaperTrade)
                .where(
                    PaperTrade.portfolio_id == self.portfolio_id,
                    PaperTrade.executed_at >= day_start,
                )
                .order_by(PaperTrade.executed_at.desc())
            ).scalars()
        )

    def cooldown_until(self, db: Session, settings: RiskSettings) -> datetime | None:
        return cooldown_until_from_trades(self._trades_today(db), settings)

    # -- signal -> proposal ------------------------------------------------------

    def propose_from_signal(
        self,
        db: Session,
        portfolio: PaperPortfolio,
        *,
        symbol: str,
        direction: str,
        strength: float,
        strategy: str,
        rationale: str,
        signal_timestamp: datetime | None = None,
    ) -> PaperOrder | None:
        """Turn one live signal into a ``proposed`` order (or veto/skip it).

        BUY opens/extends a long; SELL only closes an existing long (shorting
        is out of scope this phase). Every outcome is written to the ledger.
        """
        settings = self.settings_for(portfolio)
        now = self._now_fn()
        symbol = symbol.upper()

        self._emit(
            db,
            ev.EVENT_SIGNAL_RECEIVED,
            f"Sinal {direction} {symbol} ({strategy}, força {strength:.2f}): {rationale}",
            symbol=symbol,
            payload={"strategy": strategy, "direction": direction, "strength": strength},
        )

        if strength < settings.min_signal_strength:
            self._emit(
                db,
                ev.EVENT_SIGNAL_SKIPPED,
                f"Sinal {direction} {symbol} abaixo da força mínima "
                f"({strength:.2f} < {settings.min_signal_strength:.2f}).",
                symbol=symbol,
            )
            return None

        # One open order per symbol at a time keeps the pending panel unambiguous.
        open_order = db.execute(
            select(PaperOrder).where(
                PaperOrder.portfolio_id == self.portfolio_id,
                PaperOrder.symbol == symbol,
                PaperOrder.status.in_((STATUS_PROPOSED, STATUS_APPROVED)),
            )
        ).scalar_one_or_none()
        if open_order is not None:
            self._emit(
                db,
                ev.EVENT_SIGNAL_SKIPPED,
                f"Sinal {direction} {symbol} ignorado: já existe ordem aberta #{open_order.id}.",
                symbol=symbol,
            )
            return None

        quote = self.quotes.get(symbol)
        reference_price = float(quote.last) if quote and quote.last is not None else None
        if reference_price is None or reference_price <= 0:
            self._emit(
                db,
                ev.EVENT_SIGNAL_SKIPPED,
                f"Sinal {direction} {symbol} ignorado: sem cotação de referência.",
                symbol=symbol,
                severity="warn",
            )
            return None

        position = self._position_for(db, symbol)
        has_position = position is not None and float(position.quantity) > 0

        if direction == "SELL" and not has_position:
            self._emit(
                db,
                ev.EVENT_SIGNAL_SKIPPED,
                f"Sinal SELL {symbol} ignorado: sem posição aberta (short desativado).",
                symbol=symbol,
            )
            return None
        if direction == "BUY" and has_position:
            self._emit(
                db,
                ev.EVENT_SIGNAL_SKIPPED,
                f"Sinal BUY {symbol} ignorado: posição já aberta.",
                symbol=symbol,
            )
            return None

        is_closing = direction == "SELL"
        equity = self.equity_now(db, portfolio)
        if is_closing:
            quantity = float(position.quantity)  # close the whole position
            stop_loss_pct: float | None = None
            take_profit_pct: float | None = None
        else:
            stop_loss_pct = settings.default_stop_loss_pct or None
            take_profit_pct = settings.default_take_profit_pct or None
            quantity = compute_position_quantity(
                capital=equity,
                exec_price=reference_price,
                position_sizing_model=settings.position_sizing_model,
                risk_per_trade_pct=settings.risk_per_trade_pct,
                position_size_rate=max(0.01, min(1.0, settings.position_size_pct / 100.0)),
                stop_loss_rate=(stop_loss_pct / 100.0) if stop_loss_pct else None,
                atr_value=None,  # tick stream has no ATR; stop distance rules sizing
            )
            quantity = float(int(quantity))  # whole shares for US equities
            if quantity <= 0:
                self._emit(
                    db,
                    ev.EVENT_SIGNAL_SKIPPED,
                    f"Sinal BUY {symbol} ignorado: sizing resultou em 0 ações.",
                    symbol=symbol,
                    severity="warn",
                )
                return None

        veto = RiskManager(settings).evaluate_proposal(
            ProposalContext(
                side=direction,
                symbol=symbol,
                quantity=quantity,
                price=reference_price,
                stop_loss_pct=stop_loss_pct,
                equity=equity,
                cash=float(portfolio.cash),
                open_exposure_notional=self.open_exposure_notional(db),
                is_closing=is_closing,
                kill_switch_active=portfolio.kill_switch_active,
                cooldown_until=self.cooldown_until(db, settings),
                market_session=market_session(now),
            ),
            now=now,
        )

        notional = reference_price * quantity
        risk_snapshot: dict[str, object] = {
            "reference_price": reference_price,
            "notional": notional,
            "position_pct_of_equity": (notional / equity * 100.0) if equity > 0 else None,
            "equity_at_proposal": equity,
        }
        signal_snapshot: dict[str, object] = {
            "strategy": strategy,
            "direction": direction,
            "strength": strength,
            "rationale": rationale,
            "signal_timestamp": signal_timestamp.isoformat() if signal_timestamp else None,
        }

        order = PaperOrder(
            portfolio_id=self.portfolio_id,
            symbol=symbol,
            side=direction,
            quantity=_DEC(quantity),
            order_type="market",
            status=STATUS_REJECTED_RISK if veto else STATUS_PROPOSED,
            stop_loss_pct=_DEC(stop_loss_pct) if stop_loss_pct else None,
            take_profit_pct=_DEC(take_profit_pct) if take_profit_pct else None,
            signal_snapshot=signal_snapshot,
            risk_snapshot=risk_snapshot,
            data_liveness=quote.data_liveness if quote else "UNKNOWN",
            reject_reason=veto.reason if veto else None,
            proposed_at=now,
            decided_at=now if veto else None,
        )
        db.add(order)
        db.flush()

        if veto:
            self._emit(
                db,
                ev.EVENT_RISK_VETO,
                f"VETO {symbol} {direction}: {veto.reason}",
                symbol=symbol,
                severity="warn",
                payload={"order_id": order.id, "code": veto.code},
            )
        else:
            stop_text = f", stop {stop_loss_pct:.1f}%" if stop_loss_pct else ""
            tp_text = f", TP {take_profit_pct:.1f}%" if take_profit_pct else ""
            self._emit(
                db,
                ev.EVENT_ORDER_PROPOSED,
                (
                    f"Ordem proposta: {direction} {quantity:g} {symbol} @ mercado"
                    f"{stop_text}{tp_text} ({risk_snapshot['position_pct_of_equity']:.1f}% do portfolio)."
                    if risk_snapshot["position_pct_of_equity"] is not None
                    else f"Ordem proposta: {direction} {quantity:g} {symbol} @ mercado."
                ),
                symbol=symbol,
                payload={"order_id": order.id},
            )
        return order

    # -- user decisions ----------------------------------------------------------

    def approve_order(
        self, db: Session, portfolio: PaperPortfolio, order: PaperOrder
    ) -> tuple[PaperOrder, PaperTrade | None, FillDeferral | None]:
        """Approve a proposed order and attempt the fill immediately.

        If the feed cannot support a credible fill right now the order stays
        ``approved`` and the runtime retries on the next fresh quote.
        """
        now = self._now_fn()
        settings = self.settings_for(portfolio)

        if portfolio.kill_switch_active:
            order.status = STATUS_REJECTED_RISK
            order.decided_at = now
            order.reject_reason = "Kill switch ativo no momento da aprovação."
            self._emit(
                db,
                ev.EVENT_RISK_VETO,
                f"VETO {order.symbol}: aprovação bloqueada, kill switch ativo.",
                symbol=order.symbol,
                severity="warn",
                payload={"order_id": order.id, "code": "kill_switch"},
            )
            return order, None, None

        order.status = STATUS_APPROVED
        order.decided_at = now
        self._emit(
            db,
            ev.EVENT_ORDER_APPROVED,
            f"Ordem #{order.id} aprovada: {order.side} {float(order.quantity):g} {order.symbol}.",
            symbol=order.symbol,
            payload={"order_id": order.id},
        )

        trade, deferral = self.try_fill_order(db, portfolio, order, settings=settings)
        return order, trade, deferral

    def reject_order(
        self, db: Session, portfolio: PaperPortfolio, order: PaperOrder
    ) -> PaperOrder:
        order.status = STATUS_REJECTED_USER
        order.decided_at = self._now_fn()
        order.reject_reason = "Rejeitada pelo utilizador."
        self._emit(
            db,
            ev.EVENT_ORDER_REJECTED,
            f"Ordem #{order.id} rejeitada pelo utilizador.",
            symbol=order.symbol,
            payload={"order_id": order.id},
        )
        return order

    def manual_close(
        self, db: Session, portfolio: PaperPortfolio, position: PaperPosition
    ) -> tuple[PaperOrder, PaperTrade | None, FillDeferral | None]:
        """Close an open position on user request: SELL the whole quantity.

        Mirrors the protective exit: the click IS the approval, so the order
        is born ``approved`` and fills on the next credible quote (or waits,
        retried by the runtime, if the feed cannot support a fill right now).
        """
        now = self._now_fn()
        settings = self.settings_for(portfolio)
        quote = self.quotes.get(position.symbol)
        order = PaperOrder(
            portfolio_id=self.portfolio_id,
            symbol=position.symbol,
            side="SELL",
            quantity=position.quantity,
            order_type="market",
            status=STATUS_APPROVED,
            signal_snapshot={
                "origin": "manual",
                "strategy": "manual",
                "rationale": "Venda manual pelo utilizador.",
            },
            risk_snapshot={},
            data_liveness=quote.data_liveness if quote else "UNKNOWN",
            proposed_at=now,
            decided_at=now,
        )
        db.add(order)
        db.flush()
        self._emit(
            db,
            ev.EVENT_ORDER_APPROVED,
            f"Venda manual: SELL {float(position.quantity):g} {position.symbol} "
            f"(ordem #{order.id}).",
            symbol=position.symbol,
            payload={"order_id": order.id, "origin": "manual"},
        )
        trade, deferral = self.try_fill_order(db, portfolio, order, settings=settings)
        return order, trade, deferral

    def entry_context(self, db: Session, symbol: str) -> PaperOrder | None:
        """The filled BUY order that opened the current position, if any.

        Sourced from the most recent filled BUY — the position row itself
        survives closes/reopens, so its ``created_at`` can lie about the entry.
        Callers read opened-at, strategy/rationale and stop/TP levels from it.
        """
        return db.execute(
            select(PaperOrder)
            .where(
                PaperOrder.portfolio_id == self.portfolio_id,
                PaperOrder.symbol == symbol.upper(),
                PaperOrder.side == "BUY",
                PaperOrder.status == STATUS_FILLED,
            )
            .order_by(PaperOrder.filled_at.desc())
            .limit(1)
        ).scalar_one_or_none()

    def position_provenance(self, db: Session, position: PaperPosition) -> dict[str, object]:
        """Cockpit fields answering "why/when was this opened, where does it exit?"."""
        entry = self.entry_context(db, position.symbol)
        if entry is None:
            return {
                "opened_at": None,
                "strategy": None,
                "rationale": None,
                "stop_price": None,
                "take_profit_price": None,
            }
        snapshot = entry.signal_snapshot or {}
        entry_price = float(position.avg_entry_price)
        stop = float(entry.stop_loss_pct) if entry.stop_loss_pct is not None else None
        tp = float(entry.take_profit_pct) if entry.take_profit_pct is not None else None
        strategy = snapshot.get("strategy")
        rationale = snapshot.get("rationale")
        return {
            "opened_at": entry.filled_at,
            "strategy": str(strategy) if strategy else None,
            "rationale": str(rationale) if rationale else None,
            "stop_price": entry_price * (1.0 - stop / 100.0) if stop else None,
            "take_profit_price": entry_price * (1.0 + tp / 100.0) if tp else None,
        }

    def cancel_order(
        self, db: Session, portfolio: PaperPortfolio, order: PaperOrder
    ) -> PaperOrder:
        order.status = STATUS_CANCELLED
        order.decided_at = self._now_fn()
        self._emit(
            db,
            ev.EVENT_ORDER_CANCELLED,
            f"Ordem #{order.id} cancelada.",
            symbol=order.symbol,
            payload={"order_id": order.id},
        )
        return order

    def expire_stale_proposals(self, db: Session, portfolio: PaperPortfolio) -> int:
        """Expire ``proposed`` orders older than the configured window."""
        settings = self.settings_for(portfolio)
        cutoff = self._now_fn() - timedelta(minutes=settings.order_expiry_minutes)
        stale = list(
            db.execute(
                select(PaperOrder).where(
                    PaperOrder.portfolio_id == self.portfolio_id,
                    PaperOrder.status == STATUS_PROPOSED,
                    PaperOrder.proposed_at < cutoff,
                )
            ).scalars()
        )
        for order in stale:
            order.status = STATUS_EXPIRED
            order.decided_at = self._now_fn()
            self._emit(
                db,
                ev.EVENT_ORDER_EXPIRED,
                f"Ordem #{order.id} expirou sem decisão "
                f"({settings.order_expiry_minutes} min).",
                symbol=order.symbol,
                payload={"order_id": order.id},
            )
        return len(stale)

    # -- fills --------------------------------------------------------------------

    def try_fill_order(
        self,
        db: Session,
        portfolio: PaperPortfolio,
        order: PaperOrder,
        *,
        settings: RiskSettings | None = None,
    ) -> tuple[PaperTrade | None, FillDeferral | None]:
        """Fill an ``approved`` order against the latest quote, if credible."""
        if order.status != STATUS_APPROVED:
            return None, None
        settings = settings or self.settings_for(portfolio)
        now = self._now_fn()

        result = compute_fill(
            side=order.side,
            quantity=float(order.quantity),
            quote=self.quotes.get(order.symbol),
            settings=settings,
            now=now,
        )
        if isinstance(result, FillDeferral):
            self._emit(
                db,
                ev.EVENT_FILL_DEFERRED,
                f"Fill da ordem #{order.id} adiado: {result.reason}",
                symbol=order.symbol,
                severity="warn",
                payload={"order_id": order.id, "code": result.code},
            )
            return None, result

        trade = self._apply_fill(db, portfolio, order, result, now)
        self._check_kill_switch(db, portfolio, settings)
        return trade, None

    def _apply_fill(
        self,
        db: Session,
        portfolio: PaperPortfolio,
        order: PaperOrder,
        fill: FillComputation,
        now: datetime,
    ) -> PaperTrade:
        quantity = float(order.quantity)
        notional = fill.price * quantity
        realized: float | None = None

        position = self._position_for(db, order.symbol)
        if order.side == "BUY":
            portfolio.cash = _DEC(float(portfolio.cash) - notional - fill.fee)
            if position is None:
                position = PaperPosition(
                    portfolio_id=self.portfolio_id,
                    symbol=order.symbol,
                    quantity=_DEC(quantity),
                    avg_entry_price=_DEC(fill.price),
                )
                db.add(position)
            else:
                old_qty = float(position.quantity)
                new_qty = old_qty + quantity
                position.avg_entry_price = _DEC(
                    (old_qty * float(position.avg_entry_price) + notional) / new_qty
                )
                position.quantity = _DEC(new_qty)
        else:
            if position is None or float(position.quantity) < quantity - 1e-9:
                # Defensive: risk rules prevent this; never let cash go negative silently.
                quantity = float(position.quantity) if position else 0.0
            realized = (fill.price - float(position.avg_entry_price)) * quantity - fill.fee
            portfolio.cash = _DEC(float(portfolio.cash) + fill.price * quantity - fill.fee)
            position.quantity = _DEC(float(position.quantity) - quantity)
            position.realized_pnl = _DEC(float(position.realized_pnl) + realized)

        order.status = STATUS_FILLED
        order.filled_at = now
        order.data_liveness = fill.data_liveness

        trade = PaperTrade(
            portfolio_id=self.portfolio_id,
            order_id=order.id,
            symbol=order.symbol,
            side=order.side,
            quantity=_DEC(quantity),
            price=_DEC(fill.price),
            fee_paid=_DEC(fill.fee),
            fill_basis=fill.basis,
            quote_age_seconds=_DEC(round(fill.quote_age_seconds, 3)),
            data_liveness=fill.data_liveness,
            realized_pnl=_DEC(realized) if realized is not None else None,
            executed_at=now,
        )
        db.add(trade)
        db.flush()

        portfolio.equity = _DEC(self.equity_now(db, portfolio))

        basis_text = "bid/ask" if fill.basis == "bid_ask" else "last+slippage"
        pnl_text = f", PnL {realized:+.2f}" if realized is not None else ""
        self._emit(
            db,
            ev.EVENT_ORDER_FILLED,
            (
                f"Fill: {order.side} {quantity:g} {order.symbol} @ {fill.price:.2f} "
                f"({basis_text}), fee ${fill.fee:.2f}{pnl_text}."
            ),
            symbol=order.symbol,
            payload={
                "order_id": order.id,
                "trade_id": trade.id,
                "price": fill.price,
                "fee": fill.fee,
                "basis": fill.basis,
                "quote_age_seconds": fill.quote_age_seconds,
                "data_liveness": fill.data_liveness,
                "realized_pnl": realized,
            },
        )
        return trade

    # -- protective exits ----------------------------------------------------------

    def check_protective_exits(
        self, db: Session, portfolio: PaperPortfolio
    ) -> list[PaperTrade]:
        """Auto-close positions whose entry order's stop/TP level was crossed.

        Protective exits belong to the approved entry order, so they execute
        without a new user approval — and they stay active under kill switch.
        """
        settings = self.settings_for(portfolio)
        trades: list[PaperTrade] = []
        for position in self._positions(db):
            entry_order = db.execute(
                select(PaperOrder)
                .where(
                    PaperOrder.portfolio_id == self.portfolio_id,
                    PaperOrder.symbol == position.symbol,
                    PaperOrder.side == "BUY",
                    PaperOrder.status == STATUS_FILLED,
                )
                .order_by(PaperOrder.filled_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if entry_order is None:
                continue

            quote = self.quotes.get(position.symbol)
            if quote is None or quote.last is None:
                continue
            last = float(quote.last)
            entry = float(position.avg_entry_price)

            trigger: str | None = None
            if entry_order.stop_loss_pct is not None:
                stop_price = entry * (1.0 - float(entry_order.stop_loss_pct) / 100.0)
                if last <= stop_price:
                    trigger = "stop_loss"
            if trigger is None and entry_order.take_profit_pct is not None:
                tp_price = entry * (1.0 + float(entry_order.take_profit_pct) / 100.0)
                if last >= tp_price:
                    trigger = "take_profit"
            if trigger is None:
                continue

            now = self._now_fn()
            event_type = (
                ev.EVENT_STOP_LOSS_HIT if trigger == "stop_loss" else ev.EVENT_TAKE_PROFIT_HIT
            )
            label = "Stop-loss" if trigger == "stop_loss" else "Take-profit"
            self._emit(
                db,
                event_type,
                f"{label} atingido em {position.symbol} (último {last:.2f}, entrada {entry:.2f}).",
                symbol=position.symbol,
                severity="warn",
                payload={"entry_order_id": entry_order.id, "last": last, "entry": entry},
            )

            protective = PaperOrder(
                portfolio_id=self.portfolio_id,
                symbol=position.symbol,
                side="SELL",
                quantity=position.quantity,
                order_type="market",
                status=STATUS_APPROVED,  # part of the approved entry order
                signal_snapshot={
                    "origin": "protective",
                    "trigger": trigger,
                    "parent_order_id": entry_order.id,
                },
                risk_snapshot={},
                data_liveness=quote.data_liveness,
                proposed_at=now,
                decided_at=now,
            )
            db.add(protective)
            db.flush()
            trade, _ = self.try_fill_order(db, portfolio, protective, settings=settings)
            if trade is not None:
                trades.append(trade)
        return trades

    # -- PnL / kill switch -----------------------------------------------------------

    def pnl_snapshot(self, db: Session, portfolio: PaperPortfolio) -> dict[str, float]:
        realized_today = sum(
            float(trade.realized_pnl)
            for trade in self._trades_today(db)
            if trade.realized_pnl is not None
        )
        fees_today = sum(float(trade.fee_paid) for trade in self._trades_today(db))
        unrealized = sum(
            (self._mark_price(pos) - float(pos.avg_entry_price)) * float(pos.quantity)
            for pos in self._positions(db)
        )
        equity = self.equity_now(db, portfolio)
        day_pnl = realized_today + unrealized
        return {
            "equity": equity,
            "cash": float(portfolio.cash),
            "unrealized_pnl": unrealized,
            "realized_pnl_today": realized_today,
            "fees_today": fees_today,
            "day_pnl": day_pnl,
            "trades_today": len(self._trades_today(db)),
        }

    def _check_kill_switch(
        self, db: Session, portfolio: PaperPortfolio, settings: RiskSettings
    ) -> None:
        if portfolio.kill_switch_active:
            return
        snapshot = self.pnl_snapshot(db, portfolio)
        day_start_equity = snapshot["equity"] - snapshot["day_pnl"]
        if daily_loss_breached(
            day_pnl=snapshot["day_pnl"],
            day_start_equity=day_start_equity,
            limit_pct=settings.daily_loss_limit_pct,
        ):
            portfolio.kill_switch_active = True
            portfolio.kill_switch_reason = (
                f"Perda diária de {snapshot['day_pnl']:+.2f} excedeu o limite de "
                f"{settings.daily_loss_limit_pct:.1f}% (${day_start_equity * settings.daily_loss_limit_pct / 100.0:,.2f})."
            )
            self._emit(
                db,
                ev.EVENT_KILL_SWITCH_ON,
                f"KILL SWITCH: {portfolio.kill_switch_reason}",
                severity="error",
                payload={"day_pnl": snapshot["day_pnl"]},
            )

    def reset_kill_switch(self, db: Session, portfolio: PaperPortfolio) -> None:
        portfolio.kill_switch_active = False
        portfolio.kill_switch_reason = None
        self._emit(db, ev.EVENT_KILL_SWITCH_OFF, "Kill switch rearmado manualmente.")

    # -- status -----------------------------------------------------------------------

    def status(
        self,
        db: Session,
        portfolio: PaperPortfolio,
        *,
        tracked_symbols: list[str],
        has_provider: bool = False,
    ) -> EngineStatus:
        settings = self.settings_for(portfolio)
        now = self._now_fn()
        session_now = market_session(now)
        age = self.quotes.freshest_age_seconds(tracked_symbols or None)
        if age is None:
            feed_status = "unavailable"
        elif age > settings.quote_max_age_seconds:
            feed_status = "stale"
        else:
            feed_status = "fresh"

        # Best-effort diagnosis so the cockpit can tell "broken" from "expected".
        feed_reason: str | None = None
        if feed_status != "fresh":
            if not portfolio.engine_running:
                feed_reason = "engine_stopped"
            elif not has_provider:
                feed_reason = "no_provider"
            elif session_now == "closed":
                feed_reason = "market_closed"
            else:
                feed_reason = "no_ticks"

        liveness = "UNKNOWN"
        for symbol in tracked_symbols:
            quote = self.quotes.get(symbol)
            if quote is not None:
                liveness = quote.data_liveness
                break

        pending = db.execute(
            select(PaperOrder).where(
                PaperOrder.portfolio_id == self.portfolio_id,
                PaperOrder.status == STATUS_PROPOSED,
            )
        ).scalars()
        cooldown = self.cooldown_until(db, settings)

        return EngineStatus(
            running=portfolio.engine_running,
            kill_switch_active=portfolio.kill_switch_active,
            kill_switch_reason=portfolio.kill_switch_reason,
            feed_status=feed_status,
            feed_reason=feed_reason,
            feed_age_seconds=age,
            data_liveness=liveness,
            market_session=session_now,
            tracked_symbols=tracked_symbols,
            pending_orders=len(list(pending)),
            cooldown_until=cooldown.isoformat() if cooldown else None,
            consecutive_losses=consecutive_losses(self._trades_today(db)),
            max_consecutive_losses=settings.max_consecutive_losses,
        )
