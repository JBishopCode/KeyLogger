"""Tests for saving and loading named macros under macros/."""

import json

import pytest

from macrologger.events import MacroEvent, MacroSerializationError
from macrologger.storage import (
    InvalidMacroNameError,
    MacroNotFoundError,
    load_macro,
    macro_path,
    save_macro,
)


def sample_events():
    return [
        MacroEvent(0.0, "key", "down", "w", "Minecraft 1.21"),
        MacroEvent(0.412, "key", "up", "w", "Minecraft 1.21"),
        MacroEvent(0.9, "click", "down", "right", "Minecraft 1.21"),
    ]


def test_save_then_load_returns_identical_events(tmp_path):
    save_macro("demo", sample_events(), macros_dir=tmp_path)

    assert load_macro("demo", macros_dir=tmp_path) == sample_events()


def test_save_writes_the_documented_schema(tmp_path):
    save_macro("demo", sample_events(), macros_dir=tmp_path)

    payload = json.loads((tmp_path / "demo.json").read_text(encoding="utf-8"))

    assert payload["name"] == "demo"
    assert set(payload) == {"name", "created", "events"}
    assert payload["events"][2] == {
        "t": 0.9,
        "type": "click",
        "action": "down",
        "code": "right",
        "window": "Minecraft 1.21",
    }


def test_save_creates_the_macros_directory(tmp_path):
    target = tmp_path / "macros"

    save_macro("demo", sample_events(), macros_dir=target)

    assert (target / "demo.json").is_file()


def test_save_returns_the_written_path(tmp_path):
    path = save_macro("demo", sample_events(), macros_dir=tmp_path)

    assert path == tmp_path / "demo.json"


def test_save_overwrites_an_existing_macro(tmp_path):
    save_macro("demo", sample_events(), macros_dir=tmp_path)
    save_macro("demo", [MacroEvent(0.0, "key", "down", "a", "")], macros_dir=tmp_path)

    assert [e.code for e in load_macro("demo", macros_dir=tmp_path)] == ["a"]


def test_empty_macro_round_trips(tmp_path):
    save_macro("empty", [], macros_dir=tmp_path)

    assert load_macro("empty", macros_dir=tmp_path) == []


def test_load_missing_macro_raises(tmp_path):
    with pytest.raises(MacroNotFoundError):
        load_macro("nope", macros_dir=tmp_path)


def test_load_malformed_json_raises_serialization_error(tmp_path):
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(MacroSerializationError):
        load_macro("broken", macros_dir=tmp_path)


def test_load_wrong_schema_raises_serialization_error(tmp_path):
    (tmp_path / "bad.json").write_text('{"name": "bad"}', encoding="utf-8")

    with pytest.raises(MacroSerializationError):
        load_macro("bad", macros_dir=tmp_path)


@pytest.mark.parametrize("name", ["", "..", "../escape", "sub/dir", "back\\slash"])
def test_names_that_could_escape_the_macros_dir_are_rejected(tmp_path, name):
    with pytest.raises(InvalidMacroNameError):
        macro_path(name, macros_dir=tmp_path)


@pytest.mark.parametrize("name", ["con", "PRN", "aux", "nul", "com1", "LPT9"])
def test_windows_reserved_device_names_are_rejected(tmp_path, name):
    with pytest.raises(InvalidMacroNameError):
        macro_path(name, macros_dir=tmp_path)


def test_valid_names_are_accepted(tmp_path):
    path = macro_path("fishing-cast_2", macros_dir=tmp_path)

    assert path.name == "fishing-cast_2.json"
