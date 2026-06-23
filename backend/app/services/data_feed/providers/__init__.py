from __future__ import annotations

from app.services.data_feed.types import MarketDataProvider


def build_provider(name: str) -> MarketDataProvider:
    """Instantiate a market data provider by configured name.

    Only ``yfinance`` ships in v1; IBKR and others can register here later
    without touching callers.
    """
    key = name.strip().lower()
    if key in {"yfinance", "yf"}:
        from app.services.data_feed.providers.yfinance_provider import YFinanceProvider

        return YFinanceProvider()

    raise ValueError(f"Unknown market data provider: {name!r}")
