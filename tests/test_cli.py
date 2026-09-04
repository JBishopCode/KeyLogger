"""Tests for the CLI boundary: exit codes, messages, and wiring.

The recorder and player are replaced with fakes, so no global hook is
installed and no input is ever sent during the test run.
"""

import pytest

from macrologger import cli
from macrologger.events import MacroEvent
from macrologger.player import BackendUnavailableError, UnknownCodeError
from macrologger.storage import save_macro


@pytest.fixture
def macros_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "DEFAULT_MACROS_DIR", tmp_path)
    return tmp_path


def sample_events():
    return [
        MacroEvent(0.0, "key", "down", "w", "Minecraft 1.21"),
        MacroEvent(0.4, "key", "up", "w", "Minecraft 1.21"),
    ]


class FakeRecorder:
    def __init__(self, *args, **kwargs):
        self.events = sample_events()

    def record(self):
        return self.events


class FakePlayer:
    played = []

    def __init__(self, *args, **kwargs):
        pass

    def play(self, events):
        FakePlayer.played = list(events)


def test_record_saves_the_captured_events(macros_dir, monkeypatch):
    monkeypatch.setattr(cli, "Recorder", FakeRecorder)

    assert cli.main(["record", "demo"]) == 0
    assert (macros_dir / "demo.json").is_file()


def test_play_replays_the_saved_events(macros_dir, monkeypatch):
    monkeypatch.setattr(cli, "Player", FakePlayer)
    save_macro("demo", sample_events(), macros_dir=macros_dir)

    assert cli.main(["play", "demo"]) == 0
    assert FakePlayer.played == sample_events()


def test_play_missing_macro_exits_non_zero_with_a_message(macros_dir, capsys):
    exit_code = cli.main(["play", "nope"])

    assert exit_code != 0
    assert "nope" in capsys.readouterr().err


def test_play_unknown_code_exits_non_zero_with_a_message(
    macros_dir, monkeypatch, capsys
):
    class ExplodingPlayer:
        def __init__(self, *args, **kwargs):
            pass

        def play(self, events):
            raise UnknownCodeError("no DirectInput key for code 'nope'")

    monkeypatch.setattr(cli, "Player", ExplodingPlayer)
    save_macro("demo", sample_events(), macros_dir=macros_dir)

    exit_code = cli.main(["play", "demo"])

    assert exit_code != 0
    assert "nope" in capsys.readouterr().err


def test_invalid_macro_name_exits_non_zero(macros_dir, monkeypatch, capsys):
    monkeypatch.setattr(cli, "Recorder", FakeRecorder)

    exit_code = cli.main(["record", "../escape"])

    assert exit_code != 0
    assert capsys.readouterr().err.strip() != ""


def test_keyboard_interrupt_exits_non_zero_with_a_message(macros_dir, monkeypatch, capsys):
    class InterruptedRecorder:
        def __init__(self, *args, **kwargs):
            pass

        def record(self):
            raise KeyboardInterrupt

    monkeypatch.setattr(cli, "Recorder", InterruptedRecorder)

    exit_code = cli.main(["record", "demo"])

    assert exit_code != 0
    assert "interrupted" in capsys.readouterr().err


def test_unwritable_macros_dir_exits_non_zero_with_a_message(
    macros_dir, monkeypatch, capsys
):
    monkeypatch.setattr(cli, "Recorder", FakeRecorder)

    def denied(*args, **kwargs):
        raise PermissionError("access is denied")

    monkeypatch.setattr(cli, "save_macro", denied)

    exit_code = cli.main(["record", "demo"])

    assert exit_code != 0
    assert "denied" in capsys.readouterr().err


def test_missing_input_backend_exits_non_zero_with_a_message(
    macros_dir, monkeypatch, capsys
):
    def no_backend(*args, **kwargs):
        raise BackendUnavailableError("pydirectinput is not installed")

    monkeypatch.setattr(cli, "Player", no_backend)
    save_macro("demo", sample_events(), macros_dir=macros_dir)

    exit_code = cli.main(["play", "demo"])

    assert exit_code != 0
    assert "pydirectinput" in capsys.readouterr().err


def test_unknown_command_exits_non_zero(macros_dir):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["frobnicate", "demo"])

    assert excinfo.value.code != 0
