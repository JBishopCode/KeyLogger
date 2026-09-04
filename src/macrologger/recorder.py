"""Record keyboard press/release and mouse-button clicks with exact timing.

Uses ``pynput`` global listeners. Mouse *movement* is deliberately never
captured (an in-game item handles look/movement). Everything is local: events
stay in memory until the CLI writes them to a JSON file on this machine.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from .events import MacroEvent
from .window import get_active_window_title

logger = logging.getLogger(__name__)

DEFAULT_STOP_CODE = "esc"

BUTTON_CODES = ("left", "right", "middle")

# pynput special-key names that map onto our own key vocabulary. Anything not
# listed here and without a printable ``.char`` is unsupported.
_SPECIAL_KEY_CODES: dict[str, str] = {
    "space": "space",
    "enter": "enter",
    "tab": "tab",
    "backspace": "backspace",
    "esc": "esc",
    "delete": "delete",
    "insert": "insert",
    "home": "home",
    "end": "end",
    "page_up": "pageup",
    "page_down": "pagedown",
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
    "caps_lock": "capslock",
    "cmd": "win",
    "cmd_l": "win",
    "cmd_r": "win",
    "shift": "shift",
    "shift_l": "shift",
    "shift_r": "shift",
    "ctrl": "ctrl",
    "ctrl_l": "ctrl",
    "ctrl_r": "ctrl",
    "alt": "alt",
    "alt_l": "alt",
    "alt_r": "alt",
    "alt_gr": "alt",
    **{f"f{n}": f"f{n}" for n in range(1, 13)},
}


class UnsupportedInputError(Exception):
    """Raised when a key or button has no representation in the macro schema."""


def key_to_code(key: object) -> str:
    """Translate a pynput key into a macro ``code`` string.

    Printable keys (letters, digits, punctuation) become their lowercase
    character; special keys use the names in :data:`_SPECIAL_KEY_CODES`.
    """
    char = getattr(key, "char", None)
    if isinstance(char, str) and char:
        return char.lower()
    name = getattr(key, "name", None)
    if isinstance(name, str) and name in _SPECIAL_KEY_CODES:
        return _SPECIAL_KEY_CODES[name]
    raise UnsupportedInputError(f"unsupported key: {key!r}")


def button_to_code(button: object) -> str:
    """Translate a pynput mouse button into a macro ``code`` string."""
    name = getattr(button, "name", None)
    if isinstance(name, str) and name in BUTTON_CODES:
        return name
    raise UnsupportedInputError(f"unsupported mouse button: {button!r}")


class Recorder:
    """Collects input events, timestamped relative to the first event."""

    def __init__(
        self,
        clock: Callable[[], float] = time.perf_counter,
        window_provider: Callable[[], str] = get_active_window_title,
        stop_code: str = DEFAULT_STOP_CODE,
    ) -> None:
        self._clock = clock
        self._window_provider = window_provider
        self.stop_code = stop_code
        self.events: list[MacroEvent] = []
        self.stopped = False
        self._origin: float | None = None
        # The keyboard and mouse listeners run on separate threads, so the
        # check-then-set of the time origin must not race.
        self._lock = threading.Lock()

    def _elapsed(self) -> float:
        """Seconds since the first recorded event (the first call returns 0.0)."""
        now = self._clock()
        with self._lock:
            if self._origin is None:
                self._origin = now
                return 0.0
            return now - self._origin

    def _append(self, event_type: str, action: str, code: str) -> None:
        event = MacroEvent(
            t=self._elapsed(),
            type=event_type,
            action=action,
            code=code,
            window=self._window_provider(),
        )
        self.events.append(event)
        logger.debug(
            "recorded %s %s %s @ %.4fs", event.type, event.action, event.code, event.t
        )

    def _safe_append(self, event_type: str, action: str, code: str) -> None:
        """Append an event, never letting a failure kill the listener thread."""
        try:
            self._append(event_type, action, code)
        except Exception:  # noqa: BLE001 - dropping one event beats losing the macro
            logger.exception("failed to record %s %s %s", event_type, action, code)

    def _record_key(self, key: object, action: str) -> bool | None:
        if self.stopped:
            return False
        try:
            code = key_to_code(key)
        except UnsupportedInputError:
            logger.info("skipping unsupported key %r (not captured)", key)
            return None
        except Exception:  # noqa: BLE001 - a raise here would kill the listener
            logger.exception("error translating key %r; recording continues", key)
            return None
        if code == self.stop_code:
            logger.info("stop key %r pressed; recording finished", self.stop_code)
            self.stopped = True
            return False
        self._safe_append("key", action, code)
        return None

    def _on_key_press(self, key: object) -> bool | None:
        return self._record_key(key, "down")

    def _on_key_release(self, key: object) -> bool | None:
        return self._record_key(key, "up")

    def _on_click(self, x: int, y: int, button: object, pressed: bool) -> bool | None:
        # x/y are ignored on purpose: mouse movement is out of scope.
        if self.stopped:
            return False
        try:
            code = button_to_code(button)
        except UnsupportedInputError:
            logger.info("skipping unsupported button %r (not captured)", button)
            return None
        except Exception:  # noqa: BLE001 - a raise here would kill the listener
            logger.exception("error translating button %r; recording continues", button)
            return None
        self._safe_append("click", "down" if pressed else "up", code)
        return None

    def record(self) -> list[MacroEvent]:
        """Block until the stop key is pressed, then return the recorded events."""
        from pynput import keyboard, mouse  # lazy: needs a real input backend

        logger.info("recording started; press %r to stop", self.stop_code)
        mouse_listener = mouse.Listener(on_click=self._on_click)
        mouse_listener.start()
        try:
            with keyboard.Listener(
                on_press=self._on_key_press, on_release=self._on_key_release
            ) as keyboard_listener:
                keyboard_listener.join()
        finally:
            mouse_listener.stop()
        logger.info("recording stopped; %d event(s) captured", len(self.events))
        return self.events
