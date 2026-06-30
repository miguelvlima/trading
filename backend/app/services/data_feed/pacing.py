from __future__ import annotations

import time
from collections.abc import Callable

import structlog

logger = structlog.get_logger(__name__)


class PacingThrottle:
    """Enforce a minimum interval between requests with simple exponential backoff.

    ``wait()`` blocks (via ``sleep_fn``) until at least ``min_interval_seconds``
    (plus any active backoff) have elapsed since the previous call. Call
    ``record_failure()`` after a provider error to grow the backoff, and
    ``record_success()`` to reset it. ``time_fn`` / ``sleep_fn`` are injectable
    so the throttle is deterministic under test.
    """

    def __init__(
        self,
        min_interval_seconds: float = 1.0,
        *,
        max_backoff_seconds: float = 60.0,
        time_fn: Callable[[], float] = time.monotonic,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        if min_interval_seconds < 0:
            raise ValueError("min_interval_seconds must be >= 0")
        if max_backoff_seconds < 0:
            raise ValueError("max_backoff_seconds must be >= 0")

        self._min_interval = float(min_interval_seconds)
        self._max_backoff = float(max_backoff_seconds)
        self._time_fn = time_fn
        self._sleep_fn = sleep_fn
        self._last_call: float | None = None
        self._backoff = 0.0

    @property
    def backoff_seconds(self) -> float:
        return self._backoff

    def wait(self) -> float:
        """Sleep until the next request is allowed. Returns seconds slept."""
        now = self._time_fn()
        slept = 0.0
        if self._last_call is not None:
            required = self._min_interval + self._backoff
            remaining = required - (now - self._last_call)
            if remaining > 0:
                self._sleep_fn(remaining)
                slept = remaining
        # Advance the logical clock deterministically by the amount we slept so
        # behaviour is identical whether sleep_fn truly blocks or is faked.
        self._last_call = now + slept
        return slept

    def record_success(self) -> None:
        self._backoff = 0.0

    def record_failure(self) -> float:
        """Grow the backoff (exponential, capped) and return the new value."""
        nxt = self._min_interval if self._backoff <= 0 else self._backoff * 2
        self._backoff = min(nxt, self._max_backoff)
        logger.warning("pacing_backoff_increased", backoff_seconds=self._backoff)
        return self._backoff
