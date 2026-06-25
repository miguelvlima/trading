from __future__ import annotations

import pytest

from app.services.data_feed.streaming import (
    LineBudgetExceeded,
    SubscriptionManager,
)


def test_acquire_and_release_tracks_count() -> None:
    mgr = SubscriptionManager(max_lines=5)
    assert mgr.count == 0

    assert mgr.acquire("aapl") is True
    assert mgr.has("AAPL") is True
    assert mgr.count == 1
    # idempotent: re-acquiring an active key is a no-op, not a new line.
    assert mgr.acquire("AAPL") is False
    assert mgr.count == 1

    assert mgr.release("AAPL") is True
    assert mgr.release("AAPL") is False
    assert mgr.count == 0


def test_acquire_raises_when_budget_full() -> None:
    mgr = SubscriptionManager(max_lines=2)
    mgr.acquire("A")
    mgr.acquire("B")
    with pytest.raises(LineBudgetExceeded):
        mgr.acquire("C")
    # The failed acquire must not have leaked a line.
    assert mgr.count == 2


def test_plan_diffs_to_desired_set() -> None:
    mgr = SubscriptionManager(max_lines=10)
    mgr.acquire("AAPL")
    mgr.acquire("SPX")

    plan = mgr.plan({"MSFT", "SPX"})
    # AAPL dropped, MSFT added, SPX kept; index/symbol share the budget.
    assert plan.to_add == ("MSFT",)
    assert plan.to_remove == ("AAPL",)
    assert plan.is_noop is False


def test_plan_is_noop_when_already_satisfied() -> None:
    mgr = SubscriptionManager(max_lines=10)
    mgr.acquire("AAPL")
    plan = mgr.plan({"aapl"})
    assert plan.is_noop is True


def test_switch_frees_old_line_for_new_within_cap() -> None:
    """The crux of the line cap: swapping symbols at the cap must succeed.

    Cancellations net against additions, so a full budget can switch the active
    symbol without ever exceeding the cap (no orphan accumulation).
    """
    mgr = SubscriptionManager(max_lines=3)
    for key in ("AAPL", "SPX", "VIX"):
        mgr.acquire(key)
    assert mgr.available == 0

    # Move from AAPL to MSFT while keeping both indices — still 3 lines.
    plan = mgr.plan({"MSFT", "SPX", "VIX"})
    assert plan.to_add == ("MSFT",)
    assert plan.to_remove == ("AAPL",)

    mgr.apply(plan)
    assert mgr.active == frozenset({"MSFT", "SPX", "VIX"})
    assert mgr.count == 3


def test_plan_rejects_desired_set_larger_than_cap() -> None:
    mgr = SubscriptionManager(max_lines=2)
    with pytest.raises(LineBudgetExceeded):
        mgr.plan({"A", "B", "C"})


def test_apply_then_clear() -> None:
    mgr = SubscriptionManager(max_lines=5)
    mgr.apply(mgr.plan({"A", "B"}))
    assert mgr.count == 2
    released = mgr.clear()
    assert released == ("A", "B")
    assert mgr.count == 0
