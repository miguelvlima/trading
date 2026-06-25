"""Market-data line budgeting for live subscriptions.

IBKR caps the number of simultaneous market-data "lines" (active ``reqMktData``
streams) — the operator environment reports ``API Max tickers = 100``. Every
followed symbol and every index in the bottom strip consumes one line, so a
session that opened a new line on each symbol switch without cancelling the old
one would exhaust the cap and the Gateway would start rejecting subscriptions.

:class:`SubscriptionManager` is the bookkeeping that prevents that. It is pure
(no IBKR calls): it tracks which keys are live and computes the minimal
add/remove diff to reach a desired set, enforcing the cap. The WebSocket session
applies that diff by calling the provider's ``subscribe``/``unsubscribe`` — so
the cancel-on-switch behaviour is centralised and unit-testable offline.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_MAX_LINES = 100


class LineBudgetExceeded(RuntimeError):
    """Raised when a desired subscription set would exceed the line cap."""

    def __init__(self, requested: int, max_lines: int) -> None:
        super().__init__(
            f"market-data line budget exceeded: {requested} requested, cap is {max_lines}"
        )
        self.requested = requested
        self.max_lines = max_lines


@dataclass(frozen=True)
class ReconcilePlan:
    """The minimal set of subscription changes to reach a desired state."""

    to_add: tuple[str, ...]
    to_remove: tuple[str, ...]

    @property
    def is_noop(self) -> bool:
        return not self.to_add and not self.to_remove


class SubscriptionManager:
    """Track active market-data lines and plan transitions within the cap.

    Keys are opaque uppercase strings; the session uses the symbol for followed
    instruments and the IBKR symbol (e.g. ``"SPX"``) for indices — both draw
    from the same budget, exactly as IBKR counts them.
    """

    def __init__(self, *, max_lines: int = DEFAULT_MAX_LINES) -> None:
        if max_lines < 1:
            raise ValueError("max_lines must be >= 1")
        self._max_lines = max_lines
        self._active: set[str] = set()

    @property
    def max_lines(self) -> int:
        return self._max_lines

    @property
    def active(self) -> frozenset[str]:
        return frozenset(self._active)

    @property
    def count(self) -> int:
        return len(self._active)

    @property
    def available(self) -> int:
        return self._max_lines - len(self._active)

    def has(self, key: str) -> bool:
        return key.upper() in self._active

    def plan(self, desired: set[str]) -> ReconcilePlan:
        """Compute the add/remove diff to move ``active`` to ``desired``.

        Cancellations are computed against the *final* set, so freeing a line by
        dropping an old symbol makes room for a new one in the same switch (the
        net count is what must fit the cap, not the transient peak).
        """
        wanted = {key.upper() for key in desired}
        if len(wanted) > self._max_lines:
            raise LineBudgetExceeded(len(wanted), self._max_lines)
        to_add = tuple(sorted(wanted - self._active))
        to_remove = tuple(sorted(self._active - wanted))
        return ReconcilePlan(to_add=to_add, to_remove=to_remove)

    def apply(self, plan: ReconcilePlan) -> None:
        """Commit a plan to the tracked state (call after the provider succeeds)."""
        for key in plan.to_remove:
            self._active.discard(key)
        for key in plan.to_add:
            self._active.add(key)

    def acquire(self, key: str) -> bool:
        """Reserve a line for ``key``. Returns False if already held; raises if full."""
        normalized = key.upper()
        if normalized in self._active:
            return False
        if len(self._active) >= self._max_lines:
            raise LineBudgetExceeded(len(self._active) + 1, self._max_lines)
        self._active.add(normalized)
        return True

    def release(self, key: str) -> bool:
        """Free the line for ``key``. Returns True if it was active."""
        normalized = key.upper()
        if normalized in self._active:
            self._active.discard(normalized)
            return True
        return False

    def clear(self) -> tuple[str, ...]:
        """Release every line and return what was active (for teardown)."""
        released = tuple(sorted(self._active))
        self._active.clear()
        return released
