from __future__ import annotations

from app.services.data_feed.pacing import PacingThrottle


def _controlled_throttle(min_interval: float = 2.0):
    clock = {"t": 0.0}
    sleeps: list[float] = []

    def fake_time() -> float:
        return clock["t"]

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock["t"] += seconds

    throttle = PacingThrottle(
        min_interval_seconds=min_interval, time_fn=fake_time, sleep_fn=fake_sleep
    )
    return throttle, clock, sleeps


def test_first_call_does_not_wait() -> None:
    throttle, _clock, sleeps = _controlled_throttle()
    assert throttle.wait() == 0.0
    assert sleeps == []


def test_immediate_second_call_waits_full_interval() -> None:
    throttle, _clock, sleeps = _controlled_throttle(min_interval=2.0)
    throttle.wait()
    assert throttle.wait() == 2.0
    assert sleeps == [2.0]


def test_no_wait_when_enough_time_elapsed() -> None:
    throttle, clock, _sleeps = _controlled_throttle(min_interval=2.0)
    throttle.wait()
    clock["t"] += 5.0
    assert throttle.wait() == 0.0


def test_backoff_grows_and_resets() -> None:
    throttle, _clock, _sleeps = _controlled_throttle(min_interval=2.0)
    throttle.wait()

    assert throttle.record_failure() == 2.0
    assert throttle.record_failure() == 4.0  # exponential
    # Next immediate call waits interval + active backoff.
    assert throttle.wait() == 6.0

    throttle.record_success()
    assert throttle.backoff_seconds == 0.0


def test_backoff_is_capped() -> None:
    throttle = PacingThrottle(min_interval_seconds=1.0, max_backoff_seconds=3.0)
    for _ in range(10):
        throttle.record_failure()
    assert throttle.backoff_seconds == 3.0
