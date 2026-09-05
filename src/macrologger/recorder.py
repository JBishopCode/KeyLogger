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
from typing import Any

from .backend import load_pynput
from .events import MacroEvent
from .rawinput import RawMouseListener
from .window import get_active_window_title

logger = logging.getLogger(__name__)

DEFAULT_STOP_CODE = "esc"

#: Minimum seconds between recorded movement samples (~125 Hz, matching a
#: typical mouse polling rate).
#:
#: Deliberately fine-grained. Accumulating many small deltas into one large one
#: preserves total distance but NOT the resulting camera rotation: Windows
#: pointer ballistics scale a delta non-linearly, so one jump of 30 turns
#: further than three of 10. Coarse sampling replays the right shape while
#: ending on a different heading.
DEFAULT_MOVE_INTERVAL = 0.008

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
        record_movement: bool = False,
        move_interval: float = DEFAULT_MOVE_INTERVAL,
    ) -> None:
        self._clock = clock
        self._window_provider = window_provider
        self.stop_code = stop_code
        self.record_movement = record_movement
        self.move_interval = move_interval
        self.events: list[MacroEvent] = []
        self.stopped = False
        self._origin: float | None = None
        self._last_position: tuple[int, int] | None = None
        self._last_move_sample: float = 0.0
        self._pending_dx = 0
        self._pending_dy = 0
        #: Live listeners, so request_stop() can end a session on demand.
        self._listeners: list[Any] = []
        # The keyboard and mouse listeners run on separate threads, so the
        # check-then-set of the time origin must not race.
        self._lock = threading.Lock()

    def _elapsed(self) -> float:
        """Seconds since the first recorded event (the first call returns 0.0)."""
        return self._elapsed_at(self._clock())

    def _elapsed_at(self, now: float) -> float:
        """As :meth:`_elapsed`, for a timestamp the caller already read."""
        with self._lock:
            if self._origin is None:
                self._origin = now
                return 0.0
            return now - self._origin

    def _append(
        self,
        event_type: str,
        action: str,
        code: str,
        dx: int = 0,
        dy: int = 0,
        now: float | None = None,
    ) -> None:
        event = MacroEvent(
            t=self._elapsed() if now is None else self._elapsed_at(now),
            type=event_type,
            action=action,
            code=code,
            window=self._window_provider(),
            dx=dx,
            dy=dy,
        )
        self.events.append(event)
        logger.debug(
            "recorded %s %s %s @ %.4fs", event.type, event.action, event.code, event.t
        )

    def _safe_append(
        self, event_type: str, action: str, code: str, dx: int = 0, dy: int = 0
    ) -> None:
        """Append an event, never letting a failure kill the listener thread."""
        try:
            self._append(event_type, action, code, dx=dx, dy=dy)
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

    def _on_move(self, x: int, y: int) -> bool | None:
        """Sample cursor movement as a relative delta, if movement is enabled.

        Minecraft traps the cursor for camera control, so absolute positions
        are meaningless on replay — only deltas are. Samples faster than
        ``move_interval`` are accumulated rather than dropped, so no distance
        is lost.
        """
        if self.stopped:
            return False
        if not self.record_movement:
            return None

        now = self._clock()
        if self._last_position is None:
            self._last_position = (x, y)
            self._last_move_sample = now
            return None

        last_x, last_y = self._last_position
        self._last_position = (x, y)
        self._pending_dx += x - last_x
        self._pending_dy += y - last_y

        if now - self._last_move_sample < self.move_interval:
            return None
        if not (self._pending_dx or self._pending_dy):
            return None

        self._safe_append_move(now)
        return None

    def _on_scroll(self, x: int, y: int, dx: int, dy: int) -> bool | None:
        """Record a wheel scroll (hotbar selection in Minecraft).

        Always captured, independent of the mouse-movement toggle: scrolling
        is a discrete action like a keypress, not continuous motion.
        """
        if self.stopped:
            return False
        if not (dx or dy):
            return None
        self._safe_append("scroll", "scroll", "", dx=dx, dy=dy)
        return None

    def request_stop(self) -> None:
        """Stop recording without waiting for the stop key.

        The CLI ends a recording with the sentinel key; the control window
        needs a Stop button, which cannot rely on a keypress arriving.
        """
        self.stopped = True
        for listener in self._listeners:
            try:
                listener.stop()
            except Exception:  # noqa: BLE001 - stopping must not raise
                logger.debug("listener stop failed", exc_info=True)
        logger.info("stop requested; recording finished")

    def _on_raw_move(self, dx: int, dy: int) -> None:
        """Accept a true device delta from Raw Input.

        Preferred over :meth:`_on_move`: cursor-position deltas are useless in
        a game that recentres the cursor every frame.
        """
        if self.stopped or not self.record_movement:
            return

        now = self._clock()
        # Guarded: this runs on the raw-input pump thread while the pynput
        # listeners run on theirs, and the accumulator is shared state.
        with self._lock:
            self._pending_dx += dx
            self._pending_dy += dy
            if now - self._last_move_sample < self.move_interval:
                return
            if not (self._pending_dx or self._pending_dy):
                return
            dx_total, dy_total = self._pending_dx, self._pending_dy
            self._pending_dx = self._pending_dy = 0
            self._last_move_sample = now

        try:
            self._append("move", "move", "", dx=dx_total, dy=dy_total, now=now)
        except Exception:  # noqa: BLE001 - never kill the pump thread
            logger.exception("failed to record movement %s,%s", dx_total, dy_total)

    def _safe_append_move(self, now: float) -> None:
        dx, dy = self._pending_dx, self._pending_dy
        self._pending_dx = self._pending_dy = 0
        self._last_move_sample = now
        try:
            self._append("move", "move", "", dx=dx, dy=dy, now=now)
        except Exception:  # noqa: BLE001 - never kill the listener thread
            logger.exception("failed to record movement %s,%s", dx, dy)

    def record(self) -> list[MacroEvent]:
        """Block until the stop key is pressed, then return the recorded events."""
        pynput = load_pynput()  # lazy: needs a real input backend
        keyboard, mouse = pynput.keyboard, pynput.mouse

        logger.info(
            "recording started; press %r to stop (movement: %s)",
            self.stop_code,
            "on" if self.record_movement else "off",
        )
        mouse_listener = mouse.Listener(
            on_click=self._on_click, on_scroll=self._on_scroll
        )
        mouse_listener.start()
        self._listeners = [mouse_listener]

        # Movement comes from Raw Input, not pynput: Minecraft recentres the
        # cursor, so cursor-position deltas describe the recentring instead of
        # the player's hand.
        raw_listener = None
        if self.record_movement:
            raw_listener = RawMouseListener(on_move=self._on_raw_move)
            raw_listener.start()
            self._listeners.append(raw_listener)
            if not raw_listener.running:
                logger.warning(
                    "raw mouse input unavailable; movement will not be recorded"
                )
        try:
            with keyboard.Listener(
                on_press=self._on_key_press, on_release=self._on_key_release
            ) as keyboard_listener:
                self._listeners.append(keyboard_listener)
                keyboard_listener.join()
        finally:
            mouse_listener.stop()
            if raw_listener is not None:
                raw_listener.stop()
        logger.info("recording stopped; %d event(s) captured", len(self.events))
        return self.events
