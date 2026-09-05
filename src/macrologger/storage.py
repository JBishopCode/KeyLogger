"""Persist named macros as JSON files under ``macros/``.

One file per macro, ``macros/<name>.json``, in the schema documented in
:mod:`macrologger.events`. Storage is local-only: no network, no telemetry.
"""

from __future__ import annotations

import json
import logging
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .events import (
    MacroEvent,
    MacroSerializationError,
    events_from_dict,
    events_to_dict,
)

logger = logging.getLogger(__name__)

def default_macros_dir() -> Path:
    """Where macros live.

    Running from source that is ``./macros``. In a packaged .exe it is a
    ``macros`` folder beside the executable, so double-clicking the app from
    anywhere still finds the same library instead of scattering files into
    whatever directory Windows happened to launch it from.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "macros"
    return Path("macros")


DEFAULT_MACROS_DIR = default_macros_dir()

_ALLOWED_NAME_EXTRAS = {"-", "_", "."}

# Windows refuses to create a file whose stem is a reserved device name, with
# or without an extension, so reject them up front with a clear message.
_RESERVED_NAMES = {"con", "prn", "aux", "nul"} | {
    f"{prefix}{n}" for prefix in ("com", "lpt") for n in range(10)
}


class MacroNotFoundError(Exception):
    """Raised when the requested macro file does not exist."""


class InvalidMacroNameError(Exception):
    """Raised when a macro name is empty or not a safe single filename."""


def _validate_name(name: str) -> str:
    """Reject names that are empty or could escape the macros directory."""
    if not name or any(
        not (char.isalnum() or char in _ALLOWED_NAME_EXTRAS) for char in name
    ):
        raise InvalidMacroNameError(
            f"invalid macro name {name!r}: use letters, digits, '-', '_' or '.'"
        )
    if name.strip(".") == "":
        raise InvalidMacroNameError(f"invalid macro name {name!r}")
    if name.split(".")[0].lower() in _RESERVED_NAMES:
        raise InvalidMacroNameError(
            f"invalid macro name {name!r}: reserved Windows device name"
        )
    return name


def macro_path(name: str, macros_dir: Path | str = DEFAULT_MACROS_DIR) -> Path:
    """Return the JSON file path for macro ``name``."""
    return Path(macros_dir) / f"{_validate_name(name)}.json"


def save_macro(
    name: str,
    events: Sequence[MacroEvent],
    macros_dir: Path | str = DEFAULT_MACROS_DIR,
) -> Path:
    """Write ``events`` to ``macros_dir/<name>.json`` and return that path."""
    path = macro_path(name, macros_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = events_to_dict(name, events)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("saved %d event(s) to %s", len(events), path)
    return path


def _dominant_window(events: Sequence[MacroEvent]) -> str:
    """The window most events were recorded in.

    Not the first event's window: recording typically starts in the terminal
    and only then alt-tabs into the game, so the first title is misleading.
    Blank titles are ignored.
    """
    titles = Counter(event.window for event in events if event.window)
    if not titles:
        return ""
    return titles.most_common(1)[0][0]


@dataclass(frozen=True, slots=True)
class MacroSummary:
    """One row of the macro library listing."""

    name: str
    created: str
    event_count: int
    duration: float
    window: str


def list_macros(macros_dir: Path | str = DEFAULT_MACROS_DIR) -> list[MacroSummary]:
    """Summarize every readable macro in ``macros_dir``, sorted by name.

    Unreadable or malformed files are logged and skipped rather than breaking
    the whole listing.
    """
    directory = Path(macros_dir)
    if not directory.is_dir():
        return []

    summaries = []
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            events = events_from_dict(payload)
        except (OSError, json.JSONDecodeError, MacroSerializationError):
            logger.warning("skipping unreadable macro file %s", path, exc_info=True)
            continue
        summaries.append(
            MacroSummary(
                name=path.stem,
                created=str(payload.get("created", "")),
                event_count=len(events),
                duration=events[-1].t if events else 0.0,
                window=_dominant_window(events),
            )
        )
    return summaries


def load_macro(
    name: str, macros_dir: Path | str = DEFAULT_MACROS_DIR
) -> list[MacroEvent]:
    """Read the events of macro ``name``.

    Raises:
        MacroNotFoundError: if the file does not exist.
        MacroSerializationError: if the file is not valid macro JSON.
    """
    path = macro_path(name, macros_dir)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise MacroNotFoundError(f"no macro named {name!r} at {path}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MacroSerializationError(f"{path} is not valid JSON: {exc}") from exc
    events = events_from_dict(payload)
    logger.info("loaded %d event(s) from %s", len(events), path)
    return events
