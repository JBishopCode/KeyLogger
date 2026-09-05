"""Tests for scroll-wheel capture and replay.

pydirectinput has no scroll function, so replay goes through a Win32 wheel
event; these pin both halves.
"""

import pytest

from macrologger.events import MacroEvent
from macrologger.player import Player
from macrologger.recorder import Recorder

from test_player_timing import FakeSleep


class FakeClock:
    def __init__(self, ticks):
        self._ticks = list(ticks)
        self.last = 0.0

    def __call__(self):
        if self._ticks:
            self.last = self._ticks.pop(0)
        return self.last


def make_recorder(ticks):
    return Recorder(
        clock=FakeClock(ticks),
        window_provider=lambda: "Minecraft 1.21",
        stop_code="esc",
    )


class ScrollBackend:
    def __init__(self):
        self.calls = []

    def keyDown(self, key, **kwargs):
        self.calls.append(("keyDown", key))

    def keyUp(self, key, **kwargs):
        self.calls.append(("keyUp", key))

    def mouseDown(self, x=None, y=None, button="primary", **kwargs):
        self.calls.append(("mouseDown", button))

    def mouseUp(self, x=None, y=None, button="primary", **kwargs):
        self.calls.append(("mouseUp", button))

    def move(self, xOffset=None, yOffset=None, relative=False, **kwargs):
        self.calls.append(("move", xOffset, yOffset))


def make_player(backend, scroll=None):
    return Player(
        backend=backend,
        sleep=FakeSleep(),
        clock=lambda: 0.0,
        scroll=scroll,
    )


# -- recording ---------------------------------------------------------


def test_scrolling_up_is_recorded():
    recorder = make_recorder([1.0])

    recorder._on_scroll(0, 0, 0, 1)

    event = recorder.events[0]
    assert (event.type, event.action) == ("scroll", "scroll")
    assert event.dy == 1


def test_scrolling_down_is_recorded():
    recorder = make_recorder([1.0])

    recorder._on_scroll(0, 0, 0, -2)

    assert recorder.events[0].dy == -2


def test_scroll_is_recorded_even_without_movement_enabled():
    """Hotbar scrolling is a discrete action, not mouse movement."""
    recorder = make_recorder([1.0])

    assert recorder.record_movement is False
    recorder._on_scroll(0, 0, 0, 1)

    assert len(recorder.events) == 1


def test_scroll_carries_the_window_title():
    recorder = make_recorder([1.0])

    recorder._on_scroll(0, 0, 0, 1)

    assert recorder.events[0].window == "Minecraft 1.21"


def test_scroll_after_stop_is_ignored():
    recorder = make_recorder([1.0])
    recorder.request_stop()

    recorder._on_scroll(0, 0, 0, 1)

    assert recorder.events == []


def test_zero_scroll_is_not_recorded():
    recorder = make_recorder([1.0])

    recorder._on_scroll(0, 0, 0, 0)

    assert recorder.events == []


# -- replay ------------------------------------------------------------


def test_scroll_events_are_sent_to_the_wheel_backend():
    sent = []
    backend = ScrollBackend()

    make_player(backend, scroll=lambda clicks: sent.append(clicks)).play(
        [MacroEvent(0.0, "scroll", "scroll", "", "", 0, 3)]
    )

    assert sent == [3]


def test_scroll_direction_is_preserved():
    sent = []
    backend = ScrollBackend()

    make_player(backend, scroll=lambda clicks: sent.append(clicks)).play(
        [MacroEvent(0.0, "scroll", "scroll", "", "", 0, -1)]
    )

    assert sent == [-1]


def test_scroll_interleaves_with_other_events_in_order():
    order = []
    backend = ScrollBackend()
    backend.calls = order

    events = [
        MacroEvent(0.0, "key", "down", "w", ""),
        MacroEvent(0.1, "scroll", "scroll", "", "", 0, 1),
        MacroEvent(0.2, "key", "up", "w", ""),
    ]
    make_player(backend, scroll=lambda clicks: order.append(("scroll", clicks))).play(
        events
    )

    assert order == [("keyDown", "w"), ("scroll", 1), ("keyUp", "w")]


def test_middle_click_still_replays_as_a_button():
    """Middle click is a button press, distinct from scrolling."""
    backend = ScrollBackend()

    make_player(backend, scroll=lambda clicks: None).play(
        [
            MacroEvent(0.0, "click", "down", "middle", ""),
            MacroEvent(0.1, "click", "up", "middle", ""),
        ]
    )

    assert backend.calls == [("mouseDown", "middle"), ("mouseUp", "middle")]


# -- Win32 wheel -------------------------------------------------------


def test_wheel_delta_converts_clicks_to_win32_units():
    from macrologger.backend import WHEEL_DELTA, wheel_delta_for

    assert wheel_delta_for(1) == WHEEL_DELTA
    assert wheel_delta_for(-2) == -2 * WHEEL_DELTA
    assert wheel_delta_for(0) == 0


def test_scroll_without_a_backend_raises_rather_than_silently_doing_nothing():
    backend = ScrollBackend()
    player = Player(backend=backend, sleep=FakeSleep(), clock=lambda: 0.0, scroll=None)
    player._scroll = None  # simulate an unavailable wheel backend

    with pytest.raises(Exception):
        player.play([MacroEvent(0.0, "scroll", "scroll", "", "", 0, 1)])
