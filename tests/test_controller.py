"""Tests for the control-window logic, independent of any GUI toolkit.

Recorder and player are injected fakes, so no hooks are installed and no
input is sent.
"""

import threading

import pytest

from macrologger.controller import AppController, AppState, PlaybackOptions
from macrologger.events import MacroEvent
from macrologger.storage import load_macro, save_macro


def sample_events():
    return [
        MacroEvent(0.0, "key", "down", "w", "Minecraft 1.21"),
        MacroEvent(0.4, "key", "up", "w", "Minecraft 1.21"),
    ]


class FakeRecorder:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.stopped = False
        self.released = threading.Event()

    def record(self):
        self.released.wait(timeout=2)
        return sample_events()

    def request_stop(self):
        self.stopped = True
        self.released.set()


class FakePlayer:
    last = None

    def __init__(self, stop_event=None, **kwargs):
        self.stop_event = stop_event
        self.play_kwargs = None
        FakePlayer.last = self

    def play(self, events, **kwargs):
        self.play_kwargs = kwargs


@pytest.fixture
def controller(tmp_path):
    return AppController(
        macros_dir=tmp_path,
        recorder_factory=lambda **kw: FakeRecorder(**kw),
        player_factory=lambda **kw: FakePlayer(**kw),
    )


def test_starts_idle(controller):
    assert controller.state is AppState.IDLE


def test_lists_saved_macros(controller, tmp_path):
    save_macro("alpha", sample_events(), macros_dir=tmp_path)
    save_macro("beta", sample_events(), macros_dir=tmp_path)

    assert [summary.name for summary in controller.list_macros()] == ["alpha", "beta"]


def test_recording_moves_to_the_recording_state(controller):
    controller.start_recording("demo", record_movement=False)

    assert controller.state is AppState.RECORDING

    controller.stop_recording()
    controller.wait_idle()


def test_stopping_a_recording_saves_it_and_returns_to_idle(controller, tmp_path):
    controller.start_recording("demo", record_movement=False)

    controller.stop_recording()
    controller.wait_idle()

    assert load_macro("demo", macros_dir=tmp_path) == sample_events()
    assert controller.state is AppState.IDLE


def test_movement_flag_reaches_the_recorder(controller):
    controller.start_recording("demo", record_movement=True)

    assert controller.recorder.kwargs["record_movement"] is True

    controller.stop_recording()
    controller.wait_idle()


def test_cannot_record_two_macros_at_once(controller):
    controller.start_recording("demo", record_movement=False)

    with pytest.raises(RuntimeError):
        controller.start_recording("other", record_movement=False)

    controller.stop_recording()
    controller.wait_idle()


def test_recording_rejects_an_invalid_name(controller):
    with pytest.raises(Exception):
        controller.start_recording("../escape", record_movement=False)

    assert controller.state is AppState.IDLE


def test_playing_moves_back_to_idle_when_done(controller, tmp_path):
    save_macro("demo", sample_events(), macros_dir=tmp_path)

    controller.start_playback("demo", PlaybackOptions())
    controller.wait_idle()

    assert controller.state is AppState.IDLE


def test_playback_options_reach_the_player(controller, tmp_path):
    save_macro("demo", sample_events(), macros_dir=tmp_path)

    controller.start_playback(
        "demo", PlaybackOptions(loop=3, loop_delay=1.5, jitter=0.2)
    )
    controller.wait_idle()

    assert FakePlayer.last.play_kwargs == {
        "loop": 3,
        "loop_delay": 1.5,
        "jitter": 0.2,
    }


def test_looping_forever_is_expressed_as_none(controller, tmp_path):
    save_macro("demo", sample_events(), macros_dir=tmp_path)

    controller.start_playback("demo", PlaybackOptions(loop_forever=True))
    controller.wait_idle()

    assert FakePlayer.last.play_kwargs["loop"] is None


def test_cannot_play_while_recording(controller, tmp_path):
    save_macro("demo", sample_events(), macros_dir=tmp_path)
    controller.start_recording("other", record_movement=False)

    with pytest.raises(RuntimeError):
        controller.start_playback("demo", PlaybackOptions())

    controller.stop_recording()
    controller.wait_idle()


def test_playing_a_missing_macro_reports_an_error(controller):
    with pytest.raises(Exception):
        controller.start_playback("nope", PlaybackOptions())

    assert controller.state is AppState.IDLE


def test_state_changes_are_announced(controller, tmp_path):
    seen = []
    controller.on_state_change = seen.append
    save_macro("demo", sample_events(), macros_dir=tmp_path)

    controller.start_playback("demo", PlaybackOptions())
    controller.wait_idle()

    assert AppState.PLAYING in seen
    assert seen[-1] is AppState.IDLE


def test_toggle_starts_then_stops_playback(controller, tmp_path):
    save_macro("demo", sample_events(), macros_dir=tmp_path)
    controller.start_playback("demo", PlaybackOptions(loop_forever=True))

    controller.toggle_playback("demo", PlaybackOptions(loop_forever=True))
    controller.wait_idle()

    assert controller.state is AppState.IDLE


def test_shutdown_stops_everything(controller, tmp_path):
    save_macro("demo", sample_events(), macros_dir=tmp_path)
    controller.start_playback("demo", PlaybackOptions(loop_forever=True))

    controller.shutdown()

    assert controller.state is AppState.IDLE
