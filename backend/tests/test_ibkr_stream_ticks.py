"""Offline tests for IBKRStreamingProvider tick emission (no Gateway needed).

``_emit_tick`` normalizes IBKR tickType 8/74 volume — the session's CUMULATIVE
traded volume, which modern Gateways encode as a fixed-point integer in
micro-shares (observed live: ``13092042091247`` == 13,092,042.091247 shares) —
into shares, so downstream consumers never mix units. See ``Tick.volume`` in
``app.services.data_feed.types``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

from app.services.data_feed.providers.ibkr_provider import IBKRStreamingProvider
from app.services.data_feed.types import Tick


def _emit(ticker_fields: dict[str, object]) -> Tick:
    provider = IBKRStreamingProvider()
    captured: list[Tick] = []
    provider._on_tick = captured.append
    ticker = SimpleNamespace(**ticker_fields)
    provider._emit_tick("AMD", ticker, datetime(2026, 7, 9, 15, 2, 30, tzinfo=UTC))
    assert len(captured) == 1
    return captured[0]


def test_emit_tick_decodes_micro_share_cumulative_volume() -> None:
    # Wire value captured from a live Gateway (server version 176, delayed):
    # 13_092_042_091_247 micro-shares == 13,092,042.091247 shares.
    tick = _emit({"last": 553.15, "volume": 13_092_042_091_247})
    assert tick.symbol == "AMD"
    assert tick.last == Decimal("553.15")
    assert tick.volume == Decimal("13092042.091247")


def test_emit_tick_keeps_plain_share_volume_verbatim() -> None:
    # Values below the micro-encoding threshold are already plain shares.
    tick = _emit({"last": 208.9, "volume": 646_000})
    assert tick.volume == Decimal("646000")


def test_emit_tick_missing_or_nan_volume_stays_none() -> None:
    assert _emit({"last": 208.9, "volume": None}).volume is None
    assert _emit({"last": 208.9, "volume": float("nan")}).volume is None
    assert _emit({"last": 208.9}).volume is None
