"""Persist named macros as JSON files under ``macros/``.

One file per macro, ``macros/<name>.json``, in the schema documented in
:mod:`macrologger.events`. Storage is local-only: no network, no telemetry.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from pathlib import Path

from .events import (
    MacroEvent,
    MacroSerializationError,
    events_from_dict,
    events_to_dict,
)

logger = logging.getLogger(__name__)

DEFAULT_MACROS_DIR = Path("macros")

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
