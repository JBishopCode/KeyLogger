"""Headless CLI for the record/replay core.

    python -m macrologger.cli record <name>
    python -m macrologger.cli play <name>

This is the Milestone 1 driver used to validate playback inside Minecraft
Java. Everything happens locally: macros are read from and written to
``macros/`` on this machine and nothing is transmitted anywhere.
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
from collections.abc import Sequence

from .backend import load_pynput
from .events import MacroEvent, MacroSerializationError
from .hotkey import DEFAULT_HOTKEY, HotkeyListener, InvalidHotkeyError, PlaybackToggle
from .overlay import KeyOverlay, OverlayModel
from .player import BackendUnavailableError, Player, UnknownCodeError
from .recorder import DEFAULT_STOP_CODE, Recorder, UnsupportedInputError, key_to_code
from .storage import (
    DEFAULT_MACROS_DIR,
    InvalidMacroNameError,
    MacroNotFoundError,
    list_macros,
    load_macro,
    save_macro,
)

logger = logging.getLogger(__name__)


class InvalidPositionError(Exception):
    """Raised when an overlay position cannot be parsed."""

# Every core exception the CLI boundary turns into a message + non-zero exit.
# OSError covers the disk-level failures storage can hit (permission denied,
# disk full, a name Windows refuses); MacroNotFoundError is raised in its place
# for the common "no such macro" case.
CORE_ERRORS = (
    BackendUnavailableError,
    InvalidHotkeyError,
    InvalidPositionError,
    InvalidMacroNameError,
    MacroNotFoundError,
    MacroSerializationError,
    OSError,
    UnknownCodeError,
)

EXIT_OK = 0
EXIT_ERROR = 1

#: How long to wait for the playback thread to notice a stop request.
WORKER_JOIN_TIMEOUT = 5.0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="macrologger",
        description="Record and replay Minecraft keyboard/mouse-click macros.",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="log every event (DEBUG)"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    record = subparsers.add_parser("record", help="record a new macro")
    record.add_argument("name", help="macro name (saved as macros/<name>.json)")
    record.add_argument(
        "--stop-key",
        default=DEFAULT_STOP_CODE,
        help=f"key that ends recording (default: {DEFAULT_STOP_CODE})",
    )

    subparsers.add_parser("list", help="list the macros in the library")

    overlay = subparsers.add_parser(
        "overlay",
        help="show the always-on-top key overlay (spike: verify it over Minecraft)",
    )
    overlay.add_argument(
        "--position",
        default="24,24",
        metavar="X,Y",
        help="screen position of the overlay (default: 24,24)",
    )
    overlay.add_argument(
        "--no-click-through",
        action="store_true",
        help="debug: keep clicks on the overlay instead of passing them through",
    )
    overlay.add_argument(
        "--opaque",
        action="store_true",
        help="debug: disable transparency (use if the overlay is invisible)",
    )

    play = subparsers.add_parser("play", help="replay a saved macro")
    play.add_argument("name", help="macro name to replay")
    play.add_argument(
        "--loop",
        nargs="?",
        const=0,
        type=int,
        default=1,
        metavar="N",
        help="repeat the macro N times; bare --loop repeats until stopped",
    )
    play.add_argument(
        "--loop-delay",
        type=float,
        default=0.0,
        metavar="SECONDS",
        help="wait this long between loop iterations (default: 0)",
    )
    play.add_argument(
        "--jitter",
        type=float,
        default=0.0,
        metavar="FRACTION",
        help="randomize each gap by +/- half this fraction, e.g. 0.1 for +/-5%%",
    )
    play.add_argument(
        "--hotkey",
        nargs="?",
        const=DEFAULT_HOTKEY,
        default=None,
        metavar="KEYS",
        help=(
            "wait for a hotkey to start playback; press again to stop "
            f"(default: {DEFAULT_HOTKEY})"
        ),
    )

    return parser


def _do_record(name: str, stop_key: str) -> int:
    print(f"Recording '{name}'. Press {stop_key.upper()} to stop.")
    recorder = Recorder(stop_code=stop_key)
    events = recorder.record()
    path = save_macro(name, events, macros_dir=DEFAULT_MACROS_DIR)
    print(f"Saved {len(events)} event(s) to {path}")
    return EXIT_OK


def _do_list() -> int:
    summaries = list_macros(macros_dir=DEFAULT_MACROS_DIR)
    if not summaries:
        print(f"No macros saved yet in {DEFAULT_MACROS_DIR}/.")
        return EXIT_OK

    name_width = max(len(summary.name) for summary in summaries)
    print(f"{'NAME':<{name_width}}  {'EVENTS':>6}  {'SECONDS':>7}  RECORDED IN")
    for summary in summaries:
        print(
            f"{summary.name:<{name_width}}  {summary.event_count:>6}  "
            f"{summary.duration:>7.2f}  {summary.window or '-'}"
        )
    return EXIT_OK


def _parse_position(text: str) -> tuple[int, int]:
    try:
        x, y = (int(part) for part in text.split(","))
    except ValueError:
        raise InvalidPositionError(
            f"position must look like X,Y (got {text!r})"
        ) from None
    return x, y


def _do_overlay(
    position: str, click_through: bool = True, alpha: float = 0.85
) -> int:
    """Overlay spike: show live keypresses over whatever is focused.

    Exists so the overlay can be validated over a running Minecraft before the
    rest of the UI is built on top of it.
    """
    keyboard = load_pynput().keyboard

    model = OverlayModel()
    overlay = KeyOverlay(
        model,
        position=_parse_position(position),
        alpha=alpha,
        click_through=click_through,
    )
    model.set_recording("overlay test")

    def on_press(key: object) -> None:
        try:
            model.press(key_to_code(key))
        except UnsupportedInputError:
            pass

    def on_release(key: object) -> None:
        try:
            model.release(key_to_code(key))
        except UnsupportedInputError:
            pass

    print("Overlay running. Alt-tab into Minecraft and press some keys.")
    print("It should stay on top, show your keys, and NOT take focus.")
    print("Ctrl+C here to close it.")
    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()
    try:
        overlay.run()
    except KeyboardInterrupt:
        pass
    finally:
        listener.stop()
        overlay.close()
    return EXIT_OK


def _describe_loop(loop: int | None) -> str:
    if loop is None:
        return "looping until stopped"
    return "once" if loop == 1 else f"{loop} times"


def _do_play(
    name: str,
    loop: int | None,
    loop_delay: float,
    jitter: float,
    hotkey: str | None,
) -> int:
    if loop is None and hotkey is None:
        print(
            "error: --loop with no count needs --hotkey, which is what stops it",
            file=sys.stderr,
        )
        return EXIT_ERROR

    events = load_macro(name, macros_dir=DEFAULT_MACROS_DIR)
    summary = f"'{name}' ({len(events)} event(s)), {_describe_loop(loop)}"

    if hotkey is None:
        print(f"Replaying {summary}. Focus Minecraft now.")
        Player().play(events, loop=loop, loop_delay=loop_delay, jitter=jitter)
        print("Replay finished.")
        return EXIT_OK

    return _play_with_hotkey(events, summary, hotkey, loop, loop_delay, jitter)


def _play_with_hotkey(
    events: Sequence[MacroEvent],
    summary: str,
    hotkey: str,
    loop: int | None,
    loop_delay: float,
    jitter: float,
) -> int:
    """Wait for the hotkey; press to start playback, press again to stop."""
    stop_event = threading.Event()
    player = Player(stop_event=stop_event)
    worker: threading.Thread | None = None
    toggle: PlaybackToggle

    def run() -> None:
        try:
            player.play(events, loop=loop, loop_delay=loop_delay, jitter=jitter)
        except Exception:
            logger.exception("playback failed")
        finally:
            toggle.mark_finished()
            print(f"Playback stopped. Press {hotkey} to start again, Ctrl+C to quit.")

    def start() -> None:
        nonlocal worker
        if worker is not None and worker.is_alive():
            logger.warning("playback already running; ignoring start")
            return
        # Safe to clear only because stop() waits for the previous worker.
        stop_event.clear()
        worker = threading.Thread(target=run, name="macro-playback", daemon=True)
        worker.start()

    def stop() -> None:
        stop_event.set()
        # Wait for the worker to actually finish (and release held keys) before
        # returning: a later start() clears stop_event, and a still-running
        # worker would see it cleared and keep playing alongside the new one.
        if worker is not None:
            worker.join(timeout=WORKER_JOIN_TIMEOUT)
            if worker.is_alive():
                logger.error("playback thread did not stop within %.1fs", WORKER_JOIN_TIMEOUT)

    toggle = PlaybackToggle(start, stop)

    def on_hotkey() -> None:
        # Runs on pynput's listener thread: an escaping exception there can
        # kill the hook and leave the hotkey silently dead.
        try:
            toggle.trigger()
        except Exception:
            logger.exception("hotkey handling failed; hotkey still active")

    print(f"Loaded {summary}.")
    print(f"Press {hotkey} to start playback; press it again to stop. Ctrl+C to quit.")
    try:
        with HotkeyListener(hotkey, on_hotkey) as listener:
            listener.join()
    except KeyboardInterrupt:
        print("Quit.")
    finally:
        # Never leave on a playing worker: it would keep sending input, and
        # keys pressed so far would stay held down in-game.
        stop_event.set()
        if worker is not None:
            worker.join(timeout=WORKER_JOIN_TIMEOUT)
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI; returns the process exit code."""
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        if args.command == "record":
            return _do_record(args.name, args.stop_key)
        if args.command == "list":
            return _do_list()
        if args.command == "overlay":
            return _do_overlay(
                args.position,
                click_through=not args.no_click_through,
                alpha=1.0 if args.opaque else 0.85,
            )
        # argparse stores bare --loop as 0; the player spells "forever" as None.
        loop = None if args.loop == 0 else args.loop
        return _do_play(args.name, loop, args.loop_delay, args.jitter, args.hotkey)
    except CORE_ERRORS as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
