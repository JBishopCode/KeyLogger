"""Tests for optional mouse-movement recording.

Movement is off by default. When on, it is sampled as relative deltas at a
capped rate: raw pynput movement fires hundreds of times a second and would
bloat the macro file for no fidelity gain.
"""

from macrologger.recorder import Recorder


class FakeClock:
    def __init__(self, ticks):
        self._ticks = list(ticks)
        self.last = 0.0

    def __call__(self):
        if self._ticks:
            self.last = self._ticks.pop(0)
        return self.last


def make_recorder(ticks, record_movement=True, interval=0.05):
    return Recorder(
        clock=FakeClock(ticks),
        window_provider=lambda: "Minecraft 1.21",
        stop_code="esc",
        record_movement=record_movement,
        move_interval=interval,
    )


def test_movement_is_off_by_default():
    recorder = Recorder(clock=FakeClock([0.0]), window_provider=lambda: "")

    assert recorder.record_movement is False


def test_disabled_recorder_ignores_movement():
    recorder = make_recorder([0.0, 0.1], record_movement=False)

    recorder._on_move(100, 100)
    recorder._on_move(140, 130)

    assert recorder.events == []


def test_first_movement_establishes_the_origin_without_an_event():
    """There is no delta until a second position is known."""
    recorder = make_recorder([0.0, 0.1])

    recorder._on_move(100, 100)

    assert recorder.events == []


def test_movement_is_recorded_as_a_relative_delta():
    recorder = make_recorder([0.0, 0.1])

    recorder._on_move(100, 100)
    recorder._on_move(140, 130)

    event = recorder.events[0]
    assert (event.type, event.action) == ("move", "move")
    assert (event.dx, event.dy) == (40, 30)


def test_deltas_are_relative_to_the_previous_sample():
    recorder = make_recorder([0.0, 0.1, 0.2])

    recorder._on_move(100, 100)
    recorder._on_move(110, 100)
    recorder._on_move(130, 90)

    assert [(e.dx, e.dy) for e in recorder.events] == [(10, 0), (20, -10)]


def test_movement_faster_than_the_interval_is_throttled():
    # Samples at 0.00, 0.01, 0.02 with a 0.05s interval: too fast to record.
    recorder = make_recorder([0.0, 0.01, 0.02], interval=0.05)

    recorder._on_move(100, 100)
    recorder._on_move(110, 100)
    recorder._on_move(120, 100)

    assert recorder.events == []


def test_throttled_movement_still_accumulates_the_full_delta():
    """Skipped samples must not lose distance, or replay drifts."""
    recorder = make_recorder([0.0, 0.01, 0.02, 0.2], interval=0.05)

    recorder._on_move(100, 100)
    recorder._on_move(110, 100)
    recorder._on_move(120, 100)
    recorder._on_move(130, 100)

    assert [(e.dx, e.dy) for e in recorder.events] == [(30, 0)]


def test_zero_movement_is_not_recorded():
    recorder = make_recorder([0.0, 0.1, 0.2])

    recorder._on_move(100, 100)
    recorder._on_move(100, 100)

    assert recorder.events == []


def test_movement_after_stop_is_ignored():
    recorder = make_recorder([0.0, 0.1, 0.2])
    recorder._on_move(100, 100)
    recorder.stopped = True

    recorder._on_move(200, 200)

    assert recorder.events == []


def test_movement_events_carry_the_window_title():
    recorder = make_recorder([0.0, 0.1])

    recorder._on_move(100, 100)
    recorder._on_move(120, 120)

    assert recorder.events[0].window == "Minecraft 1.21"
