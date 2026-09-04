"""True mouse deltas via the Win32 Raw Input API.

``pynput``'s ``on_move`` reports the *cursor position*. Minecraft traps the
cursor and recentres it every frame, so cursor-position deltas describe the
recentring, not the player's actual hand movement -- recording them produces a
macro that appears stuck at the screen centre.

Raw Input (``WM_INPUT``) reports what the device itself sent, before the
cursor is clamped or recentred, which is the only correct source for movement
inside a mouse-look game.

Implementation is a message-only window running its own pump on a background
thread, registered with ``RIDEV_INPUTSINK`` so packets arrive even while
Minecraft holds focus.
"""

from __future__ import annotations

import ctypes
import logging
import threading
from collections.abc import Callable
from ctypes import wintypes
from typing import Any

logger = logging.getLogger(__name__)

# Raw Input constants (winuser.h).
RIM_TYPEMOUSE = 0
RIDEV_INPUTSINK = 0x00000100
RID_INPUT = 0x10000003
WM_INPUT = 0x00FF
WM_CLOSE = 0x0010
HID_USAGE_PAGE_GENERIC = 0x01
HID_USAGE_GENERIC_MOUSE = 0x02

MOUSE_MOVE_RELATIVE = 0x00
MOUSE_MOVE_ABSOLUTE = 0x01


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [
        ("usUsagePage", wintypes.USHORT),
        ("usUsage", wintypes.USHORT),
        ("dwFlags", wintypes.DWORD),
        ("hwndTarget", wintypes.HWND),
    ]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [
        ("dwType", wintypes.DWORD),
        ("dwSize", wintypes.DWORD),
        ("hDevice", wintypes.HANDLE),
        ("wParam", wintypes.WPARAM),
    ]


class _RAWMOUSE_BUTTONS(ctypes.Structure):
    _fields_ = [
        ("usButtonFlags", wintypes.USHORT),
        ("usButtonData", wintypes.USHORT),
    ]


class _RAWMOUSE_UNION(ctypes.Union):
    _fields_ = [
        ("ulButtons", wintypes.ULONG),
        ("buttons", _RAWMOUSE_BUTTONS),
    ]


class RAWMOUSE(ctypes.Structure):
    _fields_ = [
        ("usFlags", wintypes.USHORT),
        ("union", _RAWMOUSE_UNION),
        ("ulRawButtons", wintypes.ULONG),
        ("lLastX", wintypes.LONG),
        ("lLastY", wintypes.LONG),
        ("ulExtraInformation", wintypes.ULONG),
    ]


class _RAWINPUT_DATA(ctypes.Union):
    _fields_ = [("mouse", RAWMOUSE)]


class RAWINPUT(ctypes.Structure):
    _fields_ = [
        ("header", RAWINPUTHEADER),
        ("data", _RAWINPUT_DATA),
    ]


def parse_raw_mouse(raw: Any) -> tuple[int, int] | None:
    """Extract a relative ``(dx, dy)`` from a RAWINPUT packet.

    Returns None for packets that are not relative mouse motion: keyboard/HID
    packets, and absolute-coordinate devices (tablets, RDP, some VMs) whose
    values are screen positions rather than deltas.
    """
    if raw.header.dwType != RIM_TYPEMOUSE:
        return None
    mouse = raw.data.mouse
    if mouse.usFlags & MOUSE_MOVE_ABSOLUTE:
        logger.debug("ignoring absolute raw mouse packet")
        return None
    return int(mouse.lLastX), int(mouse.lLastY)


def raw_input_available() -> bool:
    """Whether the Win32 Raw Input API can be used on this machine."""
    try:
        return hasattr(ctypes, "windll") and hasattr(
            ctypes.windll.user32, "RegisterRawInputDevices"
        )
    except (AttributeError, OSError):  # pragma: no cover - non-Windows
        return False


class RawMouseListener:
    """Delivers true mouse deltas to ``on_move`` until stopped."""

    WINDOW_CLASS = "MacroLoggerRawInput"

    def __init__(self, on_move: Callable[[int, int], None]) -> None:
        self._on_move = on_move
        self._thread: threading.Thread | None = None
        self._hwnd: int | None = None
        self._ready = threading.Event()
        self.running = False

    def _handle_raw(self, raw: Any) -> None:
        """Decode one packet and forward it; never raises."""
        decoded = parse_raw_mouse(raw)
        if decoded is None:
            return
        dx, dy = decoded
        if not (dx or dy):
            return
        try:
            self._on_move(dx, dy)
        except Exception:  # noqa: BLE001 - a bad callback must not kill the pump
            logger.exception("raw mouse callback failed")

    def _read_packet(self, lparam: int) -> None:  # pragma: no cover - needs Win32
        user32 = ctypes.windll.user32
        size = wintypes.UINT(0)
        header_size = ctypes.sizeof(RAWINPUTHEADER)
        user32.GetRawInputData(
            wintypes.HANDLE(lparam),
            RID_INPUT,
            None,
            ctypes.byref(size),
            header_size,
        )
        buffer = ctypes.create_string_buffer(size.value)
        copied = user32.GetRawInputData(
            wintypes.HANDLE(lparam),
            RID_INPUT,
            buffer,
            ctypes.byref(size),
            header_size,
        )
        if copied != size.value:
            logger.debug("short raw input read (%s of %s)", copied, size.value)
            return
        self._handle_raw(ctypes.cast(buffer, ctypes.POINTER(RAWINPUT)).contents)

    def _run(self) -> None:  # pragma: no cover - needs a real message pump
        import win32api
        import win32gui

        def wnd_proc(hwnd, msg, wparam, lparam):
            if msg == WM_INPUT:
                try:
                    self._read_packet(lparam)
                except Exception:  # noqa: BLE001
                    logger.exception("failed to read raw input packet")
                return 0
            return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

        window_class = win32gui.WNDCLASS()
        window_class.lpszClassName = self.WINDOW_CLASS
        window_class.lpfnWndProc = wnd_proc
        window_class.hInstance = win32api.GetModuleHandle(None)
        try:
            atom = win32gui.RegisterClass(window_class)
        except Exception:  # noqa: BLE001 - already registered by a prior run
            atom = self.WINDOW_CLASS

        self._hwnd = win32gui.CreateWindow(
            atom, self.WINDOW_CLASS, 0, 0, 0, 0, 0, 0, 0, window_class.hInstance, None
        )

        device = RAWINPUTDEVICE(
            usUsagePage=HID_USAGE_PAGE_GENERIC,
            usUsage=HID_USAGE_GENERIC_MOUSE,
            # INPUTSINK: keep receiving while Minecraft holds focus.
            dwFlags=RIDEV_INPUTSINK,
            hwndTarget=self._hwnd,
        )
        if not ctypes.windll.user32.RegisterRawInputDevices(
            ctypes.byref(device), 1, ctypes.sizeof(RAWINPUTDEVICE)
        ):
            logger.error("RegisterRawInputDevices failed; movement will not record")
            self._ready.set()
            return

        self.running = True
        self._ready.set()
        logger.info("raw mouse input registered (hwnd=%s)", self._hwnd)
        win32gui.PumpMessages()
        self.running = False

    def start(self, timeout: float = 5.0) -> None:
        """Start the pump thread and wait until registration has been attempted."""
        self._thread = threading.Thread(
            target=self._run, name="raw-mouse-input", daemon=True
        )
        self._thread.start()
        self._ready.wait(timeout)

    def stop(self) -> None:
        if self._hwnd:
            try:
                import win32gui

                win32gui.PostMessage(self._hwnd, WM_CLOSE, 0, 0)
            except Exception:  # noqa: BLE001
                logger.debug("could not close raw input window", exc_info=True)
        self.running = False
