"""Tests for replay timing and the code -> DirectInput mapping.

The input backend, sleep and clock are all mocked: no real input is sent.
"""

import pytest

from macrologger.events import MacroEvent
from macrologger.player import (
    Player,
    UnknownCodeError,
    code_to_button,
    code_to_key,
)


class FakeBackend:
    """Records calls, mirroring the real pydirectinput signatures.

    ``mouseDown``/``mouseUp`` take ``x`` first and ``button`` third, so a
    positionally-passed button lands in ``x`` and is treated as a coordinate.
    The fakes reproduce that trap deliberately.
    """

    def __init__(self):
        self.calls = []
        self.moved = []

    def keyDown(self, key, logScreenshot=None, _pause=True):
        self.calls.append(("keyDown", key))

    def keyUp(self, key, logScreenshot=None, _pause=True):
        self.calls.append(("keyUp", key))

    def mouseDown(self, x=None, y=None, button="primary", **kwargs):
        self._record_mouse("mouseDown", x, y, button)

    def mouseUp(self, x=None, y=None, button="primary", **kwargs):
        self._record_mouse("mouseUp", x, y, button)

    def _record_mouse(self, name, x, y, button):
        if x is not None or y is not None:
            self.moved.append((x, y))
        self.calls.append((name, button))


class FakeSleep:
    def __init__(self):
        self.durations = []

    def __call__(self, seconds):
        self.durations.append(seconds)


def make_player(backend=None, sleep=None, clock=None):
    return Player(
        backend=backend or FakeBackend(),
        sleep=sleep or FakeSleep(),
        clock=clock or (lambda: 0.0),
    )


def test_sleeps_the_recorded_inter_event_gaps():
    sleep = FakeSleep()
    player = make_player(sleep=sleep)
    events = [
        MacroEvent(0.0, "key", "down", "w", ""),
        MacroEvent(0.412, "key", "up", "w", ""),
        MacroEvent(0.9, "click", "down", "right", ""),
    ]

    player.play(events)

    assert [round(d, 3) for d in sleep.durations] == [0.412, 0.488]


def test_does_not_sleep_before_the_first_event():
    sleep = FakeSleep()

    make_player(sleep=sleep).play([MacroEvent(0.0, "key", "down", "w", "")])

    assert sleep.durations == []


def test_leading_offset_is_not_replayed_as_a_delay():
    sleep = FakeSleep()
    events = [
        MacroEvent(5.0, "key", "down", "w", ""),
        MacroEvent(5.5, "key", "up", "w", ""),
    ]

    make_player(sleep=sleep).play(events)

    assert [round(d, 3) for d in sleep.durations] == [0.5]


def test_negative_gaps_never_sleep_backwards():
    sleep = FakeSleep()
    events = [
        MacroEvent(1.0, "key", "down", "w", ""),
        MacroEvent(0.5, "key", "up", "w", ""),
    ]

    make_player(sleep=sleep).play(events)

    assert sleep.durations == [0.0]


def test_backend_is_called_in_recorded_order():
    backend = FakeBackend()
    events = [
        MacroEvent(0.0, "key", "down", "w", ""),
        MacroEvent(0.1, "click", "down", "right", ""),
        MacroEvent(0.2, "click", "up", "right", ""),
        MacroEvent(0.3, "key", "up", "w", ""),
    ]

    make_player(backend=backend).play(events)

    assert backend.calls == [
        ("keyDown", "w"),
        ("mouseDown", "right"),
        ("mouseUp", "right"),
        ("keyUp", "w"),
    ]


def test_clicks_pass_the_button_by_keyword_not_as_a_coordinate():
    """pydirectinput's first positional parameter is x, not button."""
    backend = FakeBackend()

    make_player(backend=backend).play(
        [
            MacroEvent(0.0, "click", "down", "right", ""),
            MacroEvent(0.1, "click", "up", "right", ""),
        ]
    )

    assert backend.calls == [("mouseDown", "right"), ("mouseUp", "right")]


def test_replay_never_moves_the_mouse():
    backend = FakeBackend()

    make_player(backend=backend).play(
        [MacroEvent(0.0, "click", "down", "left", "")]
    )

    assert backend.moved == []


def test_empty_event_list_is_a_no_op():
    backend = FakeBackend()
    sleep = FakeSleep()

    make_player(backend=backend, sleep=sleep).play([])

    assert backend.calls == []
    assert sleep.durations == []


@pytest.mark.parametrize("code", list("abcdefghijklmnopqrstuvwxyz0123456789"))
def test_mapping_covers_letters_and_digits(code):
    assert code_to_key(code) == code


@pytest.mark.parametrize("n", range(1, 13))
def test_mapping_covers_function_keys(n):
    assert code_to_key(f"f{n}") == f"f{n}"


@pytest.mark.parametrize(
    ("code", "expected"),
    [("shift", "shift"), ("ctrl", "ctrl"), ("alt", "alt"), ("space", "space")],
)
def test_mapping_covers_modifiers_and_space(code, expected):
    assert code_to_key(code) == expected


@pytest.mark.parametrize("code", ["left", "right", "middle"])
def test_mapping_covers_mouse_buttons(code):
    assert code_to_button(code) == code


def test_every_mapped_key_exists_in_pydirectinput():
    """Guards against a code -> key name that the real backend would ignore."""
    pydirectinput = pytest.importorskip("pydirectinput")

    from macrologger.player import KEY_MAP

    unmapped = [
        name
        for name in set(KEY_MAP.values())
        if pydirectinput.KEYBOARD_MAPPING.get(name) is None
    ]

    assert unmapped == []


def test_unknown_key_code_raises():
    with pytest.raises(UnknownCodeError):
        code_to_key("nope")


def test_unknown_button_code_raises():
    with pytest.raises(UnknownCodeError):
        code_to_button("x2")


def test_play_raises_on_unknown_code_before_sending_anything():
    backend = FakeBackend()

    with pytest.raises(UnknownCodeError):
        make_player(backend=backend).play([MacroEvent(0.0, "key", "down", "nope", "")])

    assert backend.calls == []
