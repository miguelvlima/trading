"""Build the "hot movers" snapshot for the Mercado grid.

Reuses the provider's scanner (ranked symbols) and ``fetch_recent_bars`` (which
already goes through the PacingThrottle) to derive a small snapshot + sparkline
per symbol. Provider-agnostic so it works against the real IBKR provider and the
test FakeProvider alike.
"""

from __future__ import annotations

from decimal import Decimal

import structlog

from app.schemas.market_scanner import HotMover, HotMoverSpark

logger = structlog.get_logger(__name__)

# Short intraday series for the sparkline + intraday change. "1 D" of 5m bars is
# ~a session (>= SPARK_POINTS) and keeps each request light.
SPARK_INTERVAL = "5m"
SPARK_POINTS = 30
_FETCH_BARS = max(SPARK_POINTS + 1, 40)
_SPARK_DURATION = "1 D"


def _bars_for(provider: object, symbols: list[str]) -> dict[str, list]:
    """Recent bars per symbol — concurrently when the provider supports it
    (IBKR), else one request at a time (FakeProvider / yfinance)."""
    batch = getattr(provider, "fetch_recent_bars_batch", None)
    if callable(batch):
        return batch(symbols, SPARK_INTERVAL, _FETCH_BARS, duration=_SPARK_DURATION)
    out: dict[str, list] = {}
    for symbol in symbols:
        out[symbol] = provider.fetch_recent_bars(symbol, SPARK_INTERVAL, _FETCH_BARS)
    return out


def _scan_code(sort: str, direction: str) -> str:
    """Map the UI sort/direction onto an IBKR scanner scan code."""
    if sort == "change_pct" and direction == "up":
        return "TOP_PERC_GAIN"
    if sort == "change_pct" and direction == "down":
        return "TOP_PERC_LOSE"
    if sort == "rvol":
        return "HOT_BY_VOLUME"
    return "MOST_ACTIVE"


def _scan_symbols(provider: object, scan_code: str, count: int) -> list[tuple[str, str | None]]:
    """Ranked (symbol, name) candidates from the provider's scanner.

    Prefers ``scan_movers(scan_code, count)`` (direction-aware) and falls back to
    ``scan_active(count)`` for providers/doubles that only expose most-active.
    """
    scan_movers = getattr(provider, "scan_movers", None)
    matches = None
    if callable(scan_movers):
        matches = scan_movers(scan_code, count)
    else:
        scan_active = getattr(provider, "scan_active", None)
        if callable(scan_active):
            matches = scan_active(count)
    return [(m.symbol, m.name) for m in (matches or [])]


def compute_hot_movers(
    provider: object,
    *,
    limit: int,
    sort: str,
    direction: str,
    min_price: float,
    symbols: list[tuple[str, str | None]] | None = None,
) -> list[HotMover]:
    """Build up to ``limit`` HotMover snapshots, filtered and sorted.

    ``symbols`` bypasses the scanner (used by the graceful yfinance fallback).
    """
    candidates = symbols if symbols is not None else _scan_symbols(provider, _scan_code(sort, direction), limit)

    try:
        bars_by_symbol = _bars_for(provider, [symbol for symbol, _ in candidates])
    except Exception as exc:  # noqa: BLE001 - a scanner/batch failure must not 500
        logger.warning("hot_movers_bars_failed", error=str(exc))
        bars_by_symbol = {}

    items: list[HotMover] = []
    for symbol, name in candidates:
        bars = bars_by_symbol.get(symbol) or bars_by_symbol.get(symbol.upper())
        if not bars:
            continue

        closes = [float(bar.close) for bar in bars]
        last = bars[-1].close
        if float(last) < min_price:
            continue
        first_open = float(bars[0].open) or float(last)
        change = ((float(last) - first_open) / first_open * 100) if first_open else 0.0
        volume = sum(int(bar.volume) for bar in bars)

        items.append(
            HotMover(
                symbol=symbol,
                name=name,
                last=last,
                change_pct=Decimal(str(round(change, 2))),
                volume=volume,
                rel_volume=None,  # 20d RVol omitted to respect IBKR pacing (see notes)
                spark=HotMoverSpark(points=closes[-SPARK_POINTS:], interval=SPARK_INTERVAL),
            )
        )

    if direction == "up":
        items = [i for i in items if i.change_pct >= 0]
    elif direction == "down":
        items = [i for i in items if i.change_pct < 0]

    if sort == "volume":
        items.sort(key=lambda i: i.volume, reverse=True)
    elif sort == "rvol":
        items.sort(key=lambda i: i.rel_volume or Decimal(0), reverse=True)
    elif direction == "down":
        items.sort(key=lambda i: i.change_pct)  # biggest drops first
    elif direction == "up":
        items.sort(key=lambda i: i.change_pct, reverse=True)
    else:
        items.sort(key=lambda i: abs(i.change_pct), reverse=True)

    return items[:limit]
