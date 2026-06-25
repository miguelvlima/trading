"""Index/forex contracts shown in the Realtime bottom strip.

Each entry maps to its own IBKR contract and therefore its own ``reqMktData``
line — these count against the same ~100 line cap as followed symbols (see
:class:`app.services.data_feed.streaming.SubscriptionManager`). The exchange /
security-type values are the IBKR contract parameters; they only matter on the
real Gateway path and may need tuning per market-data entitlements.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IndexSpec:
    symbol: str  # IBKR symbol / subscription key
    name: str  # display label in the strip
    sec_type: str  # "IND" for cash indices, "CASH" for forex
    exchange: str
    currency: str = "USD"


# Order here is the strip's display order. EUR/USD is a forex (CASH) contract,
# not an index, but shares the strip and the line budget.
DEFAULT_INDICES: tuple[IndexSpec, ...] = (
    IndexSpec("SPX", "S&P 500", "IND", "CBOE"),
    IndexSpec("NDX", "Nasdaq 100", "IND", "NASDAQ"),
    IndexSpec("INDU", "Dow Jones", "IND", "CME"),
    IndexSpec("RUT", "Russell 2000", "IND", "RUSSELL"),
    IndexSpec("VIX", "VIX", "IND", "CBOE"),
    IndexSpec("EURUSD", "EUR/USD", "CASH", "IDEALPRO", "EUR"),
)

_BY_SYMBOL = {spec.symbol.upper(): spec for spec in DEFAULT_INDICES}


def index_specs() -> tuple[IndexSpec, ...]:
    return DEFAULT_INDICES


def index_spec(symbol: str) -> IndexSpec | None:
    return _BY_SYMBOL.get(symbol.upper())


def index_keys() -> list[str]:
    return [spec.symbol.upper() for spec in DEFAULT_INDICES]
