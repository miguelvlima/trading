from __future__ import annotations

from app.core.config import Settings, get_settings
from app.services.data_feed.types import MarketDataProvider


def build_provider(name: str, settings: Settings | None = None) -> MarketDataProvider:
    """Instantiate a market data provider by configured name.

    ``yfinance`` is the default REST/polling provider (spec). ``ibkr`` is an
    optional provider backed by the IB Gateway; it is only imported when
    selected, so neither ``ib_insync`` nor a running Gateway is required
    otherwise. New providers register here without touching callers.
    """
    settings = settings or get_settings()
    key = name.strip().lower()

    if key in {"yfinance", "yf"}:
        from app.services.data_feed.providers.yfinance_provider import YFinanceProvider

        return YFinanceProvider(
            min_request_interval_seconds=settings.realtime_feed_min_request_interval_seconds
        )

    if key in {"ibkr", "ib"}:
        from app.services.data_feed.providers.ibkr_provider import IBKRProvider

        return IBKRProvider(
            host=settings.ibkr_gateway_host,
            port=settings.ibkr_gateway_port,
            client_id=settings.ibkr_client_id,
            min_request_interval_seconds=settings.realtime_feed_min_request_interval_seconds,
        )

    raise ValueError(f"Unknown market data provider: {name!r}")
