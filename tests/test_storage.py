"""Tests for saving and loading named macros under macros/."""

import json

import pytest

from macrologger.events import MacroEvent, MacroSerializationError
from macrologger.storage import (
    InvalidMacroNameError,
    MacroNotFoundError,
    list_macros,
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


def test_list_macros_is_empty_when_the_directory_does_not_exist(tmp_path):
    assert list_macros(macros_dir=tmp_path / "nope") == []


def test_list_macros_returns_names_sorted(tmp_path):
    for name in ("zeta", "alpha", "mid"):
        save_macro(name, sample_events(), macros_dir=tmp_path)

    assert [summary.name for summary in list_macros(macros_dir=tmp_path)] == [
        "alpha",
        "mid",
        "zeta",
    ]


def test_list_macros_reports_event_count_created_and_window(tmp_path):
    save_macro("demo", sample_events(), macros_dir=tmp_path)

    summary = list_macros(macros_dir=tmp_path)[0]

    assert summary.event_count == 3
    assert summary.created.endswith("Z")
    assert summary.window == "Minecraft 1.21"


def test_list_macros_reports_the_most_common_window_not_the_first(tmp_path):
    """Recording usually starts in the terminal, then alt-tabs into the game."""
    events = [
        MacroEvent(0.0, "key", "down", "w", "KeyLogger - Visual Studio Code"),
        MacroEvent(0.1, "key", "up", "w", "Minecraft 1.21"),
        MacroEvent(0.2, "key", "down", "a", "Minecraft 1.21"),
        MacroEvent(0.3, "key", "up", "a", "Minecraft 1.21"),
    ]
    save_macro("demo", events, macros_dir=tmp_path)

    assert list_macros(macros_dir=tmp_path)[0].window == "Minecraft 1.21"


def test_list_macros_ignores_blank_windows_when_picking_the_common_one(tmp_path):
    events = [
        MacroEvent(0.0, "key", "down", "w", ""),
        MacroEvent(0.1, "key", "up", "w", ""),
        MacroEvent(0.2, "key", "down", "a", "Minecraft 1.21"),
    ]
    save_macro("demo", events, macros_dir=tmp_path)

    assert list_macros(macros_dir=tmp_path)[0].window == "Minecraft 1.21"


def test_list_macros_reports_duration_from_the_last_event(tmp_path):
    save_macro("demo", sample_events(), macros_dir=tmp_path)

    assert list_macros(macros_dir=tmp_path)[0].duration == pytest.approx(0.9)


def test_list_macros_handles_an_empty_macro(tmp_path):
    save_macro("empty", [], macros_dir=tmp_path)

    summary = list_macros(macros_dir=tmp_path)[0]

    assert (summary.event_count, summary.duration, summary.window) == (0, 0.0, "")


def test_list_macros_skips_unreadable_files_instead_of_failing(tmp_path):
    save_macro("good", sample_events(), macros_dir=tmp_path)
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")

    assert [summary.name for summary in list_macros(macros_dir=tmp_path)] == ["good"]


def test_list_macros_ignores_non_json_files(tmp_path):
    save_macro("good", sample_events(), macros_dir=tmp_path)
    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")

    assert [summary.name for summary in list_macros(macros_dir=tmp_path)] == ["good"]


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
