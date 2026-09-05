"""Entry point for ``python -m macrologger`` and for the packaged .exe.

With no arguments it opens the control window, which is what double-clicking
the .exe does. With arguments it behaves like the CLI.

The packaged build is ``--windowed`` so double-clicking never flashes a
console. That also means the frozen app has **no stdout**: a plain ``print``
goes nowhere, and a CLI command run from a terminal appears to do nothing at
all. When there is no console, output is captured and shown in a window
instead.
"""

from __future__ import annotations

import contextlib
import io
import sys
from collections.abc import Callable
from typing import Any


def _console_window() -> int:  # pragma: no cover - Windows only
    import ctypes

    return int(ctypes.windll.kernel32.GetConsoleWindow())


def attach_parent_console() -> bool:  # pragma: no cover - needs a real console
    """Attach to the terminal that launched us, if there is one.

    A --windowed build starts with no console, so output run from cmd or
    PowerShell would otherwise be discarded. Attaching to the parent puts it
    back in the window the user typed into.
    """
    import ctypes

    ATTACH_PARENT_PROCESS = -1
    if not ctypes.windll.kernel32.AttachConsole(ATTACH_PARENT_PROCESS):
        return False
    try:
        sys.stdout = open("CONOUT$", "w", buffering=1, encoding="utf-8", errors="replace")
        sys.stderr = sys.stdout
    except OSError:
        return False
    return True


def has_console(stdout: Any, console_window: Callable[[], int] | None = None) -> bool:
    """Whether output has somewhere to go.

    A --windowed PyInstaller build sets stdout to None; the separate console
    build has a real one. ``console_window`` is accepted for callers that want
    to probe Win32 explicitly, but a present stdout is the deciding signal --
    probing GetConsoleWindow() wrongly discarded output from the console
    build when it was launched from a terminal emulator.
    """
    if stdout is None:
        return False
    if console_window is not None:
        try:
            return console_window() != 0
        except Exception:  # noqa: BLE001 - fall back to trusting stdout
            return True
    return True


def show_dialog(text: str) -> None:  # pragma: no cover - needs a display
    """Show captured CLI output in a scrollable window."""
    import tkinter as tk
    from tkinter import scrolledtext

    root = tk.Tk()
    root.title("Macro Logger")
    root.configure(bg="#0d1117")
    widget = scrolledtext.ScrolledText(
        root,
        width=74,
        height=20,
        bg="#0d1117",
        fg="#e6edf3",
        insertbackground="#e6edf3",
        font=("Consolas", 10),
        borderwidth=0,
        padx=14,
        pady=12,
    )
    widget.pack(fill="both", expand=True)
    widget.insert("1.0", text)
    widget.configure(state="disabled")
    root.mainloop()


def run_cli(
    runner: Callable[[], int],
    stdout: Any = None,
    show_dialog: Callable[[str], None] = show_dialog,
    console_window: Callable[[], int] | None = None,
) -> int:
    """Run ``runner``, surfacing its output even without a console."""
    if has_console(stdout, console_window):
        return runner()

    buffer = io.StringIO()
    code = 0
    try:
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            code = runner()
    except SystemExit as exc:  # argparse exits this way on bad arguments
        code = int(exc.code or 0)
    except Exception as exc:  # noqa: BLE001 - must not vanish in a windowed build
        code = 1
        buffer.write(f"\n{type(exc).__name__}: {exc}\n")

    text = buffer.getvalue().strip() or "Finished with no output."
    show_dialog(text)
    return code


def main() -> int:
    # Absolute imports on purpose: when PyInstaller runs this file as the
    # frozen entry script it has no parent package, so relative imports fail.
    from macrologger.cli import main as cli_main

    if len(sys.argv) == 1:
        from macrologger.ui import run_app

        run_app()
        return 0

    # A windowed frozen build has no stdout: try to borrow the terminal that
    # launched us, and fall back to a window if there is not one.
    if getattr(sys, "frozen", False) and sys.stdout is None:
        attach_parent_console()
    return run_cli(cli_main, stdout=sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
