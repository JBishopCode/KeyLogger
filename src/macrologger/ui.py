"""The control window: macro library, record/play, hotkey and options.

A thin ttk view over :class:`macrologger.controller.AppController`. All state
lives in the controller; this module only renders it and forwards clicks, so
the behaviour stays testable without a display.

Styling is deliberately restrained -- a dark palette, one accent colour,
generous padding and a single type family. That reads as modern far more than
widget count does, and it costs nothing at runtime.
"""

from __future__ import annotations

import logging
import queue
from pathlib import Path
from typing import Any

from .controller import AppController, AppState, PlaybackOptions
from .hotkey import DEFAULT_HOTKEY, HotkeyListener, InvalidHotkeyError
from .overlay import KeyOverlay, OverlayModel
from .storage import DEFAULT_MACROS_DIR

logger = logging.getLogger(__name__)

# One place to change the look.
DARK = {
    "bg": "#0d1117",
    "panel": "#161b22",
    "panel_alt": "#1c2330",
    "border": "#30363d",
    "text": "#e6edf3",
    "muted": "#8b949e",
    "accent": "#5ee6a8",
    "accent_dim": "#2ea373",
    "danger": "#ff7b72",
}

FONT = "Segoe UI"
MONO = "Consolas"

STATE_LABELS = {
    AppState.IDLE: ("Idle", DARK["muted"]),
    AppState.RECORDING: ("Recording", DARK["danger"]),
    AppState.PLAYING: ("Playing", DARK["accent"]),
}


class ControlWindow:
    """Main application window."""

    def __init__(
        self,
        controller: AppController | None = None,
        macros_dir: Path | str = DEFAULT_MACROS_DIR,
    ) -> None:
        self.controller = controller or AppController(macros_dir=macros_dir)
        self.hotkey_spec = DEFAULT_HOTKEY
        self._hotkey_listener: HotkeyListener | None = None
        self._overlay: KeyOverlay | None = None
        self.overlay_model = OverlayModel()
        # Worker threads post state changes here; the Tk loop drains it, since
        # widgets must only be touched from the main thread.
        self._events: queue.Queue[AppState] = queue.Queue()
        self._widgets: dict[str, Any] = {}
        self.root: Any = None

    # -- construction --------------------------------------------------

    def build(self) -> Any:
        import tkinter as tk
        from tkinter import ttk

        root = tk.Tk()
        root.title("Macro Logger")
        root.configure(bg=DARK["bg"])
        root.minsize(560, 520)
        self.root = root

        self._configure_style(ttk)

        container = ttk.Frame(root, style="App.TFrame", padding=20)
        container.pack(fill="both", expand=True)

        self._build_header(ttk, container)
        self._build_library(tk, ttk, container)
        self._build_record(tk, ttk, container)
        self._build_playback(tk, ttk, container)
        self._build_footer(ttk, container)

        self.controller.on_state_change = self._events.put
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(80, self._drain_events)
        self.refresh_library()
        return root

    def _configure_style(self, ttk: Any) -> None:
        style = ttk.Style()
        # "clam" is the only built-in theme that honours custom colours well.
        style.theme_use("clam")
        style.configure("App.TFrame", background=DARK["bg"])
        style.configure(
            "TLabel", background=DARK["bg"], foreground=DARK["text"], font=(FONT, 10)
        )
        style.configure(
            "Muted.TLabel",
            background=DARK["bg"],
            foreground=DARK["muted"],
            font=(FONT, 9),
        )
        style.configure(
            "Title.TLabel",
            background=DARK["bg"],
            foreground=DARK["text"],
            font=(FONT, 16, "bold"),
        )
        style.configure(
            "Status.TLabel",
            background=DARK["bg"],
            foreground=DARK["muted"],
            font=(FONT, 10, "bold"),
        )
        style.configure(
            "TButton",
            background=DARK["panel_alt"],
            foreground=DARK["text"],
            bordercolor=DARK["border"],
            focuscolor=DARK["bg"],
            padding=(14, 9),
            font=(FONT, 10),
        )
        style.map(
            "TButton",
            background=[("active", DARK["border"]), ("disabled", DARK["panel"])],
            foreground=[("disabled", DARK["muted"])],
        )
        style.configure(
            "Accent.TButton", background=DARK["accent_dim"], foreground="#04150d"
        )
        style.map("Accent.TButton", background=[("active", DARK["accent"])])
        style.configure(
            "TCheckbutton",
            background=DARK["bg"],
            foreground=DARK["text"],
            focuscolor=DARK["bg"],
            font=(FONT, 10),
        )
        style.map("TCheckbutton", background=[("active", DARK["bg"])])
        style.configure(
            "TEntry",
            fieldbackground=DARK["panel_alt"],
            foreground=DARK["text"],
            bordercolor=DARK["border"],
            insertcolor=DARK["text"],
            padding=8,
        )

    def _build_header(self, ttk: Any, parent: Any) -> None:
        header = ttk.Frame(parent, style="App.TFrame")
        header.pack(fill="x", pady=(0, 16))
        ttk.Label(header, text="Macro Logger", style="Title.TLabel").pack(side="left")
        status = ttk.Label(header, text="Idle", style="Status.TLabel")
        status.pack(side="right")
        self._widgets["status"] = status

    def _build_library(self, tk: Any, ttk: Any, parent: Any) -> None:
        ttk.Label(parent, text="MACROS", style="Muted.TLabel").pack(anchor="w")
        listbox = tk.Listbox(
            parent,
            height=8,
            bg=DARK["panel"],
            fg=DARK["text"],
            selectbackground=DARK["accent_dim"],
            selectforeground="#04150d",
            highlightthickness=1,
            highlightbackground=DARK["border"],
            highlightcolor=DARK["accent_dim"],
            borderwidth=0,
            font=(MONO, 10),
            activestyle="none",
        )
        listbox.pack(fill="both", expand=True, pady=(6, 14))
        self._widgets["listbox"] = listbox

    def _build_record(self, tk: Any, ttk: Any, parent: Any) -> None:
        row = ttk.Frame(parent, style="App.TFrame")
        row.pack(fill="x", pady=(0, 10))

        name_var = tk.StringVar()
        entry = ttk.Entry(row, textvariable=name_var, width=22)
        entry.pack(side="left", fill="x", expand=True)
        self._widgets["name_var"] = name_var

        record_button = ttk.Button(row, text="Record", command=self.on_record)
        record_button.pack(side="left", padx=(10, 0))
        self._widgets["record_button"] = record_button

        movement_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            parent,
            text="Record mouse movement  (needs 'Enhance pointer precision' OFF)",
            variable=movement_var,
        ).pack(anchor="w")
        self._widgets["movement_var"] = movement_var

    def _build_playback(self, tk: Any, ttk: Any, parent: Any) -> None:
        ttk.Label(parent, text="PLAYBACK", style="Muted.TLabel").pack(
            anchor="w", pady=(14, 6)
        )

        options = ttk.Frame(parent, style="App.TFrame")
        options.pack(fill="x")

        loop_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(options, text="Loop", variable=loop_var).pack(side="left")
        self._widgets["loop_var"] = loop_var

        jitter_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(options, text="Jitter", variable=jitter_var).pack(
            side="left", padx=(16, 0)
        )
        self._widgets["jitter_var"] = jitter_var

        overlay_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            options, text="Overlay", variable=overlay_var, command=self.on_overlay
        ).pack(side="left", padx=(16, 0))
        self._widgets["overlay_var"] = overlay_var

        hotkey_row = ttk.Frame(parent, style="App.TFrame")
        hotkey_row.pack(fill="x", pady=(12, 0))
        ttk.Label(hotkey_row, text="Hotkey").pack(side="left")
        hotkey_var = tk.StringVar(value=self.hotkey_spec)
        ttk.Entry(hotkey_row, textvariable=hotkey_var, width=14).pack(
            side="left", padx=(10, 0)
        )
        ttk.Button(hotkey_row, text="Bind", command=self.on_bind_hotkey).pack(
            side="left", padx=(8, 0)
        )
        self._widgets["hotkey_var"] = hotkey_var

        buttons = ttk.Frame(parent, style="App.TFrame")
        buttons.pack(fill="x", pady=(16, 0))
        play_button = ttk.Button(
            buttons, text="Play", style="Accent.TButton", command=self.on_play
        )
        play_button.pack(side="left")
        self._widgets["play_button"] = play_button
        stop_button = ttk.Button(buttons, text="Stop", command=self.on_stop)
        stop_button.pack(side="left", padx=(10, 0))
        self._widgets["stop_button"] = stop_button

    def _build_footer(self, ttk: Any, parent: Any) -> None:
        message = ttk.Label(parent, text="", style="Muted.TLabel", wraplength=520)
        message.pack(anchor="w", pady=(16, 0))
        self._widgets["message"] = message

    # -- helpers -------------------------------------------------------

    def selected_macro(self) -> str | None:
        listbox = self._widgets["listbox"]
        selection = listbox.curselection()
        if not selection:
            return None
        return listbox.get(selection[0]).split()[0]

    def set_message(self, text: str, error: bool = False) -> None:
        widget = self._widgets.get("message")
        if widget is not None:
            widget.configure(
                text=text, foreground=DARK["danger"] if error else DARK["muted"]
            )
        logger.info("ui: %s", text)

    def refresh_library(self) -> None:
        listbox = self._widgets.get("listbox")
        if listbox is None:
            return
        listbox.delete(0, "end")
        for summary in self.controller.list_macros():
            listbox.insert(
                "end",
                f"{summary.name:<18} {summary.event_count:>5} ev  "
                f"{summary.duration:>6.1f}s  {summary.window[:28]}",
            )

    def playback_options(self) -> PlaybackOptions:
        return PlaybackOptions(
            loop_forever=bool(self._widgets["loop_var"].get()),
            jitter=0.1 if self._widgets["jitter_var"].get() else 0.0,
        )

    # -- actions -------------------------------------------------------

    def on_record(self) -> None:
        if self.controller.state is AppState.RECORDING:
            self.controller.stop_recording()
            return
        name = self._widgets["name_var"].get().strip()
        if not name:
            self.set_message("Enter a name for the macro first.", error=True)
            return
        try:
            self.controller.start_recording(
                name, record_movement=bool(self._widgets["movement_var"].get())
            )
        except Exception as exc:  # noqa: BLE001 - shown in the window
            self.set_message(str(exc), error=True)
            return
        self.set_message(f"Recording '{name}'. Press ESC or Stop to finish.")

    def on_play(self) -> None:
        name = self.selected_macro()
        if name is None:
            self.set_message("Select a macro to play.", error=True)
            return
        try:
            self.controller.start_playback(name, self.playback_options())
        except Exception as exc:  # noqa: BLE001 - shown in the window
            self.set_message(str(exc), error=True)
            return
        self.set_message(f"Playing '{name}'. Alt-tab into the game.")

    def on_stop(self) -> None:
        if self.controller.state is AppState.RECORDING:
            self.controller.stop_recording()
        else:
            self.controller.stop_playback()

    def on_bind_hotkey(self) -> None:
        spec = self._widgets["hotkey_var"].get().strip()
        try:
            self._start_hotkey(spec)
        except InvalidHotkeyError as exc:
            self.set_message(str(exc), error=True)
            return
        self.hotkey_spec = spec
        self.set_message(f"Hotkey {spec} starts and stops playback.")

    def _start_hotkey(self, spec: str) -> None:
        if self._hotkey_listener is not None:
            self._hotkey_listener.__exit__()
            self._hotkey_listener = None
        listener = HotkeyListener(spec, self._on_hotkey)
        listener.__enter__()
        self._hotkey_listener = listener

    def _on_hotkey(self) -> None:
        name = self.selected_macro()
        if name is None:
            return
        try:
            self.controller.toggle_playback(name, self.playback_options())
        except Exception:  # noqa: BLE001 - hotkey thread must never die
            logger.exception("hotkey toggle failed")

    def on_overlay(self) -> None:
        if self._widgets["overlay_var"].get():
            self.set_message("Overlay will show while a macro plays.")
        else:
            self._close_overlay()

    def _close_overlay(self) -> None:
        if self._overlay is not None:
            self._overlay.close()
            self._overlay = None

    # -- event pump ----------------------------------------------------

    def _drain_events(self) -> None:
        """Apply controller state changes on the Tk thread."""
        try:
            while True:
                self._apply_state(self._events.get_nowait())
        except queue.Empty:
            pass
        if self.root is not None:
            self.root.after(80, self._drain_events)

    def _apply_state(self, state: AppState) -> None:
        label, colour = STATE_LABELS[state]
        self._widgets["status"].configure(text=label, foreground=colour)
        self._widgets["record_button"].configure(
            text="Stop" if state is AppState.RECORDING else "Record"
        )
        self._widgets["play_button"].configure(
            state="disabled" if state is not AppState.IDLE else "normal"
        )
        if state is AppState.IDLE:
            self.overlay_model.set_idle()
            self.refresh_library()
            if self.controller.last_error:
                self.set_message(self.controller.last_error, error=True)
                self.controller.last_error = None

    # -- lifecycle -----------------------------------------------------

    def close(self) -> None:
        self.controller.shutdown()
        if self._hotkey_listener is not None:
            self._hotkey_listener.__exit__()
            self._hotkey_listener = None
        self._close_overlay()
        if self.root is not None:
            self.root.destroy()
            self.root = None

    def run(self) -> None:
        root = self.build()
        root.mainloop()


def run_app(macros_dir: Path | str = DEFAULT_MACROS_DIR) -> None:
    """Open the control window."""
    ControlWindow(macros_dir=macros_dir).run()
