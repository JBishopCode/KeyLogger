"""Tests for the control window's pure helpers (no Tk required)."""

from macrologger.storage import MacroSummary
from macrologger.ui import format_macro_row, index_of_macro, macro_name_from_row


def summary(name, events=10, duration=1.5, window="Minecraft 1.21"):
    return MacroSummary(
        name=name,
        created="2026-09-04T00:00:00Z",
        event_count=events,
        duration=duration,
        window=window,
    )


def test_row_starts_with_the_macro_name():
    row = format_macro_row(summary("fishing"))

    assert row.startswith("fishing")


def test_row_shows_counts_and_context():
    row = format_macro_row(summary("demo", events=130, duration=21.6))

    assert "130" in row
    assert "21.6" in row
    assert "Minecraft" in row


def test_name_round_trips_through_a_row():
    row = format_macro_row(summary("fishing-cast_2"))

    assert macro_name_from_row(row) == "fishing-cast_2"


def test_finds_the_index_of_a_macro():
    summaries = [summary("alpha"), summary("beta"), summary("gamma")]

    assert index_of_macro(summaries, "beta") == 1


def test_missing_macro_has_no_index():
    """Selection cannot be restored if the macro is gone."""
    assert index_of_macro([summary("alpha")], "deleted") is None


def test_no_previous_selection_has_no_index():
    assert index_of_macro([summary("alpha")], None) is None
