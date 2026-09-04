"""Always-on-top keypress overlay drawn over Minecraft.

Two pieces, deliberately separated so the logic stays testable without a
display:

* :class:`OverlayModel` -- pure state (held keys, status line, dirty flag).
* :class:`KeyOverlay` -- a borderless Tk window whose Win32 extended styles are
  rewritten so it is click-through, never activates, and never appears in the
  taskbar or alt-tab.

``WS_EX_NOACTIVATE`` is the load-bearing flag: without it the overlay takes
focus from Minecraft the moment it appears, which breaks the macro.

The window repaints only when the model changes, so an idle overlay costs
effectively no CPU and no GPU.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any

logger = logging.getLogger(__name__)

# Win32 extended window styles (winuser.h).
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000

GWL_EXSTYLE = -20

#: How often the Tk loop checks for state changes. Repaints happen only if the
#: model actually changed, so this tick is cheap.
REFRESH_MS = 50

DEFAULT_MAX_CODES = 6


def overlay_styles(click_through: bool = True) -> int:
    """Extended styles for a non-activating, topmost overlay window.

    Deliberately does NOT include ``WS_EX_LAYERED``: Tk's ``-alpha`` sets that
    bit *and* the matching layered attributes together. Setting the bit alone
    leaves the window unpainted -- known to Windows, invisible on screen.
    """
    styles = WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST
    if click_through:
        styles |= WS_EX_TRANSPARENT
    return styles


def resolve_toplevel_hwnd(root: Any, user32: Any = None) -> int:
    """Return the real top-level HWND for a Tk window.

    ``winfo_id()`` gives Tk's *child* window on Windows; extended styles set
    there do not govern how the window is shown, so the parent is used when
    one exists.
    """
    child = root.winfo_id()
    api = user32
    if api is None:
        try:
            import ctypes

            api = ctypes.windll.user32
        except (ImportError, AttributeError):  # pragma: no cover - non-Windows
            return child
    try:
        parent = api.GetParent(child)
    except Exception:  # noqa: BLE001 - fall back to the child window
        logger.debug("GetParent failed; using child hwnd", exc_info=True)
        return child
    return parent or child


def _load_win32() -> Any | None:
    try:
        import win32gui

        return win32gui
    except ImportError:  # pragma: no cover - non-Windows or pywin32 missing
        logger.debug("pywin32 unavailable; overlay will not be click-through")
        return None


_WIN32 = _load_win32()

#: Distinguishes "caller said nothing" from "caller said there is no backend".
_USE_DEFAULT = object()


def apply_overlay_styles(
    hwnd: int, win32: Any = _USE_DEFAULT, click_through: bool = True
) -> bool:
    """Make the window at ``hwnd`` non-activating (and optionally click-through).

    Existing bits are preserved, so the ``WS_EX_LAYERED`` flag Tk set for
    ``-alpha`` survives. Returns True if the styles were applied; a missing
    pywin32 is not fatal, the overlay just won't be click-through.
    """
    backend = _WIN32 if win32 is _USE_DEFAULT else win32
    if backend is None:
        return False
    try:
        existing = backend.GetWindowLong(hwnd, GWL_EXSTYLE)
        backend.SetWindowLong(
            hwnd, GWL_EXSTYLE, existing | overlay_styles(click_through)
        )
        return True
    except Exception:  # noqa: BLE001 - overlay styling must never crash playback
        logger.warning("could not apply overlay window styles", exc_info=True)
        return False


class OverlayModel:
    """What the overlay is currently showing.

    Kept free of Tk so it can be driven from the playback thread and tested
    headlessly; the window polls it and repaints only when it changed.
    """

    def __init__(self, max_codes: int = DEFAULT_MAX_CODES) -> None:
        self._codes: deque[str] = deque(maxlen=max_codes)
        self.status = "idle"
        self._dirty = True

    def active_codes(self) -> list[str]:
        return list(self._codes)

    def consume_dirty(self) -> bool:
        """Return whether a repaint is due, clearing the flag."""
        was_dirty = self._dirty
        self._dirty = False
        return was_dirty

    def press(self, code: str) -> None:
        if code in self._codes:
            return
        self._codes.append(code)
        self._dirty = True

    def release(self, code: str) -> None:
        try:
            self._codes.remove(code)
        except ValueError:
            return
        self._dirty = True

    def set_playing(self, macro: str, iteration: int, total: int | None) -> None:
        counter = f"{iteration}" if total is None else f"{iteration}/{total}"
        suffix = " (looping)" if total is None else ""
        self._set_status(f"playing {macro} - {counter}{suffix}")

    def set_recording(self, macro: str) -> None:
        self._set_status(f"REC {macro}")

    def set_idle(self) -> None:
        # Clear held keys too: leaving them lit would misreport the game state.
        if self._codes:
            self._codes.clear()
            self._dirty = True
        self._set_status("idle")

    def _set_status(self, status: str) -> None:
        if status != self.status:
            self.status = status
            self._dirty = True


class KeyOverlay:
    """Borderless click-through Tk window showing the model's state."""

    PANEL = "#111820"
    TEXT = "#e6edf3"
    ACCENT = "#5ee6a8"

    def __init__(
        self,
        model: OverlayModel,
        position: tuple[int, int] = (24, 24),
        alpha: float = 0.85,
        click_through: bool = True,
    ) -> None:
        self.model = model
        self.position = position
        self.alpha = alpha
        self.click_through = click_through
        self.hwnd: int | None = None
        self._root: Any = None
        self._status_label: Any = None
        self._keys_label: Any = None

    def _build(self) -> Any:
        import tkinter as tk

        root = tk.Tk()
        root.overrideredirect(True)  # no title bar or borders
        root.attributes("-topmost", True)
        root.attributes("-alpha", self.alpha)
        root.configure(bg=self.PANEL)
        root.geometry("+{}+{}".format(*self.position))

        frame = tk.Frame(root, bg=self.PANEL, padx=14, pady=10)
        frame.pack()
        self._status_label = tk.Label(
            frame,
            text=self.model.status,
            bg=self.PANEL,
            fg=self.ACCENT,
            font=("Segoe UI", 10, "bold"),
            anchor="w",
        )
        self._status_label.pack(anchor="w")
        self._keys_label = tk.Label(
            frame,
            text="",
            bg=self.PANEL,
            fg=self.TEXT,
            font=("Consolas", 16, "bold"),
            anchor="w",
        )
        self._keys_label.pack(anchor="w")

        # Map and lay the window out before touching Win32: the HWND is not
        # meaningful until Tk has actually created and shown the window.
        root.update_idletasks()
        root.deiconify()
        root.lift()
        root.update()

        self.hwnd = resolve_toplevel_hwnd(root)
        applied = apply_overlay_styles(self.hwnd, click_through=self.click_through)
        logger.info(
            "overlay hwnd=%s size=%sx%s at %s styles_applied=%s click_through=%s",
            self.hwnd,
            root.winfo_width(),
            root.winfo_height(),
            self.position,
            applied,
            self.click_through,
        )
        self._root = root
        return root

    def _repaint(self) -> None:
        codes = self.model.active_codes()
        self._status_label.configure(text=self.model.status)
        self._keys_label.configure(
            text="  ".join(code.upper() for code in codes) if codes else "-"
        )

    def _tick(self) -> None:
        if self.model.consume_dirty():
            self._repaint()
        self._root.after(REFRESH_MS, self._tick)

    def run(self) -> None:
        """Show the overlay and block until the window is closed."""
        root = self._build()
        self._repaint()
        root.after(REFRESH_MS, self._tick)
        logger.info("overlay started")
        root.mainloop()

    def close(self) -> None:
        if self._root is not None:
            self._root.destroy()
            self._root = None
