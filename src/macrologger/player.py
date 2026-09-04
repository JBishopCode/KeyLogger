"""Replay recorded events through DirectInput so Minecraft Java registers them.

Playback is strictly local: events come from a macro JSON file on this machine
and are handed to ``pydirectinput``, which synthesizes scancode-level input.
Nothing is sent off the machine.
"""

from __future__ import annotations

import logging
import string
import time
from collections.abc import Callable, Sequence
from functools import partial
from typing import Protocol

from .events import MacroEvent

logger = logging.getLogger(__name__)


class InputBackend(Protocol):
    """The slice of ``pydirectinput`` the player uses.

    The mouse calls take ``x``/``y`` first, so ``button`` must always be passed
    by keyword — positionally it is read as a screen coordinate and the pointer
    gets moved, which this tool never does.
    """

    def keyDown(self, key: str) -> object: ...  # noqa: N802 - pydirectinput's name

    def keyUp(self, key: str) -> object: ...  # noqa: N802

    def mouseDown(self, *, button: str) -> object: ...  # noqa: N802

    def mouseUp(self, *, button: str) -> object: ...  # noqa: N802


class UnknownCodeError(Exception):
    """Raised when a recorded code has no DirectInput equivalent."""


class BackendUnavailableError(Exception):
    """Raised when the DirectInput backend cannot be loaded."""


# Central code -> pydirectinput key mapping. Recorded codes are produced by
# macrologger.recorder.key_to_code, so the two tables must stay in sync.
KEY_MAP: dict[str, str] = {
    **{char: char for char in string.ascii_lowercase},
    **{digit: digit for digit in string.digits},
    **{f"f{n}": f"f{n}" for n in range(1, 13)},
    **{char: char for char in "`-=[]\\;',./"},
    "shift": "shift",
    "ctrl": "ctrl",
    "alt": "alt",
    "space": "space",
    "enter": "enter",
    "tab": "tab",
    "backspace": "backspace",
    "esc": "esc",
    "delete": "delete",
    "insert": "insert",
    "home": "home",
    "end": "end",
    "pageup": "pageup",
    "pagedown": "pagedown",
    "capslock": "capslock",
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
    "win": "win",
}

BUTTON_MAP: dict[str, str] = {
    "left": "left",
    "right": "right",
    "middle": "middle",
}


def code_to_key(code: str) -> str:
    """Map a recorded key code onto a pydirectinput key name."""
    try:
        return KEY_MAP[code]
    except KeyError:
        raise UnknownCodeError(f"no DirectInput key for code {code!r}") from None


def code_to_button(code: str) -> str:
    """Map a recorded click code onto a pydirectinput mouse button name."""
    try:
        return BUTTON_MAP[code]
    except KeyError:
        raise UnknownCodeError(f"no DirectInput button for code {code!r}") from None


def _load_default_backend() -> InputBackend:
    try:
        import pydirectinput  # lazy: Windows-only, not needed for unit tests
    except ImportError as exc:
        raise BackendUnavailableError(
            "pydirectinput is not installed or not usable on this Python; "
            "run: pip install -r requirements.txt"
        ) from exc

    # Minecraft needs every event at the recorded time; the library's built-in
    # pause and corner failsafe would distort the gaps, so both are disabled.
    pydirectinput.PAUSE = 0
    pydirectinput.FAILSAFE = False
    return pydirectinput


class Player:
    """Replays events in order, honoring the recorded inter-event gaps."""

    def __init__(
        self,
        backend: InputBackend | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._backend = backend if backend is not None else _load_default_backend()
        self._sleep = sleep
        self._clock = clock

    def play(self, events: Sequence[MacroEvent]) -> None:
        """Send ``events`` through the backend, sleeping the recorded gaps.

        Raises:
            UnknownCodeError: if any event's code cannot be mapped. Mapping is
                resolved up front so a bad macro sends no partial input.
        """
        if not events:
            logger.info("nothing to replay: macro has no events")
            return

        plan = [self._resolve(event) for event in events]

        logger.info("replaying %d event(s)", len(events))
        started = self._clock()
        previous_t = events[0].t
        for index, (event, send) in enumerate(zip(events, plan, strict=True)):
            if index:
                self._sleep(max(0.0, event.t - previous_t))
            previous_t = event.t
            logger.debug("replaying %s %s %s", event.type, event.action, event.code)
            send()
        logger.info("replay finished in %.3fs", self._clock() - started)

    def _resolve(self, event: MacroEvent) -> Callable[[], object]:
        """Bind the backend call for ``event`` into a zero-argument callable.

        Mouse buttons are bound by keyword: ``mouseDown``/``mouseUp`` take
        ``x`` first, so a positional button would be treated as a coordinate.
        """
        if event.type == "key":
            key = code_to_key(event.code)
            send = self._backend.keyDown if event.action == "down" else self._backend.keyUp
            return partial(send, key)
        button = code_to_button(event.code)
        send = self._backend.mouseDown if event.action == "down" else self._backend.mouseUp
        return partial(send, button=button)
