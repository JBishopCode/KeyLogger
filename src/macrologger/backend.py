"""Lazy loading of the Windows input backends.

``pynput`` (capture) and ``pydirectinput`` (replay) are imported late so the
pure logic stays importable anywhere, and so a missing dependency surfaces as
an actionable message at the CLI boundary instead of a raw
``ModuleNotFoundError`` traceback -- the usual cause being the system Python
running instead of the project virtualenv.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

logger = logging.getLogger(__name__)

_INSTALL_HINT = (
    "activate the project venv (.venv\\Scripts\\activate) "
    "or run: pip install -r requirements.txt"
)


class BackendUnavailableError(Exception):
    """Raised when an input backend cannot be imported."""


def _missing(package: str) -> BackendUnavailableError:
    return BackendUnavailableError(
        f"{package} is not installed for this Python ({sys.executable}); {_INSTALL_HINT}"
    )


def load_pynput() -> Any:
    """Return the ``pynput`` package, or raise with an actionable message."""
    try:
        import pynput

        return pynput
    except ImportError as exc:
        raise _missing("pynput") from exc


#: One wheel notch, in the units SendInput expects (winuser.h).
WHEEL_DELTA = 120

MOUSEEVENTF_WHEEL = 0x0800


def wheel_delta_for(clicks: int) -> int:
    """Convert wheel clicks (as pynput reports them) into Win32 units."""
    return int(clicks) * WHEEL_DELTA


def send_wheel(clicks: int) -> None:
    """Send a mouse-wheel scroll.

    pydirectinput has no scroll function at all, so this goes straight to
    SendInput. Minecraft reads the wheel for hotbar selection, so without it
    a recorded hotbar change replays as nothing.
    """
    import ctypes
    from ctypes import wintypes

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
        ]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("union", _INPUTUNION)]

    INPUT_MOUSE = 0
    event = INPUT(
        type=INPUT_MOUSE,
        union=_INPUTUNION(
            mi=MOUSEINPUT(
                dx=0,
                dy=0,
                # DWORD is unsigned, so a negative (scroll down) delta has to
                # be passed as its two's-complement value.
                mouseData=ctypes.c_uint32(wheel_delta_for(clicks)).value,
                dwFlags=MOUSEEVENTF_WHEEL,
                time=0,
                dwExtraInfo=None,
            )
        ),
    )
    sent = ctypes.windll.user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT))
    if sent != 1:
        logger.warning("SendInput did not deliver the wheel event")


def load_pydirectinput() -> Any:
    """Return ``pydirectinput``, configured for faithful replay timing."""
    try:
        import pydirectinput
    except ImportError as exc:
        raise _missing("pydirectinput") from exc

    # Minecraft needs every event at the recorded time; the library's built-in
    # pause and corner failsafe would distort the gaps, so both are disabled.
    pydirectinput.PAUSE = 0
    pydirectinput.FAILSAFE = False
    return pydirectinput
