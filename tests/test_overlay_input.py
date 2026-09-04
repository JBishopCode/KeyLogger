"""Tests that the overlay is fed BOTH keyboard and mouse-button events.

A fake pynput package is injected, so no global hook is installed.
"""

from macrologger.overlay import OverlayModel, attach_input_listeners, click_label


class FakeListener:
    def __init__(self, **callbacks):
        self.callbacks = callbacks
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


class FakeKeyboardModule:
    def __init__(self):
        self.listener = None

    def Listener(self, **callbacks):
        self.listener = FakeListener(**callbacks)
        return self.listener


class FakeMouseModule:
    def __init__(self):
        self.listener = None

    def Listener(self, **callbacks):
        self.listener = FakeListener(**callbacks)
        return self.listener


class FakePynput:
    def __init__(self):
        self.keyboard = FakeKeyboardModule()
        self.mouse = FakeMouseModule()


class FakeKey:
    def __init__(self, char=None, name=None):
        self.char = char
        if name is not None:
            self.name = name


class FakeButton:
    def __init__(self, name):
        self.name = name


def test_attaches_a_mouse_listener_as_well_as_a_keyboard_one():
    pynput = FakePynput()

    attach_input_listeners(OverlayModel(), pynput=pynput)

    assert pynput.keyboard.listener is not None
    assert pynput.mouse.listener is not None


def test_listeners_are_started():
    pynput = FakePynput()

    attach_input_listeners(OverlayModel(), pynput=pynput)

    assert pynput.keyboard.listener.started
    assert pynput.mouse.listener.started


def test_mouse_movement_is_not_subscribed():
    """Movement is out of scope; subscribing would flood the overlay."""
    pynput = FakePynput()

    attach_input_listeners(OverlayModel(), pynput=pynput)

    assert "on_move" not in pynput.mouse.listener.callbacks


def test_clicks_appear_on_the_overlay():
    model = OverlayModel()
    pynput = FakePynput()
    attach_input_listeners(model, pynput=pynput)

    pynput.mouse.listener.callbacks["on_click"](0, 0, FakeButton("right"), True)

    assert model.active_codes() == ["RMB"]


def test_releasing_a_click_clears_it():
    model = OverlayModel()
    pynput = FakePynput()
    attach_input_listeners(model, pynput=pynput)
    on_click = pynput.mouse.listener.callbacks["on_click"]

    on_click(0, 0, FakeButton("left"), True)
    on_click(0, 0, FakeButton("left"), False)

    assert model.active_codes() == []


def test_keys_still_appear():
    model = OverlayModel()
    pynput = FakePynput()
    attach_input_listeners(model, pynput=pynput)

    pynput.keyboard.listener.callbacks["on_press"](FakeKey(char="w"))

    assert model.active_codes() == ["w"]


def test_keys_and_clicks_coexist():
    model = OverlayModel()
    pynput = FakePynput()
    attach_input_listeners(model, pynput=pynput)

    pynput.keyboard.listener.callbacks["on_press"](FakeKey(char="w"))
    pynput.mouse.listener.callbacks["on_click"](0, 0, FakeButton("right"), True)

    assert model.active_codes() == ["w", "RMB"]


def test_unsupported_input_is_ignored_not_fatal():
    model = OverlayModel()
    pynput = FakePynput()
    attach_input_listeners(model, pynput=pynput)

    pynput.keyboard.listener.callbacks["on_press"](FakeKey())
    pynput.mouse.listener.callbacks["on_click"](0, 0, FakeButton("x2"), True)

    assert model.active_codes() == []


def test_click_labels_are_readable():
    assert click_label("left") == "LMB"
    assert click_label("right") == "RMB"
    assert click_label("middle") == "MMB"
