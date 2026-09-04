"""Replay recorded events through DirectInput so Minecraft Java registers them.

Playback is strictly local: events come from a macro JSON file on this machine
and are handed to ``pydirectinput``, which synthesizes scancode-level input.
Nothing is sent off the machine.
"""

from __future__ import annotations

import itertools
import logging
import math
import random
import string
import time
from collections.abc import Callable, Sequence
from functools import partial
from typing import Protocol

from .backend import BackendUnavailableError, load_pydirectinput
from .events import MacroEvent

logger = logging.getLogger(__name__)

# Re-exported so callers can keep importing it from here.
__all__ = [
    "BackendUnavailableError",
    "Player",
    "UnknownCodeError",
    "code_to_button",
    "code_to_key",
]


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

    def move(  # noqa: N803 - pydirectinput's parameter names
        self, xOffset: int, yOffset: int, *, relative: bool
    ) -> object: ...


class RandomSource(Protocol):
    """The slice of ``random.Random`` used for timing jitter."""

    def uniform(self, a: float, b: float) -> float: ...


class StopSignal(Protocol):
    """The slice of ``threading.Event`` used to interrupt playback."""

    def is_set(self) -> bool: ...


class UnknownCodeError(Exception):
    """Raised when a recorded code has no DirectInput equivalent."""


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

#: Largest relative offset sent in one call. Bigger moves are split, because
#: Windows pointer acceleration scales a single large delta differently to the
#: sequence of small ones it represents.
MAX_MOVE_STEP = 20

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
    return load_pydirectinput()


class _HeldInput:
    """Tracks keys/buttons pressed during replay so a stop can release them.

    Without this, stopping mid-macro would leave W held down and the character
    walking in-game.
    """

    def __init__(self, backend: InputBackend) -> None:
        self._backend = backend
        self._keys: set[str] = set()
        self._buttons: set[str] = set()

    def record(self, event: MacroEvent) -> None:
        if event.type == "move":
            return  # movement holds nothing that needs releasing
        target = self._keys if event.type == "key" else self._buttons
        code = code_to_key(event.code) if event.type == "key" else code_to_button(event.code)
        if event.action == "down":
            target.add(code)
        else:
            target.discard(code)

    def release_all(self) -> None:
        for key in sorted(self._keys):
            logger.debug("releasing held key %s", key)
            self._backend.keyUp(key)
        for button in sorted(self._buttons):
            logger.debug("releasing held button %s", button)
            self._backend.mouseUp(button=button)
        self._keys.clear()
        self._buttons.clear()


class Player:
    """Replays events in order, honoring the recorded inter-event gaps."""

    #: Longest single sleep, so a stop request is noticed promptly.
    SLEEP_SLICE = 0.05

    def __init__(
        self,
        backend: InputBackend | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.perf_counter,
        stop_event: StopSignal | None = None,
    ) -> None:
        self._backend = backend if backend is not None else _load_default_backend()
        self._sleep = sleep
        self._clock = clock
        self._stop_event = stop_event

    def play(
        self,
        events: Sequence[MacroEvent],
        loop: int | None = 1,
        loop_delay: float = 0.0,
        jitter: float = 0.0,
        rng: RandomSource | None = None,
    ) -> None:
        """Send ``events`` through the backend, sleeping the recorded gaps.

        Args:
            events: The macro to replay.
            loop: How many times to replay it (``1`` = play once). ``None``
                repeats until stopped, which requires a ``stop_event``.
            loop_delay: Seconds to wait between iterations.
            jitter: Fractional timing variation applied per gap, per
                iteration — ``0.1`` means each gap is scaled by ±5%, so loops
                are not byte-identical. ``0.0`` reproduces exact gaps.
            rng: Source of randomness for ``jitter``; injectable for tests.

        Raises:
            ValueError: if ``loop`` is below 1 or ``jitter`` is negative.
            UnknownCodeError: if any event's code cannot be mapped. Mapping is
                resolved up front so a bad macro sends no partial input.
        """
        if loop is None and self._stop_event is None:
            raise ValueError("looping until stopped requires a stop_event")
        if loop is not None and loop < 1:
            raise ValueError(f"loop must be at least 1, got {loop}")
        if jitter < 0:
            raise ValueError(f"jitter must not be negative, got {jitter}")
        if not events:
            logger.info("nothing to replay: macro has no events")
            return

        plan = [self._resolve(event) for event in events]
        randomness = rng if rng is not None else random.Random()

        logger.info(
            "replaying %d event(s), loop=%s, jitter=%.3f",
            len(events),
            "until stopped" if loop is None else loop,
            jitter,
        )
        started = self._clock()
        held = _HeldInput(self._backend)
        iterations = itertools.count() if loop is None else range(loop)
        try:
            for iteration in iterations:
                if iteration and not self._wait(loop_delay):
                    break
                if not self._play_once(events, plan, jitter, randomness, held):
                    break
        finally:
            held.release_all()
        logger.info("replay finished in %.3fs", self._clock() - started)

    def _play_once(
        self,
        events: Sequence[MacroEvent],
        plan: Sequence[Callable[[], object]],
        jitter: float,
        rng: RandomSource,
        held: "_HeldInput",
    ) -> bool:
        """Replay one iteration; returns False if playback was stopped."""
        previous_t = events[0].t
        for index, (event, send) in enumerate(zip(events, plan, strict=True)):
            if index:
                gap = max(0.0, event.t - previous_t)
                if not self._wait(self._apply_jitter(gap, jitter, rng)):
                    return False
            previous_t = event.t
            if self._stopped():
                return False
            logger.debug("replaying %s %s %s", event.type, event.action, event.code)
            send()
            held.record(event)
        return True

    @staticmethod
    def _apply_jitter(gap: float, jitter: float, rng: RandomSource) -> float:
        """Scale ``gap`` by a random ±``jitter``/2 fraction, never below zero."""
        if not jitter:
            return gap
        spread = jitter / 2
        return max(0.0, gap * (1 + rng.uniform(-spread, spread)))

    def _stopped(self) -> bool:
        return self._stop_event is not None and self._stop_event.is_set()

    def _wait(self, seconds: float) -> bool:
        """Sleep ``seconds``; returns False if a stop was requested meanwhile.

        Long waits are slept in slices so a stop is noticed promptly rather
        than after a multi-second gap has elapsed.
        """
        if self._stopped():
            return False
        if self._stop_event is None:
            if seconds:
                self._sleep(seconds)
            return True
        remaining = seconds
        while remaining > 0:
            slice_seconds = min(self.SLEEP_SLICE, remaining)
            self._sleep(slice_seconds)
            remaining -= slice_seconds
            if self._stopped():
                return False
        return True

    def _send_move(self, move: Callable[..., object], dx: int, dy: int) -> None:
        """Send a relative move, split into steps no larger than MAX_MOVE_STEP.

        Windows pointer acceleration is non-linear, so one big jump rotates the
        camera further than the many small movements it was merged from. Ten
        steps of 20px land much closer to the original than one of 200.

        ``relative=True`` is load-bearing: pydirectinput defaults to False,
        which converts the offset into an absolute target that a game with a
        trapped cursor ignores.
        """
        steps = max(1, math.ceil(max(abs(dx), abs(dy)) / MAX_MOVE_STEP))
        sent_x = sent_y = 0
        for step in range(1, steps + 1):
            # Interpolate against the running total so integer rounding can
            # never lose or gain distance overall.
            target_x = round(dx * step / steps)
            target_y = round(dy * step / steps)
            move(target_x - sent_x, target_y - sent_y, relative=True)
            sent_x, sent_y = target_x, target_y

    def _resolve(self, event: MacroEvent) -> Callable[[], object]:
        """Bind the backend call for ``event`` into a zero-argument callable.

        Mouse buttons are bound by keyword: ``mouseDown``/``mouseUp`` take
        ``x`` first, so a positional button would be treated as a coordinate.
        """
        if event.type == "move":
            move = getattr(self._backend, "move", None)
            if move is None:
                raise UnknownCodeError(
                    "input backend cannot send relative mouse movement"
                )
            return partial(self._send_move, move, event.dx, event.dy)
        if event.type == "key":
            key = code_to_key(event.code)
            send = self._backend.keyDown if event.action == "down" else self._backend.keyUp
            return partial(send, key)
        button = code_to_button(event.code)
        send = self._backend.mouseDown if event.action == "down" else self._backend.mouseUp
        return partial(send, button=button)
