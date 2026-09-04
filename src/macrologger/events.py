"""Macro event model and JSON (de)serialization.

A macro file has the shape::

    {
      "name": "fishing-cast",
      "created": "2026-09-04T00:00:00Z",
      "events": [
        {"t": 0.0, "type": "key", "action": "down", "code": "w", "window": "Minecraft 1.21"}
      ]
    }

``t`` is seconds since recording start (``time.perf_counter()`` based), which
gives exact inter-event gaps on replay.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

#: Current macro schema version. v1 had no "move" events and no dx/dy.
SCHEMA_VERSION = 2

EVENT_TYPES = ("key", "click", "move")
EVENT_ACTIONS = ("down", "up", "move")
EVENT_FIELDS = ("t", "type", "action", "code", "window")

#: Optional fields, absent in v1 macros.
EVENT_DELTA_FIELDS = ("dx", "dy")


class MacroSerializationError(Exception):
    """Raised when a macro payload does not match the expected schema."""


@dataclass(frozen=True, slots=True)
class MacroEvent:
    """A single recorded input event.

    Attributes:
        t: Seconds since recording start.
        type: ``"key"`` or ``"click"``.
        action: ``"down"`` or ``"up"``.
        code: Key name (``"w"``, ``"f3"``, ``"shift"``) or button (``"left"``).
        window: Active window title when the event was recorded.
    """

    t: float
    type: str
    action: str
    code: str
    window: str
    dx: int = 0
    dy: int = 0

    def __post_init__(self) -> None:
        if self.type not in EVENT_TYPES:
            raise ValueError(f"unknown event type: {self.type!r}")
        if self.action not in EVENT_ACTIONS:
            raise ValueError(f"unknown event action: {self.action!r}")
        # "move" pairs with "move"; key/click pair with down/up. Mixing them
        # would produce events no player could dispatch.
        if (self.type == "move") != (self.action == "move"):
            raise ValueError(
                f"invalid {self.type!r} event with action {self.action!r}"
            )
        # Normalize so a round trip through JSON is value-identical.
        object.__setattr__(self, "t", float(self.t))

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "t": self.t,
            "type": self.type,
            "action": self.action,
            "code": self.code,
            "window": self.window,
        }
        # Only movement carries deltas; keeping them off key/click events keeps
        # macro files readable and diffable.
        if self.type == "move":
            payload["dx"] = self.dx
            payload["dy"] = self.dy
        return payload

    @classmethod
    def from_dict(cls, data: Any) -> MacroEvent:
        if not isinstance(data, dict):
            raise MacroSerializationError(
                f"event must be an object, got {type(data).__name__}"
            )
        missing = [field for field in EVENT_FIELDS if field not in data]
        if missing:
            raise MacroSerializationError(
                f"event missing field(s): {', '.join(missing)}"
            )
        try:
            return cls(
                t=float(data["t"]),
                type=data["type"],
                action=data["action"],
                code=str(data["code"]),
                window=str(data["window"]),
                dx=int(data.get("dx", 0)),
                dy=int(data.get("dy", 0)),
            )
        except (TypeError, ValueError) as exc:
            raise MacroSerializationError(f"invalid event {data!r}: {exc}") from exc


def utc_now_iso() -> str:
    """Current UTC time as an ISO8601 string with a trailing ``Z``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def events_to_dict(
    name: str, events: Iterable[MacroEvent], created: str | None = None
) -> dict[str, Any]:
    """Build the macro payload for ``name`` from ``events``."""
    return {
        "name": name,
        "created": created or utc_now_iso(),
        "version": SCHEMA_VERSION,
        "events": [event.to_dict() for event in events],
    }


def events_from_dict(payload: Any) -> list[MacroEvent]:
    """Parse the ``events`` list out of a macro payload.

    Raises:
        MacroSerializationError: if the payload or any event is malformed.
    """
    if not isinstance(payload, dict):
        raise MacroSerializationError(
            f"macro must be an object, got {type(payload).__name__}"
        )
    if "events" not in payload:
        raise MacroSerializationError("macro missing 'events' key")
    raw_events = payload["events"]
    if not isinstance(raw_events, list):
        raise MacroSerializationError("macro 'events' must be a list")
    return [MacroEvent.from_dict(item) for item in raw_events]
