"""Thread-safety tests for hotkey-driven playback.

Uses real threads with a blocking fake player, so a stop that does not wait
for the worker shows up as two concurrent players instead of passing by luck.
"""

import threading

from macrologger import cli
from macrologger.events import MacroEvent


class BlockingPlayer:
    """Fake player that stays 'playing' until the stop event is set.

    Records the peak number of concurrent play() calls, which is the thing
    that must never exceed 1.
    """

    instances = []

    def __init__(self, stop_event=None, **kwargs):
        self.stop_event = stop_event
        self.active = 0
        self.peak_concurrent = 0
        self._lock = threading.Lock()
        self.plays = 0
        BlockingPlayer.instances.append(self)

    def play(self, events, **kwargs):
        with self._lock:
            self.active += 1
            self.plays += 1
            self.peak_concurrent = max(self.peak_concurrent, self.active)
        try:
            # Mimic the real player: only notice the stop between slices.
            while not self.stop_event.is_set():
                threading.Event().wait(0.005)
        finally:
            with self._lock:
                self.active -= 1


class FakeHotkeyListener:
    """Drives a scripted sequence of hotkey presses, then returns."""

    presses = 2

    def __init__(self, spec, on_press):
        self.on_press = on_press

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def join(self):
        for _ in range(FakeHotkeyListener.presses):
            self.on_press()


def events():
    return [MacroEvent(0.0, "key", "down", "w", "")]


def run_presses(monkeypatch, count):
    BlockingPlayer.instances = []
    FakeHotkeyListener.presses = count
    monkeypatch.setattr(cli, "Player", BlockingPlayer)
    monkeypatch.setattr(cli, "HotkeyListener", FakeHotkeyListener)

    cli._play_with_hotkey(events(), "demo", "f8", None, 0.0, 0.0)

    return BlockingPlayer.instances[0]


def test_start_then_stop_leaves_no_worker_running(monkeypatch):
    player = run_presses(monkeypatch, 2)

    assert player.plays == 1
    assert player.active == 0


def test_rapid_start_stop_start_never_runs_two_players_at_once(monkeypatch):
    """The bug: stop() that only flags the event lets the next start overlap."""
    player = run_presses(monkeypatch, 5)

    assert player.peak_concurrent == 1


def test_every_started_worker_is_finished_before_returning(monkeypatch):
    player = run_presses(monkeypatch, 6)

    assert player.active == 0
    for thread in threading.enumerate():
        assert thread.name != "macro-playback"
