"""Global toggle hotkey: press once to start playback, again to stop.

The hotkey doubles as the emergency stop, so no separate panic key is needed.
Specs are written the way a user would say them (``"ctrl+shift+p"``, ``"f8"``)
and translated into the ``<modifier>+key`` syntax
``pynput.keyboard.GlobalHotKeys`` expects.
"""

from __future__ import annotations

import logging
import string
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)

DEFAULT_HOTKEY = "f8"

# Key names that pynput expects wrapped in angle brackets.
_SPECIAL_KEYS = {
    "ctrl",
    "ctrl_l",
    "ctrl_r",
    "shift",
    "shift_l",
    "shift_r",
    "alt",
    "alt_l",
    "alt_r",
    "alt_gr",
    "cmd",
    "space",
    "enter",
    "tab",
    "backspace",
    "esc",
    "delete",
    "insert",
    "home",
    "end",
    "page_up",
    "page_down",
    "up",
    "down",
    "left",
    "right",
    "caps_lock",
} | {f"f{n}" for n in range(1, 13)}

_PLAIN_KEYS = set(string.ascii_lowercase) | set(string.digits)


class InvalidHotkeyError(Exception):
    """Raised when a hotkey spec cannot be parsed."""


def to_pynput_hotkey(spec: str) -> str:
    """Translate ``"ctrl+shift+p"`` into ``"<ctrl>+<shift>+p"``.

    Raises:
        InvalidHotkeyError: if the spec is empty, malformed, or names a key
            that pynput would not recognize.
    """
    if not spec or not spec.strip():
        raise InvalidHotkeyError("hotkey is empty")
    parts = [part.strip().lower() for part in spec.split("+")]
    if any(not part for part in parts):
        raise InvalidHotkeyError(f"malformed hotkey {spec!r}")

    translated = []
    for part in parts:
        if part in _SPECIAL_KEYS:
            translated.append(f"<{part}>")
        elif part in _PLAIN_KEYS:
            translated.append(part)
        else:
            raise InvalidHotkeyError(f"unknown key {part!r} in hotkey {spec!r}")
    return "+".join(translated)


class PlaybackToggle:
    """Alternates between starting and stopping playback on each press."""

    def __init__(self, start: Callable[[], None], stop: Callable[[], None]) -> None:
        self._start = start
        self._stop = stop
        self._running = False
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._running

    def trigger(self) -> None:
        """Handle one hotkey press."""
        with self._lock:
            was_running = self._running
            # Flip first so a concurrent press cannot double-start; restored
            # below if the callback fails.
            self._running = not was_running
        try:
            if was_running:
                logger.info("hotkey pressed: stopping playback")
                self._stop()
            else:
                logger.info("hotkey pressed: starting playback")
                self._start()
        except Exception:
            with self._lock:
                self._running = was_running
            raise

    def mark_finished(self) -> None:
        """Note that playback ended on its own, so the next press starts it."""
        with self._lock:
            self._running = False


class HotkeyListener:
    """Runs a global hotkey until stopped (thin wrapper over pynput)."""

    def __init__(self, spec: str, on_press: Callable[[], None]) -> None:
        self.spec = spec
        self._combination = to_pynput_hotkey(spec)
        self._on_press = on_press
        self._listener = None

    def __enter__(self) -> HotkeyListener:
        from pynput import keyboard  # lazy: needs a real input backend

        logger.info("listening for hotkey %s", self.spec)
        self._listener = keyboard.GlobalHotKeys({self._combination: self._on_press})
        self._listener.start()
        return self

    def __exit__(self, *exc_info: object) -> bool:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
        return False

    def join(self) -> None:
        """Block until the listener stops."""
        if self._listener is not None:
            self._listener.join()
