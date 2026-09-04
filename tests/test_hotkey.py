"""Tests for hotkey parsing and the start/stop playback toggle.

No global hook is installed: the toggle is driven by calling it directly.
"""

import pytest

from macrologger.hotkey import (
    InvalidHotkeyError,
    PlaybackToggle,
    to_pynput_hotkey,
)


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("f8", "<f8>"),
        ("ctrl+shift+p", "<ctrl>+<shift>+p"),
        ("CTRL+P", "<ctrl>+p"),
        ("ctrl + p", "<ctrl>+p"),
        ("alt+f4", "<alt>+<f4>"),
        ("p", "p"),
    ],
)
def test_translates_specs_into_pynput_syntax(spec, expected):
    assert to_pynput_hotkey(spec) == expected


@pytest.mark.parametrize("spec", ["", "   ", "ctrl+", "+p", "ctrl++p"])
def test_rejects_malformed_specs(spec):
    with pytest.raises(InvalidHotkeyError):
        to_pynput_hotkey(spec)


def test_rejects_unknown_key_names():
    with pytest.raises(InvalidHotkeyError):
        to_pynput_hotkey("ctrl+nope")


class SpyRunner:
    """Captures playback start/stop instead of sending input."""

    def __init__(self):
        self.starts = 0
        self.stops = 0
        self.running = False

    def start(self):
        self.starts += 1
        self.running = True

    def stop(self):
        self.stops += 1
        self.running = False


def test_first_press_starts_playback():
    runner = SpyRunner()

    PlaybackToggle(runner.start, runner.stop).trigger()

    assert (runner.starts, runner.stops) == (1, 0)


def test_second_press_stops_playback():
    runner = SpyRunner()
    toggle = PlaybackToggle(runner.start, runner.stop)

    toggle.trigger()
    toggle.trigger()

    assert (runner.starts, runner.stops) == (1, 1)


def test_third_press_starts_again():
    runner = SpyRunner()
    toggle = PlaybackToggle(runner.start, runner.stop)

    for _ in range(3):
        toggle.trigger()

    assert (runner.starts, runner.stops) == (2, 1)


def test_reports_running_state():
    toggle = PlaybackToggle(lambda: None, lambda: None)

    assert toggle.running is False
    toggle.trigger()
    assert toggle.running is True


def test_playback_finishing_on_its_own_resets_the_toggle():
    """After a non-looping macro ends, the next press must start, not stop."""
    runner = SpyRunner()
    toggle = PlaybackToggle(runner.start, runner.stop)

    toggle.trigger()
    toggle.mark_finished()
    toggle.trigger()

    assert (runner.starts, runner.stops) == (2, 0)


def test_a_failing_start_does_not_leave_the_toggle_stuck_running():
    def explode():
        raise RuntimeError("backend gone")

    toggle = PlaybackToggle(explode, lambda: None)

    with pytest.raises(RuntimeError):
        toggle.trigger()

    assert toggle.running is False
