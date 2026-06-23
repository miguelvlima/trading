"""Continuous real-time market data feed worker.

Polls the configured provider for each tracked symbol and upserts normalized
bars into ``market_bars`` via :class:`DataFeedService`. Configuration comes from
the ``REALTIME_FEED_*`` settings (see ``backend/.env.example``).

Run locally with:

    cd backend
    python -m app.scripts.run_realtime_feed

Stop cleanly with Ctrl+C.
"""

from __future__ import annotations

import signal
import threading
from types import FrameType

import structlog

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.services.data_feed.providers import build_provider
from app.services.data_feed.service import DataFeedService

logger = structlog.get_logger(__name__)

_stop_event = threading.Event()


def _handle_stop(signum: int, _frame: FrameType | None) -> None:
    logger.info("realtime_feed_stop_requested", signal=signum)
    _stop_event.set()


def _poll_once(
    provider,
    symbols: list[str],
    timeframe: str,
    history_limit: int,
) -> None:
    for symbol in symbols:
        if _stop_event.is_set():
            return
        session = SessionLocal()
        service = DataFeedService(session, provider_name=provider.name)
        try:
            quotes = provider.fetch_recent_bars(symbol, timeframe, history_limit)
            if not quotes:
                logger.info("realtime_feed_no_data", symbol=symbol, timeframe=timeframe)
                continue
            result = service.ingest_bars(symbol, timeframe, quotes)
            logger.info(
                "realtime_feed_symbol_ingested",
                symbol=result.symbol,
                timeframe=result.timeframe,
                inserted=result.inserted,
                updated=result.updated,
            )
        except Exception as exc:  # noqa: BLE001 - keep the loop alive on per-symbol errors
            session.rollback()
            service.record_error(f"{symbol}: {exc}")
            logger.error("realtime_feed_symbol_error", symbol=symbol, error=str(exc))
        finally:
            session.close()


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    symbols = settings.realtime_feed_symbol_list
    timeframe = settings.realtime_feed_timeframe
    poll_seconds = settings.realtime_feed_poll_seconds
    history_limit = 100

    if not symbols:
        logger.error("realtime_feed_no_symbols_configured")
        return

    provider = build_provider(settings.realtime_feed_provider)

    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    logger.info(
        "realtime_feed_started",
        provider=provider.name,
        symbols=symbols,
        timeframe=timeframe,
        poll_seconds=poll_seconds,
    )

    while not _stop_event.is_set():
        _poll_once(provider, symbols, timeframe, history_limit)
        if _stop_event.is_set():
            break
        # Sleep between polling cycles, but stay responsive to stop requests.
        _stop_event.wait(timeout=poll_seconds)

    logger.info("realtime_feed_stopped")


if __name__ == "__main__":
    main()
