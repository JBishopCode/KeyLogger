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
import time
from collections import Counter
from collections.abc import Sequence

from .backend import load_pynput
from .events import MacroEvent, MacroSerializationError
from .hotkey import DEFAULT_HOTKEY, HotkeyListener, InvalidHotkeyError, PlaybackToggle
from .overlay import KeyOverlay, OverlayModel, attach_input_listeners
from .player import BackendUnavailableError, Player, UnknownCodeError
from .recorder import DEFAULT_MOVE_INTERVAL, DEFAULT_STOP_CODE, Recorder
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

#: Grace period before immediate playback, so the user can alt-tab into the
#: game. Not used with --hotkey, where the keypress is the go signal.
DEFAULT_START_DELAY = 3.0

#: Gaps longer than this separate bursts of movement rather than samples
#: within one, so they are excluded from the sampling-rate figure.
MOVE_BURST_GAP = 0.2

#: Median sample gap above which deltas are being merged (2x the ~125Hz
#: default, i.e. samples are arriving at least half as often as requested).
UNDERSAMPLED_GAP = 0.016


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
    record.add_argument(
        "--mouse-movement",
        action="store_true",
        help="also record mouse movement (off by default; replayed as relative motion)",
    )
    record.add_argument(
        "--move-interval",
        type=float,
        default=DEFAULT_MOVE_INTERVAL,
        metavar="SECONDS",
        help=(
            "minimum gap between movement samples "
            f"(default: {DEFAULT_MOVE_INTERVAL}; lower is smoother but larger)"
        ),
    )

    subparsers.add_parser("gui", help="open the control window")

    subparsers.add_parser("list", help="list the macros in the library")

    inspect = subparsers.add_parser(
        "inspect", help="show what a macro contains (event mix, movement, rate)"
    )
    inspect.add_argument("name", help="macro name to inspect")

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
    overlay.add_argument(
        "--diagnose",
        action="store_true",
        help="debug: report screen/monitor layout and the foreground window, then exit",
    )

    play = subparsers.add_parser("play", help="replay a saved macro")
    play.add_argument("name", help="macro name to replay")
    play.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_START_DELAY,
        metavar="SECONDS",
        help=(
            "grace period before playback starts, to alt-tab into the game "
            f"(default: {DEFAULT_START_DELAY:g}; 0 starts immediately). "
            "Ignored with --hotkey."
        ),
    )
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


def _do_record(
    name: str,
    stop_key: str,
    record_movement: bool = False,
    move_interval: float = DEFAULT_MOVE_INTERVAL,
) -> int:
    movement = "on" if record_movement else "off"
    print(f"Recording '{name}' (mouse movement: {movement}).")
    print(f"Press {stop_key.upper()} to stop.")
    recorder = Recorder(
        stop_code=stop_key,
        record_movement=record_movement,
        move_interval=move_interval,
    )
    events = recorder.record()
    path = save_macro(name, events, macros_dir=DEFAULT_MACROS_DIR)
    moves = sum(1 for event in events if event.type == "move")
    print(f"Saved {len(events)} event(s) ({moves} movement) to {path}")
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


def _do_overlay_diagnose() -> int:
    """Report why an overlay might be invisible: monitors, and what's focused.

    Waits a few seconds so the user can alt-tab into the game first.
    """
    import time

    import win32api
    import win32gui

    print("Alt-tab into Minecraft now; reading the screen in 5 seconds...")
    time.sleep(5)

    hwnd = win32gui.GetForegroundWindow()
    title = win32gui.GetWindowText(hwnd)
    rect = win32gui.GetWindowRect(hwnd)
    print(f"\nForeground window: {title!r}")
    print(f"  hwnd  : {hwnd}")
    print(f"  rect  : {rect}  (left, top, right, bottom)")

    monitors = win32api.EnumDisplayMonitors()
    print(f"\nMonitors ({len(monitors)}):")
    for index, (_, _, mrect) in enumerate(monitors, start=1):
        print(f"  {index}: {mrect}")

    virtual = (
        win32api.GetSystemMetrics(76),  # SM_XVIRTUALSCREEN
        win32api.GetSystemMetrics(77),  # SM_YVIRTUALSCREEN
        win32api.GetSystemMetrics(78),  # SM_CXVIRTUALSCREEN
        win32api.GetSystemMetrics(79),  # SM_CYVIRTUALSCREEN
    )
    print(f"\nVirtual screen (x, y, w, h): {virtual}")
    print(
        "\nIf Minecraft's rect covers a monitor exactly with no border, it is "
        "borderless or exclusive fullscreen.\nIf the game is on a monitor whose "
        "rect does not contain (24, 24), the overlay is on the other screen — "
        "rerun with --position inside the game's rect."
    )
    return EXIT_OK


def _do_overlay(
    position: str, click_through: bool = True, alpha: float = 0.85
) -> int:
    """Overlay spike: show live keypresses over whatever is focused.

    Exists so the overlay can be validated over a running Minecraft before the
    rest of the UI is built on top of it.
    """
    # Resolved here so a missing backend fails fast, with a clear message,
    # before any window is created.
    pynput = load_pynput()

    model = OverlayModel()
    overlay = KeyOverlay(
        model,
        position=_parse_position(position),
        alpha=alpha,
        click_through=click_through,
    )
    model.set_recording("overlay test")

    print("Overlay running. Alt-tab into Minecraft and press keys or click.")
    print("It should stay on top, show your input, and NOT take focus.")
    print("Ctrl+C here to close it.")
    listeners = attach_input_listeners(model, pynput=pynput)
    try:
        overlay.run()
    except KeyboardInterrupt:
        pass
    finally:
        for listener in listeners:
            listener.stop()
        overlay.close()
    return EXIT_OK


def _do_inspect(name: str) -> int:
    """Summarize a macro, with the numbers that explain replay fidelity."""
    events = load_macro(name, macros_dir=DEFAULT_MACROS_DIR)
    if not events:
        print(f"'{name}' contains no events.")
        return EXIT_OK

    counts = Counter(event.type for event in events)
    duration = events[-1].t - events[0].t
    moves = [event for event in events if event.type == "move"]

    print(f"Macro '{name}'")
    print(f"  events   : {len(events)} over {duration:.2f}s")
    for event_type in ("key", "click", "move"):
        if counts[event_type]:
            print(f"  {event_type + 's':9}: {counts[event_type]}")

    if moves:
        total_dx = sum(abs(event.dx) for event in moves)
        total_dy = sum(abs(event.dy) for event in moves)
        biggest = max(max(abs(e.dx), abs(e.dy)) for e in moves)
        print(f"  movement : {total_dx} px horizontal, {total_dy} px vertical")
        print(
            f"  net drift: dx={sum(e.dx for e in moves)}, "
            f"dy={sum(e.dy for e in moves)}"
        )

        # Rate while actually moving. Averaging over the whole macro is
        # meaningless: sampling only happens when the mouse reports, so idle
        # stretches drag the figure down and hide the real cadence.
        gaps = sorted(
            b.t - a.t
            for a, b in zip(moves, moves[1:], strict=False)
            if 0 < b.t - a.t <= MOVE_BURST_GAP
        )
        if gaps:
            median_gap = gaps[len(gaps) // 2]
            print(
                f"  sampling : {1 / median_gap:.0f} Hz while moving, "
                f"largest single step {biggest} px"
            )
            # Big steps from a fast flick are legitimate; steps that are big
            # *because samples are far apart* are merged deltas, which is what
            # sends the camera off-heading.
            if median_gap > UNDERSAMPLED_GAP and biggest > 40:
                print(
                    "  NOTE: samples are further apart than requested, so "
                    "deltas were merged. Windows pointer acceleration scales "
                    "one big jump differently to the small moves it replaced, "
                    "so the camera can end on a different heading. Re-record "
                    "with a smaller --move-interval."
                )
        else:
            print(f"  sampling : single burst, largest step {biggest} px")
    return EXIT_OK


def _countdown(seconds: float) -> None:
    """Give the user time to alt-tab into the game before input starts."""
    if seconds <= 0:
        return
    print(f"Alt-tab into Minecraft now - starting in {seconds:g}s...")
    whole = int(seconds)
    for remaining in range(whole, 0, -1):
        print(f"  {remaining}...", flush=True)
        time.sleep(1)
    leftover = seconds - whole
    if leftover > 0:
        time.sleep(leftover)
    print("Go.")


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
    delay: float = DEFAULT_START_DELAY,
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
        print(f"Replaying {summary}.")
        _countdown(delay)
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
            return _do_record(
                args.name,
                args.stop_key,
                record_movement=args.mouse_movement,
                move_interval=args.move_interval,
            )
        if args.command == "gui":
            from .ui import run_app

            run_app(macros_dir=DEFAULT_MACROS_DIR)
            return EXIT_OK
        if args.command == "list":
            return _do_list()
        if args.command == "inspect":
            return _do_inspect(args.name)
        if args.command == "overlay":
            if args.diagnose:
                return _do_overlay_diagnose()
            return _do_overlay(
                args.position,
                click_through=not args.no_click_through,
                alpha=1.0 if args.opaque else 0.85,
            )
        # argparse stores bare --loop as 0; the player spells "forever" as None.
        loop = None if args.loop == 0 else args.loop
        return _do_play(
            args.name,
            loop,
            args.loop_delay,
            args.jitter,
            args.hotkey,
            delay=args.delay,
        )
    except CORE_ERRORS as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
