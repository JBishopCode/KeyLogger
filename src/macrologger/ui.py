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
from .overlay import KeyOverlay, OverlayModel, apply_event_to_model
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
    AppState.IDLE: ("IDLE", DARK["muted"]),
    AppState.RECORDING: ("REC", DARK["danger"]),
    AppState.PLAYING: ("PLAYING", DARK["accent"]),
}

DEFAULT_RECORD_HOTKEY = "f9"
DEFAULT_PLAY_HOTKEY = DEFAULT_HOTKEY


def format_macro_row(summary: Any) -> str:
    """One line of the macro list. The name comes first so it can be parsed back."""
    return (
        f"{summary.name:<18} {summary.event_count:>5} ev  "
        f"{summary.duration:>6.1f}s  {summary.window[:26]}"
    )


def macro_name_from_row(row: str) -> str:
    return row.split()[0]


def index_of_macro(summaries: list[Any], name: str | None) -> int | None:
    """Position of ``name`` in the list, or None if it is absent."""
    if name is None:
        return None
    for index, summary in enumerate(summaries):
        if summary.name == name:
            return index
    return None


class ControlWindow:
    """Main application window."""

    def __init__(
        self,
        controller: AppController | None = None,
        macros_dir: Path | str = DEFAULT_MACROS_DIR,
    ) -> None:
        self.controller = controller or AppController(macros_dir=macros_dir)
        self.play_hotkey = DEFAULT_PLAY_HOTKEY
        self.record_hotkey = DEFAULT_RECORD_HOTKEY
        self._listeners: dict[str, HotkeyListener] = {}
        self._last_selected: str | None = None
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
        self.controller.on_playback_event = self._on_playback_event
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
            font=(FONT, 15, "bold"),
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
        style.configure(
            "TScale",
            background=DARK["bg"],
            troughcolor=DARK["panel_alt"],
            bordercolor=DARK["border"],
            lightcolor=DARK["accent_dim"],
            darkcolor=DARK["accent_dim"],
        )

    def _build_header(self, ttk: Any, parent: Any) -> None:
        import tkinter as tk

        header = ttk.Frame(parent, style="App.TFrame")
        header.pack(fill="x")

        title_row = ttk.Frame(header, style="App.TFrame")
        title_row.pack(fill="x")
        ttk.Label(title_row, text="MACRO LOGGER", style="Title.TLabel").pack(
            side="left"
        )
        status = ttk.Label(title_row, text="IDLE", style="Status.TLabel")
        status.pack(side="right")
        self._widgets["status"] = status

        # A thin accent rule under the title: cheap, and it makes the window
        # read as designed rather than default.
        rule = tk.Frame(header, height=2, bg=DARK["accent_dim"])
        rule.pack(fill="x", pady=(8, 0))

        ttk.Label(
            header,
            text="Record and replay keyboard, clicks and mouse look",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(8, 16))

    def _build_library(self, tk: Any, ttk: Any, parent: Any) -> None:
        label_row = ttk.Frame(parent, style="App.TFrame")
        label_row.pack(fill="x")
        ttk.Label(label_row, text="MACROS", style="Muted.TLabel").pack(side="left")
        count = ttk.Label(label_row, text="", style="Muted.TLabel")
        count.pack(side="right")
        self._widgets["count"] = count
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
        ttk.Checkbutton(
            options,
            text="Jitter",
            variable=jitter_var,
            command=self._update_jitter_label,
        ).pack(side="left", padx=(16, 0))
        self._widgets["jitter_var"] = jitter_var

        jitter_amount = tk.IntVar(value=10)
        scale = ttk.Scale(
            options,
            from_=2,
            to=40,
            variable=jitter_amount,
            command=lambda _: self._update_jitter_label(),
            length=110,
        )
        scale.pack(side="left", padx=(10, 6))
        self._widgets["jitter_amount"] = jitter_amount
        jitter_label = ttk.Label(options, text="+/-5%", style="Muted.TLabel")
        jitter_label.pack(side="left")
        self._widgets["jitter_label"] = jitter_label

        overlay_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            options, text="Overlay", variable=overlay_var, command=self.on_overlay
        ).pack(side="left", padx=(16, 0))
        self._widgets["overlay_var"] = overlay_var

        hotkeys = ttk.Frame(parent, style="App.TFrame")
        hotkeys.pack(fill="x", pady=(14, 0))

        play_var = tk.StringVar(value=self.play_hotkey)
        ttk.Label(hotkeys, text="Play hotkey").grid(row=0, column=0, sticky="w")
        ttk.Entry(hotkeys, textvariable=play_var, width=12).grid(
            row=0, column=1, padx=(10, 6)
        )
        ttk.Button(
            hotkeys, text="Bind", width=6, command=lambda: self.on_bind("play")
        ).grid(row=0, column=2)
        self._widgets["play_hotkey_var"] = play_var

        record_var = tk.StringVar(value=self.record_hotkey)
        ttk.Label(hotkeys, text="Record hotkey").grid(
            row=1, column=0, sticky="w", pady=(8, 0)
        )
        ttk.Entry(hotkeys, textvariable=record_var, width=12).grid(
            row=1, column=1, padx=(10, 6), pady=(8, 0)
        )
        ttk.Button(
            hotkeys, text="Bind", width=6, command=lambda: self.on_bind("record")
        ).grid(row=1, column=2, pady=(8, 0))
        self._widgets["record_hotkey_var"] = record_var

        ttk.Label(
            parent,
            text=(
                "Tip: bind the record hotkey, then start recording from inside "
                "the game so alt-tabbing is not captured."
            ),
            style="Muted.TLabel",
            wraplength=520,
        ).pack(anchor="w", pady=(10, 0))

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
        listbox = self._widgets.get("listbox")
        if listbox is None:
            return None
        selection = listbox.curselection()
        if not selection:
            # Fall back to the remembered name so a hotkey still works after a
            # refresh, even if the widget lost its highlight.
            return self._last_selected
        name = macro_name_from_row(listbox.get(selection[0]))
        self._last_selected = name
        return name

    def set_message(self, text: str, error: bool = False) -> None:
        widget = self._widgets.get("message")
        if widget is not None:
            widget.configure(
                text=text, foreground=DARK["danger"] if error else DARK["muted"]
            )
        logger.info("ui: %s", text)

    def refresh_library(self) -> None:
        """Redraw the list, keeping whatever was selected still selected.

        Losing the selection after every playback would mean re-picking the
        macro before the hotkey could fire again.
        """
        listbox = self._widgets.get("listbox")
        if listbox is None:
            return
        previous = self.selected_macro() or self._last_selected
        summaries = self.controller.list_macros()

        listbox.delete(0, "end")
        for summary in summaries:
            listbox.insert("end", format_macro_row(summary))

        index = index_of_macro(summaries, previous)
        if index is not None:
            listbox.selection_clear(0, "end")
            listbox.selection_set(index)
            listbox.activate(index)
            self._last_selected = previous

        count = len(summaries)
        counter = self._widgets.get("count")
        if counter is not None:
            counter.configure(text=f"{count} macro{'' if count == 1 else 's'}")

    def playback_options(self) -> PlaybackOptions:
        jitter = 0.0
        if self._widgets["jitter_var"].get():
            jitter = int(self._widgets["jitter_amount"].get()) / 100
        return PlaybackOptions(
            loop_forever=bool(self._widgets["loop_var"].get()), jitter=jitter
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

    def on_bind(self, kind: str) -> None:
        """Bind either the play or the record hotkey."""
        spec = self._widgets[f"{kind}_hotkey_var"].get().strip()
        callback = self._on_play_hotkey if kind == "play" else self._on_record_hotkey
        try:
            self._start_hotkey(kind, spec, callback)
        except InvalidHotkeyError as exc:
            self.set_message(str(exc), error=True)
            return
        if kind == "play":
            self.play_hotkey = spec
            self.set_message(f"{spec.upper()} starts and stops playback.")
        else:
            self.record_hotkey = spec
            self.set_message(f"{spec.upper()} starts and stops recording.")

    def _start_hotkey(self, kind: str, spec: str, callback: Any) -> None:
        existing = self._listeners.pop(kind, None)
        if existing is not None:
            existing.__exit__()
        listener = HotkeyListener(spec, callback)
        listener.__enter__()
        self._listeners[kind] = listener

    def _on_play_hotkey(self) -> None:
        name = self.selected_macro()
        if name is None:
            self.set_message("Select a macro before using the play hotkey.", error=True)
            return
        try:
            self.controller.toggle_playback(name, self.playback_options())
        except Exception:  # noqa: BLE001 - hotkey thread must never die
            logger.exception("play hotkey failed")

    def _on_record_hotkey(self) -> None:
        name = self._widgets["name_var"].get().strip()
        if not name:
            self.set_message("Type a macro name before using the record hotkey.", True)
            return
        try:
            self.controller.toggle_recording(
                name, record_movement=bool(self._widgets["movement_var"].get())
            )
        except Exception:  # noqa: BLE001 - hotkey thread must never die
            logger.exception("record hotkey failed")

    def _update_jitter_label(self) -> None:
        label = self._widgets.get("jitter_label")
        if label is None:
            return
        if not self._widgets["jitter_var"].get():
            label.configure(text="off")
            return
        amount = int(self._widgets["jitter_amount"].get())
        # jitter=0.1 means each gap varies by +/-5%, so show the half-range.
        label.configure(text=f"+/-{amount / 2:g}%")

    def on_overlay(self) -> None:
        if self._widgets["overlay_var"].get():
            self.set_message("Overlay will appear while a macro plays.")
        else:
            self._close_overlay()

    def _show_overlay(self) -> None:
        """Open the HUD as a Toplevel of this window (never a second Tk root)."""
        if self._overlay is not None or self.root is None:
            return
        self.overlay_model.set_idle()
        self._overlay = KeyOverlay(self.overlay_model, parent=self.root)
        try:
            self._overlay.show()
        except Exception:  # noqa: BLE001 - the HUD must never break playback
            logger.exception("could not show overlay")
            self._overlay = None

    def _on_playback_event(self, event: Any) -> None:
        """Runs on the playback thread: only touch the model, never widgets."""
        apply_event_to_model(self.overlay_model, event)

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
        if state is AppState.PLAYING and self._widgets["overlay_var"].get():
            self._show_overlay()
            self.overlay_model.set_playing(self.selected_macro() or "macro", 1, None)
        if state is AppState.RECORDING and self._widgets["overlay_var"].get():
            self._show_overlay()
            self.overlay_model.set_recording(self._widgets["name_var"].get().strip())
        if state is AppState.IDLE:
            self.overlay_model.set_idle()
            self._close_overlay()
            self.refresh_library()
            if self.controller.last_error:
                self.set_message(self.controller.last_error, error=True)
                self.controller.last_error = None

    # -- lifecycle -----------------------------------------------------

    def close(self) -> None:
        self.controller.shutdown()
        for listener in self._listeners.values():
            listener.__exit__()
        self._listeners.clear()
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
