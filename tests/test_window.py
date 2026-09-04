"""Tests for active-window context tagging."""

from macrologger import window


def test_returns_title_from_win32(monkeypatch):
    monkeypatch.setattr(window, "_get_foreground_window", lambda: 1234)
    monkeypatch.setattr(window, "_get_window_text", lambda hwnd: "Minecraft 1.21")

    assert window.get_active_window_title() == "Minecraft 1.21"


def test_returns_empty_string_when_no_foreground_window(monkeypatch):
    monkeypatch.setattr(window, "_get_foreground_window", lambda: 0)

    assert window.get_active_window_title() == ""


def test_swallows_win32_errors(monkeypatch):
    def boom():
        raise OSError("win32 exploded")

    monkeypatch.setattr(window, "_get_foreground_window", boom)

    assert window.get_active_window_title() == ""


def test_swallows_window_text_errors(monkeypatch):
    def boom(hwnd):
        raise OSError("win32 exploded")

    monkeypatch.setattr(window, "_get_foreground_window", lambda: 1234)
    monkeypatch.setattr(window, "_get_window_text", boom)

    assert window.get_active_window_title() == ""


def test_returns_empty_string_when_win32_unavailable(monkeypatch):
    monkeypatch.setattr(window, "_get_foreground_window", None)

    assert window.get_active_window_title() == ""
