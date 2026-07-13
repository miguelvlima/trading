from __future__ import annotations

from datetime import datetime

from app.services.execution_engine import apply_slippage, commission_for_order
from app.services.paper_trading.types import (
    FillComputation,
    FillDeferral,
    QuoteSnapshot,
    RiskSettings,
)


def compute_fill(
    *,
    side: str,
    quantity: float,
    quote: QuoteSnapshot | None,
    settings: RiskSettings,
    now: datetime,
) -> FillComputation | FillDeferral:
    """Simulate a market-order fill against the latest quote.

    Preferred basis is bid/ask (BUY pays the ask, SELL receives the bid), which
    prices the spread naturally — the probe showed delayed bid/ask are present
    and plausible. Falls back to last + fixed slippage; defers when the quote is
    missing, stale or the spread fails the sanity cap.
    """
    if quote is None:
        return FillDeferral(code="no_quote", reason="Sem cotação para o símbolo.")

    age = quote.age_seconds(now)
    if age > settings.quote_max_age_seconds:
        return FillDeferral(
            code="stale_quote",
            reason=f"Cotação obsoleta ({age:.0f}s > {settings.quote_max_age_seconds:.0f}s).",
        )

    spread_bps = quote.spread_bps()
    if quote.bid is not None and quote.ask is not None:
        if spread_bps is not None and spread_bps > settings.max_spread_bps:
            return FillDeferral(
                code="wide_spread",
                reason=(
                    f"Spread {spread_bps:.1f} bps acima do teto de sanidade "
                    f"({settings.max_spread_bps:.0f} bps)."
                ),
            )
        raw_price = float(quote.ask if side == "BUY" else quote.bid)
        basis = "bid_ask"
    elif quote.last is not None:
        raw_price = apply_slippage(float(quote.last), side, settings.slippage_bps / 10_000.0)
        basis = "last_slippage"
    else:
        return FillDeferral(code="no_quote", reason="Cotação sem preços utilizáveis.")

    if raw_price <= 0:
        return FillDeferral(code="no_quote", reason="Preço não positivo na cotação.")

    notional = raw_price * quantity
    fee = commission_for_order(
        fee_model=settings.fee_model,
        shares=quantity,
        notional=notional,
        fee_bps=settings.fee_bps,
    )
    return FillComputation(
        price=raw_price,
        basis=basis,
        fee=fee,
        quote_age_seconds=age,
        data_liveness=quote.data_liveness,
    )
