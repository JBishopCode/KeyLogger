"""Tests for replaying mouse movement as relative deltas.

Minecraft traps the cursor, so movement must be sent as relative motion; an
absolute moveTo would not steer the camera.
"""

import pytest

from macrologger.events import MacroEvent
from macrologger.player import Player

from test_player_timing import FakeSleep


class MoveBackend:
    """Mirrors pydirectinput's move signature: move(xOffset, yOffset)."""

    def __init__(self):
        self.calls = []
        self.relative_flags = []

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
        self.relative_flags.append(relative)

    def moveTo(self, x=None, y=None, **kwargs):  # must never be used
        self.calls.append(("moveTo", x, y))


def make_player(backend):
    return Player(backend=backend, sleep=FakeSleep(), clock=lambda: 0.0)


def test_move_events_are_sent_as_relative_offsets():
    backend = MoveBackend()

    make_player(backend).play([MacroEvent(0.0, "move", "move", "", "", 12, -4)])

    assert backend.calls == [("move", 12, -4)]


def test_move_is_sent_in_relative_mode():
    """pydirectinput.move defaults to relative=False, which computes an
    absolute target — Minecraft's trapped cursor ignores that."""
    backend = MoveBackend()

    make_player(backend).play([MacroEvent(0.0, "move", "move", "", "", 3, 3)])

    assert backend.relative_flags == [True]


def test_absolute_positioning_is_never_used():
    """moveTo would fight Minecraft's trapped cursor."""
    backend = MoveBackend()

    make_player(backend).play([MacroEvent(0.0, "move", "move", "", "", 5, 5)])

    assert not any(call[0] == "moveTo" for call in backend.calls)


def test_movement_interleaves_with_keys_and_clicks_in_order():
    backend = MoveBackend()
    events = [
        MacroEvent(0.0, "key", "down", "w", ""),
        MacroEvent(0.1, "move", "move", "", "", 10, 0),
        MacroEvent(0.2, "click", "down", "right", ""),
        MacroEvent(0.3, "move", "move", "", "", -5, 3),
        MacroEvent(0.4, "key", "up", "w", ""),
    ]

    make_player(backend).play(events)

    assert backend.calls == [
        ("keyDown", "w"),
        ("move", 10, 0),
        ("mouseDown", "right"),
        ("move", -5, 3),
        ("keyUp", "w"),
        # The macro never releases right-click, so cleanup does it on the way
        # out rather than leaving the button stuck down in-game.
        ("mouseUp", "right"),
    ]


def test_movement_honours_recorded_gaps():
    backend = MoveBackend()
    sleep = FakeSleep()
    events = [
        MacroEvent(0.0, "move", "move", "", "", 1, 1),
        MacroEvent(0.25, "move", "move", "", "", 2, 2),
    ]

    Player(backend=backend, sleep=sleep, clock=lambda: 0.0).play(events)

    assert [round(d, 3) for d in sleep.durations] == [0.25]


def test_a_backend_without_relative_move_fails_before_sending_anything():
    """Resolved up front, like unknown key codes, so replay is all-or-nothing."""

    class NoMoveBackend(MoveBackend):
        move = None

    backend = NoMoveBackend()

    with pytest.raises(Exception):
        make_player(backend).play(
            [
                MacroEvent(0.0, "key", "down", "w", ""),
                MacroEvent(0.1, "move", "move", "", "", 1, 1),
            ]
        )

    assert backend.calls == []


def test_held_keys_still_released_when_a_macro_contains_movement():
    backend = MoveBackend()

    class AlwaysStop:
        def is_set(self):
            return len(backend.calls) >= 2

    player = Player(
        backend=backend, sleep=FakeSleep(), clock=lambda: 0.0, stop_event=AlwaysStop()
    )
    player.play(
        [
            MacroEvent(0.0, "key", "down", "w", ""),
            MacroEvent(0.1, "move", "move", "", "", 10, 0),
            MacroEvent(5.0, "key", "up", "w", ""),
        ]
    )

    assert ("keyUp", "w") in backend.calls
