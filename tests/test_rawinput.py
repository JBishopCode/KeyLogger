"""Tests for Win32 raw-mouse decoding.

Raw Input reports true device deltas, unaffected by a game recentring the
cursor. Only the decoding is tested here; the message pump needs a window.
"""

from macrologger.rawinput import (
    MOUSE_MOVE_ABSOLUTE,
    MOUSE_MOVE_RELATIVE,
    RIM_TYPEMOUSE,
    RawMouseListener,
    parse_raw_mouse,
)


class FakeRawInput:
    """Stands in for the RAWINPUT structure ctypes hands back."""

    class _Header:
        def __init__(self, dwType):
            self.dwType = dwType

    class _Mouse:
        def __init__(self, flags, last_x, last_y):
            self.usFlags = flags
            self.lLastX = last_x
            self.lLastY = last_y

    class _Data:
        def __init__(self, mouse):
            self.mouse = mouse

    def __init__(self, dwType=RIM_TYPEMOUSE, flags=MOUSE_MOVE_RELATIVE, dx=0, dy=0):
        self.header = self._Header(dwType)
        self.data = self._Data(self._Mouse(flags, dx, dy))


def test_relative_movement_is_decoded():
    raw = FakeRawInput(dx=12, dy=-7)

    assert parse_raw_mouse(raw) == (12, -7)


def test_zero_movement_decodes_to_zero():
    assert parse_raw_mouse(FakeRawInput(dx=0, dy=0)) == (0, 0)


def test_absolute_packets_are_ignored():
    """Some devices (tablets, RDP, some VMs) report absolute coordinates.

    Those are screen positions, not deltas; treating them as deltas would
    fling the camera across the world.
    """
    raw = FakeRawInput(flags=MOUSE_MOVE_ABSOLUTE, dx=1024, dy=768)

    assert parse_raw_mouse(raw) is None


def test_non_mouse_packets_are_ignored():
    raw = FakeRawInput(dwType=1, dx=5, dy=5)  # RIM_TYPEKEYBOARD

    assert parse_raw_mouse(raw) is None


def test_listener_forwards_decoded_deltas_to_the_callback():
    seen = []
    listener = RawMouseListener(on_move=lambda dx, dy: seen.append((dx, dy)))

    listener._handle_raw(FakeRawInput(dx=3, dy=4))

    assert seen == [(3, 4)]


def test_listener_skips_zero_deltas():
    seen = []
    listener = RawMouseListener(on_move=lambda dx, dy: seen.append((dx, dy)))

    listener._handle_raw(FakeRawInput(dx=0, dy=0))

    assert seen == []


def test_listener_skips_absolute_packets():
    seen = []
    listener = RawMouseListener(on_move=lambda dx, dy: seen.append((dx, dy)))

    listener._handle_raw(FakeRawInput(flags=MOUSE_MOVE_ABSOLUTE, dx=500, dy=500))

    assert seen == []


def test_listener_survives_a_failing_callback():
    """A raised callback must not kill the message pump."""

    def boom(dx, dy):
        raise RuntimeError("nope")

    listener = RawMouseListener(on_move=boom)

    listener._handle_raw(FakeRawInput(dx=1, dy=1))  # must not raise


def test_listener_reports_whether_it_is_running():
    listener = RawMouseListener(on_move=lambda dx, dy: None)

    assert listener.running is False
