"""Application logic behind the control window.

Deliberately free of any GUI toolkit: recording and playback run on worker
threads here, and the view only renders state and calls these methods. That
keeps the behaviour testable without opening a window.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .events import MacroEvent
from .player import Player
from .recorder import DEFAULT_MOVE_INTERVAL, DEFAULT_STOP_CODE, Recorder
from .storage import (
    DEFAULT_MACROS_DIR,
    MacroSummary,
    list_macros,
    load_macro,
    macro_path,
    save_macro,
)

logger = logging.getLogger(__name__)

#: How long to wait for a worker thread to notice a stop request.
WORKER_JOIN_TIMEOUT = 5.0


class AppState(Enum):
    IDLE = "idle"
    RECORDING = "recording"
    PLAYING = "playing"


@dataclass(frozen=True, slots=True)
class PlaybackOptions:
    """The playback settings the control window exposes."""

    loop: int = 1
    loop_forever: bool = False
    loop_delay: float = 0.0
    jitter: float = 0.0

    def resolved_loop(self) -> int | None:
        """``None`` means repeat until stopped, which is what Player expects."""
        return None if self.loop_forever else self.loop


class AppController:
    """Drives recording and playback for the UI."""

    def __init__(
        self,
        macros_dir: Path | str = DEFAULT_MACROS_DIR,
        recorder_factory: Callable[..., Any] = Recorder,
        player_factory: Callable[..., Any] = Player,
        stop_code: str = DEFAULT_STOP_CODE,
        move_interval: float = DEFAULT_MOVE_INTERVAL,
    ) -> None:
        self.macros_dir = Path(macros_dir)
        self._recorder_factory = recorder_factory
        self._player_factory = player_factory
        self.stop_code = stop_code
        self.move_interval = move_interval

        self.state = AppState.IDLE
        self.recorder: Any = None
        self.player: Any = None
        self.last_error: str | None = None

        #: Called with the new AppState whenever it changes. The view sets this
        #: and is responsible for marshalling onto its own thread.
        self.on_state_change: Callable[[AppState], None] | None = None

        self._worker: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    # -- state ---------------------------------------------------------

    def _set_state(self, state: AppState) -> None:
        self.state = state
        logger.info("state -> %s", state.value)
        if self.on_state_change is not None:
            try:
                self.on_state_change(state)
            except Exception:  # noqa: BLE001 - a view bug must not wedge the app
                logger.exception("state change handler failed")

    def wait_idle(self, timeout: float = WORKER_JOIN_TIMEOUT) -> None:
        """Block until the current worker finishes (used by tests and shutdown)."""
        worker = self._worker
        if worker is not None:
            worker.join(timeout=timeout)

    # -- library -------------------------------------------------------

    def list_macros(self) -> list[MacroSummary]:
        return list_macros(macros_dir=self.macros_dir)

    def load(self, name: str) -> list[MacroEvent]:
        return load_macro(name, macros_dir=self.macros_dir)

    # -- recording -----------------------------------------------------

    def start_recording(self, name: str, record_movement: bool = False) -> None:
        """Begin recording into ``name``.

        Raises:
            RuntimeError: if something is already running.
            InvalidMacroNameError: if the name is not usable as a filename.
        """
        with self._lock:
            if self.state is not AppState.IDLE:
                raise RuntimeError(f"cannot record while {self.state.value}")
            # Validate the name before installing a hook, so a typo fails now
            # rather than after a whole recording session.
            macro_path(name, macros_dir=self.macros_dir)
            self.recorder = self._recorder_factory(
                stop_code=self.stop_code,
                record_movement=record_movement,
                move_interval=self.move_interval,
            )
            self._worker = threading.Thread(
                target=self._run_recording,
                args=(name,),
                name="macro-recording",
                daemon=True,
            )
            self._set_state(AppState.RECORDING)
            self._worker.start()

    def _run_recording(self, name: str) -> None:
        try:
            events = self.recorder.record()
            save_macro(name, events, macros_dir=self.macros_dir)
            logger.info("recorded %d event(s) into %s", len(events), name)
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI
            self.last_error = str(exc)
            logger.exception("recording failed")
        finally:
            self.recorder = None
            self._set_state(AppState.IDLE)

    def toggle_recording(self, name: str, record_movement: bool = False) -> None:
        """Record hotkey behaviour: start if idle, stop if already recording.

        Starting from a hotkey means the user is already in the game, so the
        alt-tab and click needed to reach the window are never captured.
        """
        if self.state is AppState.RECORDING:
            self.stop_recording()
        elif self.state is AppState.IDLE:
            self.start_recording(name, record_movement=record_movement)
        else:
            logger.info("ignoring record toggle while %s", self.state.value)

    def stop_recording(self) -> None:
        recorder = self.recorder
        if recorder is not None:
            recorder.request_stop()

    # -- playback ------------------------------------------------------

    def start_playback(self, name: str, options: PlaybackOptions) -> None:
        """Replay ``name``; raises if busy or the macro cannot be loaded."""
        with self._lock:
            if self.state is not AppState.IDLE:
                raise RuntimeError(f"cannot play while {self.state.value}")
            # Load before switching state so a bad macro leaves us idle.
            events = self.load(name)
            self._stop_event = threading.Event()
            self.player = self._player_factory(stop_event=self._stop_event)
            self._worker = threading.Thread(
                target=self._run_playback,
                args=(events, options),
                name="macro-playback",
                daemon=True,
            )
            self._set_state(AppState.PLAYING)
            self._worker.start()

    def _run_playback(self, events: list[MacroEvent], options: PlaybackOptions) -> None:
        try:
            self.player.play(
                events,
                loop=options.resolved_loop(),
                loop_delay=options.loop_delay,
                jitter=options.jitter,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI
            self.last_error = str(exc)
            logger.exception("playback failed")
        finally:
            self.player = None
            self._set_state(AppState.IDLE)

    def stop_playback(self) -> None:
        self._stop_event.set()
        self.wait_idle()

    def toggle_playback(self, name: str, options: PlaybackOptions) -> None:
        """Hotkey behaviour: start if idle, stop if already playing."""
        if self.state is AppState.PLAYING:
            self.stop_playback()
        elif self.state is AppState.IDLE:
            self.start_playback(name, options)
        else:
            logger.info("ignoring toggle while %s", self.state.value)

    # -- lifecycle -----------------------------------------------------

    def shutdown(self) -> None:
        """Stop whatever is running; safe to call when already idle."""
        self._stop_event.set()
        self.stop_recording()
        self.wait_idle()
