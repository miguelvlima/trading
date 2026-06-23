from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user
from app.core.config import Settings, get_settings
from app.db.dependencies import get_db_session
from app.db.models import User
from app.schemas.realtime_data import (
    RealtimeHealthResponse,
    RealtimeQuoteResponse,
    SymbolMatchResponse,
)
from app.services.data_feed.providers import build_provider
from app.services.data_feed.service import DataFeedService, normalize_symbol
from app.services.data_feed.types import BarQuote, MarketDataProvider, timeframe_seconds

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/realtime", tags=["realtime"])

# Providers (e.g. yfinance) are cheap-but-stateful (pacing throttle); cache one
# per provider name so we reuse the throttle across requests.
_provider_cache: dict[str, MarketDataProvider] = {}


def get_provider(settings: Settings = Depends(get_settings)) -> MarketDataProvider:
    name = settings.realtime_feed_provider
    if name not in _provider_cache:
        _provider_cache[name] = build_provider(name)
    return _provider_cache[name]


def _quote_response(quote: BarQuote) -> RealtimeQuoteResponse:
    return RealtimeQuoteResponse(
        symbol=quote.symbol,
        timestamp=quote.timestamp,
        open=quote.open,
        high=quote.high,
        low=quote.low,
        close=quote.close,
        volume=quote.volume,
        is_final=quote.is_final,
    )


@router.get("/health", response_model=RealtimeHealthResponse)
def get_feed_health(
    symbol: str | None = Query(default=None, min_length=1, max_length=32),
    timeframe: str | None = Query(default=None, min_length=1, max_length=16),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> RealtimeHealthResponse:
    # Default to the configured tracked symbols/timeframe, but let the UI ask
    # about exactly what it is showing so the badge matches the chart.
    target_timeframe = timeframe or settings.realtime_feed_timeframe
    symbols = [symbol] if symbol else settings.realtime_feed_symbol_list

    # Staleness must scale with the timeframe: a 1d feed is naturally a day
    # "behind", so a flat 180s threshold would always read stale. We allow up to
    # 3 bar intervals (but never tighter than the configured minimum).
    interval_seconds = timeframe_seconds(target_timeframe)
    stale_after = settings.realtime_feed_stale_after_seconds
    if interval_seconds is not None:
        stale_after = max(stale_after, int(3 * interval_seconds))

    service = DataFeedService(db, provider_name=settings.realtime_feed_provider)
    health = service.get_health(
        symbols,
        target_timeframe,
        stale_after_seconds=stale_after,
    )
    return RealtimeHealthResponse(
        provider=health.provider,
        status=health.status,
        last_update=health.last_update,
        lag_seconds=health.lag_seconds,
        tracked_symbols=health.tracked_symbols,
        recent_errors=health.recent_errors,
    )


@router.get("/symbols/search", response_model=list[SymbolMatchResponse])
def search_symbols(
    q: str = Query(min_length=1, max_length=32),
    _: User = Depends(get_current_user),
    provider: MarketDataProvider = Depends(get_provider),
) -> list[SymbolMatchResponse]:
    # Symbol search is provider-specific (IBKR contract lookup); providers that
    # do not implement it simply return no matches.
    search = getattr(provider, "search_symbols", None)
    if not callable(search):
        return []
    try:
        matches = search(q)
    except Exception as exc:  # noqa: BLE001 - surface provider failures as 502
        logger.warning("realtime_symbol_search_error", query=q, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Provider error during symbol search.",
        ) from exc
    return [
        SymbolMatchResponse(
            symbol=match.symbol,
            name=match.name,
            sec_type=match.sec_type,
            exchange=match.exchange,
            currency=match.currency,
        )
        for match in matches
    ]


@router.get("/quote", response_model=RealtimeQuoteResponse)
def get_quote(
    symbol: str = Query(min_length=1, max_length=32),
    _: User = Depends(get_current_user),
    provider: MarketDataProvider = Depends(get_provider),
) -> RealtimeQuoteResponse:
    normalized = normalize_symbol(symbol)
    try:
        quote = provider.fetch_latest_quote(normalized)
    except Exception as exc:  # noqa: BLE001 - surface provider failures as 502
        logger.warning("realtime_quote_provider_error", symbol=normalized, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Provider error fetching quote for {normalized}.",
        ) from exc

    if quote is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No quote available for {normalized}.",
        )
    return _quote_response(quote)


@router.get("/history", response_model=list[RealtimeQuoteResponse])
def get_history(
    symbol: str = Query(min_length=1, max_length=32),
    timeframe: str = Query(default="1d", min_length=1, max_length=16),
    limit: int = Query(default=100, ge=1, le=5000),
    _: User = Depends(get_current_user),
    provider: MarketDataProvider = Depends(get_provider),
) -> list[RealtimeQuoteResponse]:
    normalized = normalize_symbol(symbol)
    try:
        bars = provider.fetch_recent_bars(normalized, timeframe, limit)
    except Exception as exc:  # noqa: BLE001 - surface provider failures as 502
        logger.warning("realtime_history_provider_error", symbol=normalized, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Provider error fetching history for {normalized}.",
        ) from exc
    return [_quote_response(bar) for bar in bars]
