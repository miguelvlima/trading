from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, Query

from app.api.dependencies.auth import get_current_user
from app.api.routes.realtime_data import get_provider  # shared, cached provider
from app.db.models import User
from app.schemas.market_scanner import HotMoversResponse
from app.services.data_feed.hot_movers import compute_hot_movers
from app.services.data_feed.providers import build_provider
from app.services.data_feed.types import MarketDataProvider
from app.services.data_feed.universe import major_symbols

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/market-scanner", tags=["market-scanner"])

# The scanner is expensive (a scan + one history call per symbol, all serialised
# on the single IBKR thread), so cache the assembled response briefly.
_CACHE_TTL_SECONDS = 15.0
_cache: dict[tuple, tuple[float, HotMoversResponse]] = {}

# Cache the yfinance fallback provider so its pacing throttle persists.
_fallback_provider: MarketDataProvider | None = None


def _get_fallback_provider() -> MarketDataProvider:
    global _fallback_provider
    if _fallback_provider is None:
        _fallback_provider = build_provider("yfinance")
    return _fallback_provider


@router.get("/hot-movers", response_model=HotMoversResponse)
def get_hot_movers(
    limit: int = Query(default=10, ge=1, le=25),
    sort: Literal["change_pct", "rvol", "volume"] = Query(default="change_pct"),
    direction: Literal["up", "down", "both"] = Query(default="both"),
    min_price: float = Query(default=0.30, ge=0),
    _: User = Depends(get_current_user),
    provider: MarketDataProvider = Depends(get_provider),
) -> HotMoversResponse:
    """The 10 "hottest" symbols for the Mercado grid: each with a snapshot and a
    short sparkline. Falls back to yfinance over the curated universe when the
    IBKR scanner yields nothing (Gateway offline)."""
    key = (limit, sort, direction, round(min_price, 2))
    now = time.monotonic()
    cached = _cache.get(key)
    if cached is not None and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    items = compute_hot_movers(
        provider, limit=limit, sort=sort, direction=direction, min_price=min_price
    )

    if not items:
        # Graceful degradation: no scanner (or Gateway down) -> curated universe
        # via yfinance, so the grid still shows live-ish movers.
        fallback_symbols = [(major.symbol, major.name) for major in major_symbols()]
        items = compute_hot_movers(
            _get_fallback_provider(),
            limit=limit,
            sort=sort,
            direction=direction,
            min_price=min_price,
            symbols=fallback_symbols,
        )

    response = HotMoversResponse(as_of=datetime.now(UTC), sort=sort, items=items)
    _cache[key] = (now, response)
    return response
