"""Tests for the always-on-top overlay's Win32 styling and display model.

No window is created: the Win32 calls are faked and the model is pure.
"""

import pytest

from macrologger.overlay import (
    WS_EX_LAYERED,
    WS_EX_NOACTIVATE,
    WS_EX_TOOLWINDOW,
    WS_EX_TOPMOST,
    WS_EX_TRANSPARENT,
    OverlayModel,
    apply_overlay_styles,
    overlay_styles,
    resolve_toplevel_hwnd,
)


class FakeWin32:
    """Records GetWindowLong/SetWindowLong traffic."""

    GWL_EXSTYLE = -20

    def __init__(self, existing=0):
        self.existing = existing
        self.set_calls = []

    def GetWindowLong(self, hwnd, index):
        return self.existing

    def SetWindowLong(self, hwnd, index, value):
        self.set_calls.append((hwnd, index, value))
        return 0


def test_styles_make_the_window_click_through_and_non_activating():
    styles = overlay_styles()

    assert styles & WS_EX_TRANSPARENT  # clicks pass through to Minecraft
    assert styles & WS_EX_NOACTIVATE  # never steals focus from the game
    assert styles & WS_EX_TOPMOST  # stays above the game
    assert styles & WS_EX_TOOLWINDOW  # no taskbar/alt-tab entry


def test_styles_never_set_layered_themselves():
    """Tk's -alpha sets WS_EX_LAYERED and its attributes together.

    Adding the bit by hand without SetLayeredWindowAttributes leaves the
    window unpainted, i.e. completely invisible.
    """
    assert not overlay_styles() & WS_EX_LAYERED


def test_click_through_can_be_disabled_for_debugging():
    styles = overlay_styles(click_through=False)

    assert not styles & WS_EX_TRANSPARENT
    assert styles & WS_EX_NOACTIVATE


def test_apply_overlay_styles_preserves_existing_bits():
    win32 = FakeWin32(existing=0x00000100)

    apply_overlay_styles(1234, win32=win32)

    hwnd, index, value = win32.set_calls[0]
    assert hwnd == 1234
    assert index == FakeWin32.GWL_EXSTYLE
    assert value & 0x00000100
    assert value & WS_EX_NOACTIVATE


def test_apply_overlay_styles_keeps_layered_bit_that_tk_already_set():
    win32 = FakeWin32(existing=WS_EX_LAYERED)

    apply_overlay_styles(1234, win32=win32)

    _, _, value = win32.set_calls[0]
    assert value & WS_EX_LAYERED


def test_resolve_toplevel_hwnd_prefers_the_parent_window():
    """Tk's winfo_id() returns a child HWND; styles must go on the parent."""

    class FakeRoot:
        def winfo_id(self):
            return 111

    class FakeUser32:
        def GetParent(self, hwnd):
            return 222 if hwnd == 111 else 0

    assert resolve_toplevel_hwnd(FakeRoot(), user32=FakeUser32()) == 222


def test_resolve_toplevel_hwnd_falls_back_to_the_child_when_unparented():
    class FakeRoot:
        def winfo_id(self):
            return 111

    class FakeUser32:
        def GetParent(self, hwnd):
            return 0

    assert resolve_toplevel_hwnd(FakeRoot(), user32=FakeUser32()) == 111


def test_apply_overlay_styles_is_a_no_op_without_win32():
    # Must not raise when pywin32 is unavailable; the overlay just won't be
    # click-through rather than the app crashing.
    assert apply_overlay_styles(1234, win32=None) is False


def test_model_starts_idle():
    model = OverlayModel()

    assert model.status == "idle"
    assert model.active_codes() == []


def test_model_tracks_held_keys_in_press_order():
    model = OverlayModel()

    model.press("w")
    model.press("shift")

    assert model.active_codes() == ["w", "shift"]


def test_model_releases_keys():
    model = OverlayModel()
    model.press("w")
    model.press("a")

    model.release("w")

    assert model.active_codes() == ["a"]


def test_releasing_an_unheld_key_is_harmless():
    model = OverlayModel()

    model.release("w")

    assert model.active_codes() == []


def test_model_caps_how_many_codes_it_shows():
    model = OverlayModel(max_codes=3)
    for code in "abcdef":
        model.press(code)

    assert len(model.active_codes()) == 3


def test_model_shows_the_most_recent_codes_when_capped():
    model = OverlayModel(max_codes=2)
    for code in "abc":
        model.press(code)

    assert model.active_codes() == ["b", "c"]


def test_status_reports_playback_progress():
    model = OverlayModel()

    model.set_playing(macro="fishing", iteration=2, total=5)

    assert "fishing" in model.status
    assert "2" in model.status and "5" in model.status


def test_status_reports_endless_looping():
    model = OverlayModel()

    model.set_playing(macro="fishing", iteration=3, total=None)

    assert "fishing" in model.status
    assert "3" in model.status


def test_stopping_clears_held_keys_so_the_overlay_does_not_lie():
    model = OverlayModel()
    model.press("w")
    model.set_playing("demo", 1, 1)

    model.set_idle()

    assert model.active_codes() == []
    assert model.status == "idle"


def test_recording_status():
    model = OverlayModel()

    model.set_recording("demo")

    assert "rec" in model.status.lower()
    assert "demo" in model.status


@pytest.mark.parametrize("dirty_before", [True, False])
def test_model_reports_when_a_repaint_is_needed(dirty_before):
    """The overlay repaints only on change, not on a timer."""
    model = OverlayModel()
    if dirty_before:
        model.press("w")
    model.consume_dirty()

    model.press("q")

    assert model.consume_dirty() is True
    assert model.consume_dirty() is False
