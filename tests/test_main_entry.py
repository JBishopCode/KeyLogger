"""Tests for the packaged entry point.

A --windowed PyInstaller build has no console: sys.stdout is None, so CLI
output vanishes. These pin the behaviour that keeps it visible.
"""

import io

from macrologger.__main__ import has_console, run_cli


def test_console_detected_when_stdout_exists_and_a_console_is_attached():
    assert has_console(io.StringIO(), console_window=lambda: 12345) is True


def test_no_console_when_stdout_is_none():
    assert has_console(None, console_window=lambda: 12345) is False


def test_no_console_when_windows_reports_no_console_window():
    """A --windowed build can still hand out a stdout that goes nowhere.

    GetConsoleWindow() returning 0 is the reliable signal, and this is the
    case that made `MacroLogger.exe doctor` print absolutely nothing.
    """
    assert has_console(io.StringIO(), console_window=lambda: 0) is False


def test_console_check_failure_falls_back_to_trusting_stdout():
    """Better to print into a terminal that exists than to hide the output."""

    def boom():
        raise OSError("no kernel32")

    assert has_console(io.StringIO(), console_window=boom) is True


def test_with_a_console_output_is_not_captured():
    shown = []

    def runner():
        print("hello")
        return 0

    code = run_cli(
        runner,
        stdout=io.StringIO(),
        show_dialog=shown.append,
        console_window=lambda: 12345,
    )

    assert code == 0
    assert shown == []


def test_without_a_console_output_goes_to_a_dialog():
    shown = []

    def runner():
        print("ok  pynput")
        print("ok  tkinter")
        return 0

    code = run_cli(runner, stdout=None, show_dialog=shown.append)

    assert code == 0
    assert "pynput" in shown[0]
    assert "tkinter" in shown[0]


def test_errors_are_shown_too_rather_than_vanishing():
    shown = []

    def runner():
        raise RuntimeError("backend exploded")

    code = run_cli(runner, stdout=None, show_dialog=shown.append)

    assert code != 0
    assert "backend exploded" in shown[0]


def test_a_silent_command_still_reports_something():
    shown = []

    code = run_cli(lambda: 0, stdout=None, show_dialog=shown.append)

    assert code == 0
    assert shown and shown[0].strip() != ""
