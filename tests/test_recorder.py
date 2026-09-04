"""Tests for the recorder's clock normalization and event translation.

No real hardware or global hooks are touched: the clock, the window lookup and
the pynput key/button objects are all synthetic.
"""

import pytest

from macrologger.events import MacroEvent
from macrologger.recorder import (
    Recorder,
    UnsupportedInputError,
    button_to_code,
    key_to_code,
)


class FakeClock:
    """Deterministic stand-in for time.perf_counter()."""

    def __init__(self, ticks):
        self._ticks = list(ticks)

    def __call__(self):
        return self._ticks.pop(0)


class FakeKey:
    """Mimics pynput's KeyCode (has .char) or special Key (has .name)."""

    def __init__(self, char=None, name=None):
        self.char = char
        if name is not None:
            self.name = name


class FakeButton:
    def __init__(self, name):
        self.name = name


def make_recorder(ticks, window="Minecraft 1.21"):
    return Recorder(
        clock=FakeClock(ticks),
        window_provider=lambda: window,
        stop_code="esc",
    )


def test_first_event_is_at_time_zero():
    recorder = make_recorder([100.5, 100.9])

    recorder._on_key_press(FakeKey(char="w"))

    assert recorder.events[0].t == 0.0


def test_timestamps_are_relative_to_the_first_event():
    recorder = make_recorder([100.5, 100.912, 101.4])

    recorder._on_key_press(FakeKey(char="w"))
    recorder._on_key_release(FakeKey(char="w"))
    recorder._on_click(0, 0, FakeButton("right"), True)

    assert [round(event.t, 3) for event in recorder.events] == [0.0, 0.412, 0.9]


def test_key_press_and_release_are_recorded_with_window():
    recorder = make_recorder([5.0, 5.25])

    recorder._on_key_press(FakeKey(char="w"))
    recorder._on_key_release(FakeKey(char="w"))

    assert recorder.events == [
        MacroEvent(0.0, "key", "down", "w", "Minecraft 1.21"),
        MacroEvent(0.25, "key", "up", "w", "Minecraft 1.21"),
    ]


def test_click_press_and_release_are_recorded():
    recorder = make_recorder([1.0, 1.1])

    recorder._on_click(0, 0, FakeButton("left"), True)
    recorder._on_click(0, 0, FakeButton("left"), False)

    assert [(e.type, e.action, e.code) for e in recorder.events] == [
        ("click", "down", "left"),
        ("click", "up", "left"),
    ]


def test_mouse_movement_is_not_recorded_by_default():
    """Movement is opt-in; a default recording contains no move events."""
    recorder = make_recorder([1.0, 1.1, 1.2])

    recorder._on_move(100, 100)
    recorder._on_move(200, 200)

    assert recorder.record_movement is False
    assert recorder.events == []


def test_stop_key_stops_recording_and_is_not_recorded():
    recorder = make_recorder([1.0])

    result = recorder._on_key_press(FakeKey(name="esc"))

    assert result is False
    assert recorder.events == []
    assert recorder.stopped is True


def test_events_after_stop_are_ignored():
    recorder = make_recorder([1.0])

    recorder._on_key_press(FakeKey(name="esc"))
    recorder._on_key_press(FakeKey(char="w"))

    assert recorder.events == []


def test_clicks_after_stop_are_ignored():
    recorder = make_recorder([1.0])
    recorder.stopped = True

    result = recorder._on_click(0, 0, FakeButton("left"), True)

    assert result is False
    assert recorder.events == []


def test_window_lookup_failure_does_not_kill_the_listener():
    def boom():
        raise OSError("win32 exploded")

    recorder = Recorder(
        clock=FakeClock([1.0, 1.5]),
        window_provider=boom,
        stop_code="esc",
    )

    assert recorder._on_key_press(FakeKey(char="w")) is None
    assert recorder.events == []
    assert recorder.stopped is False


class FakeListener:
    """Stand-in for pynput's Listener, recording lifecycle calls."""

    def __init__(self, log, label, raise_on_join=None, **kwargs):
        self._log = log
        self._label = label
        self._raise_on_join = raise_on_join
        self.kwargs = kwargs

    def start(self):
        self._log.append(f"{self._label}.start")

    def stop(self):
        self._log.append(f"{self._label}.stop")

    def join(self):
        self._log.append(f"{self._label}.join")
        if self._raise_on_join is not None:
            raise self._raise_on_join

    def __enter__(self):
        self._log.append(f"{self._label}.enter")
        return self

    def __exit__(self, *exc_info):
        self._log.append(f"{self._label}.exit")
        return False


def install_fake_pynput(monkeypatch, log, raise_on_join=None):
    import sys
    import types

    keyboard = types.ModuleType("pynput.keyboard")
    keyboard.Listener = lambda **kw: FakeListener(
        log, "keyboard", raise_on_join=raise_on_join, **kw
    )
    mouse = types.ModuleType("pynput.mouse")
    mouse.Listener = lambda **kw: FakeListener(log, "mouse", **kw)
    package = types.ModuleType("pynput")
    package.keyboard = keyboard
    package.mouse = mouse

    monkeypatch.setitem(sys.modules, "pynput", package)
    monkeypatch.setitem(sys.modules, "pynput.keyboard", keyboard)
    monkeypatch.setitem(sys.modules, "pynput.mouse", mouse)


def test_record_starts_mouse_listener_and_joins_keyboard_listener(monkeypatch):
    log = []
    install_fake_pynput(monkeypatch, log)
    recorder = make_recorder([])

    assert recorder.record() == []
    assert log == [
        "mouse.start",
        "keyboard.enter",
        "keyboard.join",
        "keyboard.exit",
        "mouse.stop",
    ]


def test_record_stops_mouse_listener_even_when_keyboard_listener_raises(monkeypatch):
    log = []
    install_fake_pynput(monkeypatch, log, raise_on_join=RuntimeError("hook died"))
    recorder = make_recorder([])

    with pytest.raises(RuntimeError):
        recorder.record()

    assert log[0] == "mouse.start"
    assert log[-1] == "mouse.stop"


def test_request_stop_ends_recording_without_the_stop_key():
    """The UI needs a Stop button, not just the sentinel key."""
    recorder = make_recorder([1.0])

    recorder.request_stop()

    assert recorder.stopped is True


def test_request_stop_before_recording_starts_is_harmless():
    recorder = make_recorder([1.0])

    recorder.request_stop()  # no listeners exist yet

    assert recorder.stopped is True


def test_events_are_ignored_after_request_stop():
    recorder = make_recorder([1.0, 1.5])
    recorder.request_stop()

    recorder._on_key_press(FakeKey(char="w"))

    assert recorder.events == []


def test_key_to_code_maps_letters_digits_specials_and_modifiers():
    assert key_to_code(FakeKey(char="w")) == "w"
    assert key_to_code(FakeKey(char="W")) == "w"
    assert key_to_code(FakeKey(char="7")) == "7"
    assert key_to_code(FakeKey(char="/")) == "/"
    assert key_to_code(FakeKey(name="f5")) == "f5"
    assert key_to_code(FakeKey(name="shift_l")) == "shift"
    assert key_to_code(FakeKey(name="ctrl_r")) == "ctrl"
    assert key_to_code(FakeKey(name="alt_gr")) == "alt"
    assert key_to_code(FakeKey(name="space")) == "space"


def test_key_to_code_rejects_unknown_key():
    with pytest.raises(UnsupportedInputError):
        key_to_code(FakeKey())


def test_button_to_code_maps_the_three_buttons():
    assert button_to_code(FakeButton("left")) == "left"
    assert button_to_code(FakeButton("middle")) == "middle"
    assert button_to_code(FakeButton("right")) == "right"


def test_button_to_code_rejects_unknown_button():
    with pytest.raises(UnsupportedInputError):
        button_to_code(FakeButton("x2"))


def test_unsupported_key_is_skipped_not_fatal():
    recorder = make_recorder([1.0, 1.5])

    recorder._on_key_press(FakeKey())
    recorder._on_key_press(FakeKey(char="a"))

    assert [event.code for event in recorder.events] == ["a"]
