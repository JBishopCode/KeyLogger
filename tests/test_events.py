"""Tests for the macro event model and its JSON serialization."""

import dataclasses

import pytest

from macrologger.events import (
    MacroEvent,
    MacroSerializationError,
    events_from_dict,
    events_to_dict,
)


def sample_events():
    return [
        MacroEvent(t=0.0, type="key", action="down", code="w", window="Minecraft 1.21"),
        MacroEvent(t=0.412, type="key", action="up", code="w", window="Minecraft 1.21"),
        MacroEvent(
            t=0.9, type="click", action="down", code="right", window="Minecraft 1.21"
        ),
    ]


def test_events_to_dict_matches_schema():
    payload = events_to_dict(
        "fishing-cast", sample_events(), created="2026-09-04T00:00:00Z"
    )

    assert payload["name"] == "fishing-cast"
    assert payload["created"] == "2026-09-04T00:00:00Z"
    assert payload["events"][0] == {
        "t": 0.0,
        "type": "key",
        "action": "down",
        "code": "w",
        "window": "Minecraft 1.21",
    }


def test_created_defaults_to_iso8601_utc():
    payload = events_to_dict("demo", sample_events())

    assert payload["created"].endswith("Z")
    assert "T" in payload["created"]


def test_round_trip_is_lossless():
    original = sample_events()

    restored = events_from_dict(events_to_dict("demo", original))

    assert restored == original


def test_round_trip_preserves_t_as_float():
    payload = events_to_dict("demo", [MacroEvent(0, "key", "down", "w", "")])

    restored = events_from_dict(payload)

    assert isinstance(restored[0].t, float)
    assert restored[0].t == 0.0


def test_from_dict_rejects_missing_events_key():
    with pytest.raises(MacroSerializationError):
        events_from_dict({"name": "demo", "created": "2026-09-04T00:00:00Z"})


def test_from_dict_rejects_missing_event_field():
    payload = {
        "name": "demo",
        "created": "2026-09-04T00:00:00Z",
        "events": [{"t": 0.0, "type": "key", "action": "down", "code": "w"}],
    }

    with pytest.raises(MacroSerializationError):
        events_from_dict(payload)


def test_move_events_carry_relative_deltas():
    event = MacroEvent(
        t=0.5, type="move", action="move", code="", window="", dx=12, dy=-4
    )

    assert (event.dx, event.dy) == (12, -4)


def test_move_events_round_trip():
    events = [MacroEvent(0.5, "move", "move", "", "", dx=12, dy=-4)]

    restored = events_from_dict(events_to_dict("demo", events))

    assert restored == events


def test_move_event_serializes_deltas():
    payload = events_to_dict("demo", [MacroEvent(0.5, "move", "move", "", "", 3, 4)])

    assert payload["events"][0]["dx"] == 3
    assert payload["events"][0]["dy"] == 4


def test_key_events_default_to_zero_deltas():
    event = MacroEvent(0.0, "key", "down", "w", "")

    assert (event.dx, event.dy) == (0, 0)


def test_payload_declares_the_schema_version():
    assert events_to_dict("demo", [])["version"] == 2


def test_version_1_macros_without_deltas_still_load():
    """Macros recorded before mouse movement existed must keep working."""
    payload = {
        "name": "old",
        "created": "2026-09-04T00:00:00Z",
        "events": [
            {"t": 0.0, "type": "key", "action": "down", "code": "w", "window": ""}
        ],
    }

    restored = events_from_dict(payload)

    assert restored == [MacroEvent(0.0, "key", "down", "w", "")]


def test_move_action_must_be_move():
    with pytest.raises(ValueError):
        MacroEvent(0.0, "move", "down", "", "", 1, 1)


def test_key_events_cannot_use_the_move_action():
    with pytest.raises(ValueError):
        MacroEvent(0.0, "key", "move", "w", "")


def test_event_is_frozen():
    event = MacroEvent(0.0, "key", "down", "w", "")

    with pytest.raises(dataclasses.FrozenInstanceError):
        event.t = 1.0


def test_from_dict_rejects_non_dict_payload():
    with pytest.raises(MacroSerializationError):
        events_from_dict(42)


def test_from_dict_rejects_non_dict_event_item():
    with pytest.raises(MacroSerializationError):
        events_from_dict({"name": "demo", "created": "x", "events": ["oops"]})


def test_empty_event_list_round_trips():
    assert events_from_dict(events_to_dict("empty", [])) == []


def test_event_rejects_unknown_type():
    with pytest.raises(ValueError):
        MacroEvent(t=0.0, type="scroll", action="down", code="w", window="")


def test_event_rejects_unknown_action():
    with pytest.raises(ValueError):
        MacroEvent(t=0.0, type="key", action="hold", code="w", window="")
