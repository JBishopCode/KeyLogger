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
from collections.abc import Sequence

from .events import MacroSerializationError
from .player import BackendUnavailableError, Player, UnknownCodeError
from .recorder import DEFAULT_STOP_CODE, Recorder
from .storage import (
    DEFAULT_MACROS_DIR,
    InvalidMacroNameError,
    MacroNotFoundError,
    load_macro,
    save_macro,
)

logger = logging.getLogger(__name__)

# Every core exception the CLI boundary turns into a message + non-zero exit.
# OSError covers the disk-level failures storage can hit (permission denied,
# disk full, a name Windows refuses); MacroNotFoundError is raised in its place
# for the common "no such macro" case.
CORE_ERRORS = (
    BackendUnavailableError,
    InvalidMacroNameError,
    MacroNotFoundError,
    MacroSerializationError,
    OSError,
    UnknownCodeError,
)

EXIT_OK = 0
EXIT_ERROR = 1


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

    play = subparsers.add_parser("play", help="replay a saved macro")
    play.add_argument("name", help="macro name to replay")

    return parser


def _do_record(name: str, stop_key: str) -> int:
    print(f"Recording '{name}'. Press {stop_key.upper()} to stop.")
    recorder = Recorder(stop_code=stop_key)
    events = recorder.record()
    path = save_macro(name, events, macros_dir=DEFAULT_MACROS_DIR)
    print(f"Saved {len(events)} event(s) to {path}")
    return EXIT_OK


def _do_play(name: str) -> int:
    events = load_macro(name, macros_dir=DEFAULT_MACROS_DIR)
    print(f"Replaying '{name}' ({len(events)} event(s)). Focus Minecraft now.")
    Player().play(events)
    print("Replay finished.")
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
        return _do_play(args.name)
    except CORE_ERRORS as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
