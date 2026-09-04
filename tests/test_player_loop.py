"""Tests for looping, per-loop timing jitter, and interruptible playback.

Backend, sleep, clock and RNG are all injected, so nothing real is sent and
no wall-clock time passes.
"""

import pytest

from macrologger.events import MacroEvent
from macrologger.player import Player

from test_player_timing import FakeBackend, FakeSleep


class FakeStopEvent:
    """Minimal stand-in for threading.Event."""

    def __init__(self, set_after=None):
        self._set = False
        self._checks = 0
        self._set_after = set_after

    def set(self):
        self._set = True

    def is_set(self):
        self._checks += 1
        if self._set_after is not None and self._checks > self._set_after:
            return True
        return self._set


class FakeRandom:
    """Returns a fixed fraction of the requested uniform range."""

    def __init__(self, fraction=1.0):
        self.fraction = fraction
        self.calls = []

    def uniform(self, low, high):
        self.calls.append((low, high))
        return high * self.fraction


def two_events():
    return [
        MacroEvent(0.0, "key", "down", "w", ""),
        MacroEvent(0.5, "key", "up", "w", ""),
    ]


def make_player(**kwargs):
    kwargs.setdefault("backend", FakeBackend())
    kwargs.setdefault("sleep", FakeSleep())
    kwargs.setdefault("clock", lambda: 0.0)
    return Player(**kwargs)


def test_loop_count_replays_the_macro_that_many_times():
    backend = FakeBackend()

    make_player(backend=backend).play(two_events(), loop=3)

    assert backend.calls.count(("keyDown", "w")) == 3


def test_default_plays_once():
    backend = FakeBackend()

    make_player(backend=backend).play(two_events())

    assert backend.calls.count(("keyDown", "w")) == 1


def test_loop_waits_the_gap_between_iterations():
    sleep = FakeSleep()

    make_player(sleep=sleep).play(two_events(), loop=2, loop_delay=1.5)

    assert [round(d, 3) for d in sleep.durations] == [0.5, 1.5, 0.5]


def test_jitter_scales_each_gap():
    sleep = FakeSleep()
    rng = FakeRandom(fraction=1.0)  # always the maximum of the range

    make_player(sleep=sleep).play(two_events(), jitter=0.1, rng=rng)

    # jitter=0.1 means +/-5%, so the top of the range is 0.5 * 1.05.
    assert [round(d, 4) for d in sleep.durations] == [0.525]
    assert rng.calls == [(-0.05, 0.05)]


def test_jitter_of_zero_reproduces_exact_gaps():
    sleep = FakeSleep()

    make_player(sleep=sleep).play(two_events(), jitter=0.0)

    assert [round(d, 4) for d in sleep.durations] == [0.5]


def test_jitter_never_produces_a_negative_gap():
    sleep = FakeSleep()
    rng = FakeRandom(fraction=-100.0)  # absurdly negative jitter

    make_player(sleep=sleep).play(two_events(), jitter=0.5, rng=rng)

    assert all(duration >= 0.0 for duration in sleep.durations)


def test_jitter_differs_between_loop_iterations():
    """Successive loops must not be byte-identical in timing."""
    sleep = FakeSleep()

    class Ramp:
        def __init__(self):
            self.n = 0

        def uniform(self, low, high):
            self.n += 1
            return high / self.n

    make_player(sleep=sleep).play(two_events(), loop=2, jitter=0.1, rng=Ramp())

    gaps = [d for d in sleep.durations if d > 0]
    assert gaps[0] != gaps[-1]


def test_loop_none_repeats_until_stopped():
    backend = FakeBackend()
    stop = StopAfterCalls(backend, 7)

    make_player(backend=backend, stop_event=stop).play(two_events(), loop=None)

    # Far more than one iteration, and it ended because the stop was requested.
    assert backend.calls.count(("keyDown", "w")) >= 3


def test_loop_none_without_a_stop_event_is_rejected():
    """Otherwise playback could never be stopped short of killing the process."""
    with pytest.raises(ValueError):
        make_player().play(two_events(), loop=None)


def test_negative_jitter_argument_is_rejected():
    with pytest.raises(ValueError):
        make_player().play(two_events(), jitter=-0.1)


def test_loop_below_one_is_rejected():
    with pytest.raises(ValueError):
        make_player().play(two_events(), loop=0)


def test_stop_event_ends_playback_between_events():
    backend = FakeBackend()
    stop = FakeStopEvent()
    stop.set()

    make_player(backend=backend, stop_event=stop).play(two_events(), loop=5)

    assert backend.calls == []


def test_stop_event_ends_looping_partway():
    backend = FakeBackend()
    stop = FakeStopEvent(set_after=3)

    make_player(backend=backend, stop_event=stop).play(two_events(), loop=100)

    assert 0 < backend.calls.count(("keyDown", "w")) < 100


def test_long_gaps_are_slept_in_slices_so_stop_stays_responsive():
    sleep = FakeSleep()
    stop = FakeStopEvent()
    events = [
        MacroEvent(0.0, "key", "down", "w", ""),
        MacroEvent(1.0, "key", "up", "w", ""),
    ]

    make_player(sleep=sleep, stop_event=stop).play(events)

    assert len(sleep.durations) > 1
    assert max(sleep.durations) <= 0.05
    assert round(sum(sleep.durations), 3) == 1.0


class StopAfterCalls:
    """Requests a stop once the backend has sent ``count`` events.

    Keyed off backend activity rather than internal check counts, so it does
    not break when the player's polling changes.
    """

    def __init__(self, backend, count):
        self._backend = backend
        self._count = count

    def is_set(self):
        return len(self._backend.calls) >= self._count


def test_held_keys_and_buttons_are_released_when_playback_is_stopped():
    """A stop must not leave W held down or the right button stuck in-game."""
    backend = FakeBackend()
    stop = StopAfterCalls(backend, 2)
    events = [
        MacroEvent(0.0, "key", "down", "w", ""),
        MacroEvent(0.1, "click", "down", "right", ""),
        MacroEvent(5.0, "click", "up", "right", ""),
        MacroEvent(5.5, "key", "up", "w", ""),
    ]

    make_player(backend=backend, stop_event=stop).play(events)

    # Stopped after w-down and right-down; both must be released on the way out.
    assert backend.calls == [
        ("keyDown", "w"),
        ("mouseDown", "right"),
        ("keyUp", "w"),
        ("mouseUp", "right"),
    ]


def test_nothing_is_released_when_the_macro_ends_cleanly():
    backend = FakeBackend()

    make_player(backend=backend).play(two_events())

    assert backend.calls == [("keyDown", "w"), ("keyUp", "w")]
