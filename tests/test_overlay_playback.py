"""Tests for driving the overlay from replayed events."""

from macrologger.events import MacroEvent
from macrologger.overlay import (
    OverlayModel,
    apply_event_to_model,
    new_overlay_window,
)


class FakeTk:
    """Records which window constructor was used."""

    def __init__(self):
        self.created = []

    def Tk(self):
        self.created.append("Tk")
        return f"root-{len(self.created)}"

    def Toplevel(self, parent):
        self.created.append(("Toplevel", parent))
        return f"toplevel-{len(self.created)}"


def test_creates_a_root_when_standalone():
    tk = FakeTk()

    new_overlay_window(tk, parent=None)

    assert tk.created == ["Tk"]


def test_creates_a_toplevel_when_embedded():
    """A second Tk() inside a running app is a crash risk."""
    tk = FakeTk()

    new_overlay_window(tk, parent="main-window")

    assert tk.created == [("Toplevel", "main-window")]


def test_key_down_lights_the_key():
    model = OverlayModel()

    apply_event_to_model(model, MacroEvent(0.0, "key", "down", "w", ""))

    assert model.active_codes() == ["w"]


def test_key_up_clears_the_key():
    model = OverlayModel()
    apply_event_to_model(model, MacroEvent(0.0, "key", "down", "w", ""))

    apply_event_to_model(model, MacroEvent(0.1, "key", "up", "w", ""))

    assert model.active_codes() == []


def test_clicks_use_readable_labels():
    model = OverlayModel()

    apply_event_to_model(model, MacroEvent(0.0, "click", "down", "right", ""))

    assert model.active_codes() == ["RMB"]


def test_movement_does_not_fill_the_overlay():
    """Movement fires constantly; it must not push keys out of the display."""
    model = OverlayModel()
    apply_event_to_model(model, MacroEvent(0.0, "key", "down", "w", ""))

    for _ in range(20):
        apply_event_to_model(model, MacroEvent(0.1, "move", "move", "", "", 5, 5))

    assert model.active_codes() == ["w"]
