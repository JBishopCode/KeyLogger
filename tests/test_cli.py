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
    options = {}

    def __init__(self, *args, **kwargs):
        pass

    def play(self, events, **kwargs):
        FakePlayer.played = list(events)
        FakePlayer.options = kwargs


def test_record_saves_the_captured_events(macros_dir, monkeypatch):
    monkeypatch.setattr(cli, "Recorder", FakeRecorder)

    assert cli.main(["record", "demo"]) == 0
    assert (macros_dir / "demo.json").is_file()


def test_play_replays_the_saved_events(macros_dir, monkeypatch):
    monkeypatch.setattr(cli, "Player", FakePlayer)
    save_macro("demo", sample_events(), macros_dir=macros_dir)

    assert cli.main(["play", "demo", "--delay", "0"]) == 0
    assert FakePlayer.played == sample_events()


def test_play_defaults_to_a_single_pass_without_jitter(macros_dir, monkeypatch):
    monkeypatch.setattr(cli, "Player", FakePlayer)
    save_macro("demo", sample_events(), macros_dir=macros_dir)

    cli.main(["play", "demo", "--delay", "0"])

    assert FakePlayer.options == {"loop": 1, "loop_delay": 0.0, "jitter": 0.0}


def test_loop_count_and_jitter_flags_reach_the_player(macros_dir, monkeypatch):
    monkeypatch.setattr(cli, "Player", FakePlayer)
    save_macro("demo", sample_events(), macros_dir=macros_dir)

    cli.main(["play", "demo", "--delay", "0", "--loop", "4", "--loop-delay", "2.5", "--jitter", "0.1"])

    assert FakePlayer.options == {"loop": 4, "loop_delay": 2.5, "jitter": 0.1}


def test_bare_loop_flag_means_repeat_until_stopped(macros_dir, monkeypatch):
    captured = {}

    def fake_hotkey_play(events, summary, hotkey, loop, loop_delay, jitter):
        captured["loop"] = loop
        captured["hotkey"] = hotkey
        return 0

    monkeypatch.setattr(cli, "_play_with_hotkey", fake_hotkey_play)
    save_macro("demo", sample_events(), macros_dir=macros_dir)

    cli.main(["play", "demo", "--loop", "--hotkey"])

    assert captured == {"loop": None, "hotkey": "f8"}


def test_endless_loop_without_a_hotkey_is_refused_with_a_message(macros_dir, capsys):
    """There would be no way to stop it, so say so instead of crashing."""
    save_macro("demo", sample_events(), macros_dir=macros_dir)

    exit_code = cli.main(["play", "demo", "--loop"])

    err = capsys.readouterr().err
    assert exit_code != 0
    assert "--hotkey" in err
    assert "Traceback" not in err


def test_invalid_hotkey_exits_non_zero_with_a_message(macros_dir, capsys):
    save_macro("demo", sample_events(), macros_dir=macros_dir)

    exit_code = cli.main(["play", "demo", "--hotkey", "ctrl+nope"])

    assert exit_code != 0
    assert "nope" in capsys.readouterr().err


def test_play_waits_before_starting_so_you_can_alt_tab(macros_dir, monkeypatch):
    slept = []
    monkeypatch.setattr(cli, "Player", FakePlayer)
    monkeypatch.setattr(cli.time, "sleep", lambda s: slept.append(s))
    save_macro("demo", sample_events(), macros_dir=macros_dir)

    cli.main(["play", "demo"])

    assert sum(slept) >= 3  # default grace period, in seconds


def test_start_delay_is_configurable(macros_dir, monkeypatch):
    slept = []
    monkeypatch.setattr(cli, "Player", FakePlayer)
    monkeypatch.setattr(cli.time, "sleep", lambda s: slept.append(s))
    save_macro("demo", sample_events(), macros_dir=macros_dir)

    cli.main(["play", "demo", "--delay", "7"])

    assert sum(slept) == 7


def test_zero_delay_starts_immediately(macros_dir, monkeypatch):
    slept = []
    monkeypatch.setattr(cli, "Player", FakePlayer)
    monkeypatch.setattr(cli.time, "sleep", lambda s: slept.append(s))
    save_macro("demo", sample_events(), macros_dir=macros_dir)

    cli.main(["play", "demo", "--delay", "0"])

    assert slept == []


def test_hotkey_playback_does_not_add_a_start_delay(macros_dir, monkeypatch):
    """The hotkey press IS the go signal; a countdown would fight it."""
    slept = []
    captured = {}
    monkeypatch.setattr(cli.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(
        cli, "_play_with_hotkey", lambda *a, **k: captured.setdefault("ran", True) or 0
    )
    save_macro("demo", sample_events(), macros_dir=macros_dir)

    cli.main(["play", "demo", "--hotkey"])

    assert captured["ran"] is True
    assert slept == []


def test_play_missing_macro_exits_non_zero_with_a_message(macros_dir, capsys):
    exit_code = cli.main(["play", "nope", "--delay", "0"])

    assert exit_code != 0
    assert "nope" in capsys.readouterr().err


def test_play_unknown_code_exits_non_zero_with_a_message(
    macros_dir, monkeypatch, capsys
):
    class ExplodingPlayer:
        def __init__(self, *args, **kwargs):
            pass

        def play(self, events, **kwargs):
            raise UnknownCodeError("no DirectInput key for code 'nope'")

    monkeypatch.setattr(cli, "Player", ExplodingPlayer)
    save_macro("demo", sample_events(), macros_dir=macros_dir)

    exit_code = cli.main(["play", "demo", "--delay", "0"])

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

    exit_code = cli.main(["play", "demo", "--delay", "0"])

    assert exit_code != 0
    assert "pydirectinput" in capsys.readouterr().err


def test_list_shows_saved_macros_with_context(macros_dir, capsys):
    save_macro("demo", sample_events(), macros_dir=macros_dir)

    exit_code = cli.main(["list"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "demo" in output
    assert "Minecraft 1.21" in output
    assert "2" in output  # event count


def test_list_on_an_empty_library_says_so(macros_dir, capsys):
    exit_code = cli.main(["list"])

    assert exit_code == 0
    assert "no macros" in capsys.readouterr().out.lower()


def test_missing_pynput_exits_with_advice_not_a_traceback(
    macros_dir, monkeypatch, capsys
):
    """Running with the wrong Python must not dump a ModuleNotFoundError."""

    def no_pynput():
        raise BackendUnavailableError(
            "pynput is not installed; run: pip install -r requirements.txt"
        )

    monkeypatch.setattr(cli, "load_pynput", no_pynput)

    exit_code = cli.main(["overlay"])

    err = capsys.readouterr().err
    assert exit_code != 0
    assert "pip install" in err
    assert "Traceback" not in err


def test_bad_overlay_position_exits_non_zero(macros_dir, capsys):
    exit_code = cli.main(["overlay", "--position", "middle"])

    assert exit_code != 0
    assert "X,Y" in capsys.readouterr().err


def test_inspect_summarizes_event_types_and_movement(macros_dir, capsys):
    events = [
        MacroEvent(0.0, "key", "down", "w", "Minecraft 1.21"),
        MacroEvent(0.1, "move", "move", "", "Minecraft 1.21", 10, -5),
        MacroEvent(0.2, "move", "move", "", "Minecraft 1.21", 6, 2),
        MacroEvent(0.3, "click", "down", "right", "Minecraft 1.21"),
    ]
    save_macro("demo", events, macros_dir=macros_dir)

    exit_code = cli.main(["inspect", "demo"])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "2" in out  # movement event count
    assert "16" in out  # total |dx| travelled: 10 + 6


def test_inspect_reports_the_rate_while_actually_moving(macros_dir, capsys):
    """Idle time must not drag the reported rate down.

    Two bursts sampled 8ms apart, separated by a 10s pause: the average over
    the whole macro is meaningless, the rate during motion is ~125Hz.
    """
    events = [
        MacroEvent(0.000, "move", "move", "", "", 1, 0),
        MacroEvent(0.008, "move", "move", "", "", 1, 0),
        MacroEvent(0.016, "move", "move", "", "", 1, 0),
        MacroEvent(10.016, "move", "move", "", "", 1, 0),
        MacroEvent(10.024, "move", "move", "", "", 1, 0),
    ]
    save_macro("bursty", events, macros_dir=macros_dir)

    cli.main(["inspect", "bursty"])

    out = capsys.readouterr().out
    assert "125 Hz" in out  # while moving, not 0.5Hz averaged over the pause


def test_inspect_does_not_warn_about_a_well_sampled_macro(macros_dir, capsys):
    """A fast flick produces a big step legitimately; that is not a fault."""
    events = [
        MacroEvent(0.000, "move", "move", "", "", 180, 0),
        MacroEvent(0.008, "move", "move", "", "", 150, 0),
        MacroEvent(0.016, "move", "move", "", "", 120, 0),
    ]
    save_macro("flick", events, macros_dir=macros_dir)

    cli.main(["inspect", "flick"])

    assert "NOTE" not in capsys.readouterr().out


def test_inspect_warns_when_samples_are_too_far_apart(macros_dir, capsys):
    """Coarse spacing IS the fault: deltas got merged."""
    events = [
        MacroEvent(0.00, "move", "move", "", "", 200, 0),
        MacroEvent(0.10, "move", "move", "", "", 200, 0),
        MacroEvent(0.20, "move", "move", "", "", 200, 0),
    ]
    save_macro("coarse", events, macros_dir=macros_dir)

    cli.main(["inspect", "coarse"])

    assert "NOTE" in capsys.readouterr().out


def test_inspect_missing_macro_exits_non_zero(macros_dir, capsys):
    exit_code = cli.main(["inspect", "nope"])

    assert exit_code != 0
    assert "nope" in capsys.readouterr().err


def test_doctor_reports_every_backend(macros_dir, capsys):
    exit_code = cli.main(["doctor"])

    out = capsys.readouterr().out
    assert exit_code == 0
    for backend in ("pynput", "pydirectinput", "pywin32", "tkinter"):
        assert backend in out


def test_doctor_checks_raw_mouse_input(macros_dir, monkeypatch, capsys):
    """Movement recording depends on this and nothing else reports it."""

    class WorkingRaw:
        def __init__(self, on_move):
            self.running = False

        def start(self, timeout=5.0):
            self.running = True

        def stop(self):
            self.running = False

    monkeypatch.setattr(cli, "RawMouseListener", WorkingRaw)

    cli.main(["doctor"])

    assert "raw mouse input" in capsys.readouterr().out.lower()


def test_doctor_fails_when_raw_input_cannot_register(macros_dir, monkeypatch, capsys):
    """This is the silent failure behind 'movement recorded nothing'."""

    class BrokenRaw:
        def __init__(self, on_move):
            self.running = False

        def start(self, timeout=5.0):
            self.running = False

        def stop(self):
            pass

    monkeypatch.setattr(cli, "RawMouseListener", BrokenRaw)

    exit_code = cli.main(["doctor"])

    out = capsys.readouterr().out
    assert exit_code != 0
    assert "MISSING" in out


def test_doctor_fails_when_a_backend_is_missing(macros_dir, monkeypatch, capsys):
    """This is the check that catches a broken packaged build."""

    def no_pynput():
        raise BackendUnavailableError("pynput is not installed")

    monkeypatch.setattr(cli, "load_pynput", no_pynput)

    exit_code = cli.main(["doctor"])

    assert exit_code != 0
    assert "MISSING" in capsys.readouterr().out


def test_unknown_command_exits_non_zero(macros_dir):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["frobnicate", "demo"])

    assert excinfo.value.code != 0
