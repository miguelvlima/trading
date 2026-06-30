"""Curated "majors" universe shown first in the symbol picker.

A small, stable set of large-cap stocks and broad ETFs that should always be
available to pick, independent of the live IBKR market scanner (which supplies
the dynamic "most active" discovery list). Keeping it here — not in config —
means the picker has a sensible default even before the Gateway is reachable.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MajorSymbol:
    symbol: str
    name: str


DEFAULT_MAJORS: tuple[MajorSymbol, ...] = (
    MajorSymbol("AAPL", "Apple"),
    MajorSymbol("MSFT", "Microsoft"),
    MajorSymbol("NVDA", "NVIDIA"),
    MajorSymbol("AMZN", "Amazon"),
    MajorSymbol("GOOGL", "Alphabet"),
    MajorSymbol("META", "Meta Platforms"),
    MajorSymbol("TSLA", "Tesla"),
    MajorSymbol("AMD", "AMD"),
    MajorSymbol("NFLX", "Netflix"),
    MajorSymbol("SPY", "S&P 500 ETF"),
    MajorSymbol("QQQ", "Nasdaq 100 ETF"),
)


def major_symbols() -> tuple[MajorSymbol, ...]:
    return DEFAULT_MAJORS
