"""Active-window context lookup (Win32).

Used to tag each recorded event with the focused window's title, so macro logs
are readable ("was Minecraft actually focused when this was recorded?").
Failure is never fatal: the title falls back to an empty string.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:  # pragma: no cover - import shape depends on the host OS
    import win32gui

    _get_foreground_window = win32gui.GetForegroundWindow
    _get_window_text = win32gui.GetWindowText
except ImportError:  # pragma: no cover - non-Windows or pywin32 missing
    logger.debug("pywin32 unavailable; active window titles will be empty")
    _get_foreground_window = None
    _get_window_text = None


def get_active_window_title() -> str:
    """Return the focused window's title, or ``""`` if it cannot be read."""
    if _get_foreground_window is None or _get_window_text is None:
        return ""
    try:
        hwnd = _get_foreground_window()
        if not hwnd:
            return ""
        return _get_window_text(hwnd) or ""
    except Exception:  # noqa: BLE001 - context tagging must never break recording
        logger.debug("failed to read active window title", exc_info=True)
        return ""
