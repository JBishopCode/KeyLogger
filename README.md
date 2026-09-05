# Minecraft Macro Logger — Record & Replay Core (Milestone 1)

Records your real keyboard presses/releases and mouse clicks with exact timing, saves them
as a named macro, and replays them through DirectInput so Minecraft Java registers the input.

This milestone is headless (CLI only). The UI, global hotkey, loop/jitter options, live
keypress overlay, and single-file `.exe` packaging are later milestones (see
`.claude/prds/minecraft-macro-logger.prd.md`).

**Local-only by design.** Macros are plain JSON files on your machine. The tool makes no
network calls and sends no data anywhere.

## Requirements

- Windows
- Python 3.11+ (developed and tested on 3.14)

## Setup

This project uses a `src/` layout, so set `PYTHONPATH` to `src` before running the CLI from the repo root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:PYTHONPATH = "src"
```

## Usage

Record — press **Esc** to stop:

```powershell
$env:PYTHONPATH = "src"
python -m macrologger.cli record demo
```

Replay:

```powershell
$env:PYTHONPATH = "src"
python -m macrologger.cli play demo
```

List everything you have recorded:

```powershell
python -m macrologger.cli list
```

```
NAME  EVENTS  SECONDS  RECORDED IN
demo     130    21.62  Minecraft 1.21
```

Options:

- `-v` / `--verbose` — log every individual event (DEBUG)
- `--stop-key <key>` — use a different stop key when recording (default `esc`)
- `--loop N` — replay the macro N times; bare `--loop` repeats until you stop it
- `--loop-delay SECONDS` — pause between loop iterations
- `--jitter FRACTION` — randomize each gap by ±half this fraction, so looped
  cycles are not byte-identical (`0.1` = ±5%)
- `--hotkey [KEYS]` — wait for a hotkey instead of playing immediately; press it
  to start, press again to stop (default `f8`, e.g. `--hotkey ctrl+shift+p`)

### Hotkey playback

```powershell
python -m macrologger.cli play demo --loop --jitter 0.1 --hotkey f8
```

Loads the macro and waits. Alt-tab into Minecraft, press **F8** to start, press
**F8** again to stop. The hotkey is also the emergency stop — stopping releases
any key or mouse button the macro was still holding, so you are never left
walking forward. Ctrl+C in the terminal quits.

Looping forever requires `--hotkey`, since that is what stops it.

Macros are saved to `macros/<name>.json`:

```json
{
  "name": "demo",
  "created": "2026-09-04T00:00:00Z",
  "events": [
    { "t": 0.0,   "type": "key",   "action": "down", "code": "w",     "window": "Minecraft 1.21" },
    { "t": 0.412, "type": "key",   "action": "up",   "code": "w",     "window": "Minecraft 1.21" },
    { "t": 0.9,   "type": "click", "action": "down", "code": "right", "window": "Minecraft 1.21" }
  ]
}
```

`t` is seconds since the first recorded event (`time.perf_counter()`), so replay reproduces
the original inter-event gaps.

Event types:

| `type` | `action` | Carries | Notes |
|---|---|---|---|
| `key` | `down` / `up` | `code` (`"w"`, `"f5"`, `"shift"`) | |
| `click` | `down` / `up` | `code` (`"left"`, `"right"`, `"middle"`) | |
| `scroll` | `scroll` | `dy` = wheel clicks, positive is up | hotbar selection; always recorded |
| `move` | `move` | `dx`/`dy` = relative pixels | only with `--mouse-movement` |

Older macros still load: v1 files (no `version`, no `dx`/`dy`) and v2 files (no `scroll`)
are read unchanged.

### Overlay spike (Milestone 4, needs in-game verification)

```powershell
python -m macrologger.cli overlay
```

Shows a small always-on-top panel with the keys you are pressing. Alt-tab into
Minecraft and check three things:

1. It stays visible on top of the game.
2. Minecraft **keeps focus** — you can still move and look around. (The window
   sets `WS_EX_NOACTIVATE`, so it should never steal focus.)
3. Clicks pass straight through it into the game (`WS_EX_TRANSPARENT`).

Ctrl+C in the terminal closes it. Move it with `--position 40,200`.

Minecraft must be in **borderless windowed** mode for the overlay to be visible;
in exclusive fullscreen Windows will not composite another window over the game.

| Date | Outcome |
|---|---|
| _pending_ | **NOT YET RUN over Minecraft** — window styles verified programmatically (NOACTIVATE / TRANSPARENT / LAYERED / TOOLWINDOW all set), but on-screen behaviour over the game is unconfirmed. |

## Control window

```powershell
python -m macrologger.cli gui
```

- **Macro list** — every saved macro with its event count, duration and the
  window it was recorded in. Select one to play it.
- **Name + Record** — type a name, hit Record; the button becomes Stop (ESC
  still works too).
- **Record mouse movement** — the opt-in movement toggle.
- **Loop / Jitter / Overlay** — playback options.
- **Hotkey** — type a combination (e.g. `f8`, `ctrl+shift+p`) and press Bind;
  it then starts and stops playback of the selected macro from anywhere.

The CLI commands all still work and are unchanged.

## Building the .exe

```powershell
pip install -r requirements-dev.txt
python build.py            # folder build  -> dist/MacroLogger/  (+ .zip)
python build.py --onefile  # single file   -> dist/MacroLogger.exe
python build.py --both     # build both and compare
```

**The folder build is the one to share.** A one-file exe unpacks itself into
`%TEMP%` on every launch, which is slower to start and is exactly the pattern
antivirus heuristics flag — and this app already looks like a keylogger to a
scanner. `build.py` zips the folder build for you.

| Shape | Size | Notes |
|---|---|---|
| `--onedir` | 26.4 MB (11.8 MB zipped) | recommended; fast start, less likely quarantined |
| `--onefile` | 8.5 MB | single file, slower start, more likely flagged |

Double-clicking `MacroLogger.exe` opens the control window. Passing arguments
runs the CLI instead (`MacroLogger.exe list`, `MacroLogger.exe play demo`).

Macros are stored in a `macros` folder **next to the executable**, so the app
finds the same library wherever it is launched from.

### First thing to run on a new PC

```powershell
MacroLogger.exe doctor
```

Confirms every input backend loaded. Packaging can silently drop dynamically
imported modules, and this catches that immediately instead of at the moment
you try to record:

```
  ok       pynput (capture)
  ok       pydirectinput (replay)
  ok       pywin32 (window titles, overlay)
  ok       tkinter (control window)
```

## Required for accurate mouse movement

**Turn OFF Windows "Enhance pointer precision".**
Settings → Bluetooth & devices → Mouse → Additional mouse settings → Pointer
Options → untick *Enhance pointer precision*.

That setting applies a non-linear acceleration curve to injected mouse input,
so a replayed movement rotates the camera by a different amount than when it
was recorded — the macro traces the right shape but ends on a different
heading. With it off, movement replays accurately (verified in-game
2026-09-04).

Key and click macros are unaffected; this only matters when recording with
`--mouse-movement`.

## Tests

```bash
pytest -q
```

## In-game validation (Minecraft Java)

The load-bearing check for this milestone — does `pydirectinput` actually reach the game?

1. Launch Minecraft Java and load a world (a private/single-player world is recommended;
   see the server-rules note below).
2. In a terminal, run `python -m macrologger.cli record demo` after setting `PYTHONPATH=src`.
3. Alt-tab into Minecraft, hold **W** for about a second, then **right-click** once.
4. Alt-tab back to the terminal and press **Esc** to stop. Confirm the printed event count
   and inspect `macros/demo.json` — the `window` field should read as the Minecraft window.
5. Run `python -m macrologger.cli play demo` after setting `PYTHONPATH=src`, then alt-tab into
   Minecraft before playback reaches the first event.
6. PASS = the character visibly walks forward and the right-click registers in-game.

If nothing registers in-game, **stop** — do not swap libraries silently. The documented
fallback is the Interception driver (a kernel-level input driver); raise it before
continuing to the next milestone.

### Result

| Date | Step | Outcome |
|---|---|---|
| 2026-09-04 | Record (steps 1–4) | **PASS** — 130 events captured to `macros/demo.json` with Minecraft Java focused. |
| 2026-09-04 | Replay (steps 5–6) | **PASS** — after the click fix below, the character visibly walked forward and the right-click registered in Minecraft Java. `pydirectinput` reaches the game; the Interception-driver fallback is **not** needed. |

Replay crash, 2026-09-04: `pydirectinput.mouseDown` takes `x` as its first positional
parameter and `button` third, so passing the button positionally made the library treat
`"right"` as an X coordinate and call `moveTo`, raising
`TypeError: unsupported operand type(s) for //: 'str' and 'int'`. The player now binds
mouse buttons by keyword (`mouseDown(button=...)`) with `x`/`y` left as `None`, so no
pointer movement is emitted. Regression tests:
`test_clicks_pass_the_button_by_keyword_not_as_a_coordinate` and
`test_replay_never_moves_the_mouse` in `tests/test_player_timing.py`.

This resolves the PRD's top open question and risk: Minecraft Java does register
`pydirectinput`'s scancode-level input for both keys and clicks.

## Windows Defender / SmartScreen

This tool installs a global keyboard hook, which is the same pattern a keylogger uses, so
antivirus and SmartScreen may flag it. Nothing is transmitted — events stay in local JSON
files you can open and read.

**Scope of capture, stated plainly:** while a recording is running, keyboard and
mouse-button input is captured system-wide, not just in Minecraft. With "Record mouse
movement" enabled, mouse motion is additionally captured through Windows Raw Input
(`RIDEV_INPUTSINK`), which keeps delivering while another window has focus — that is
what makes recording inside a game with a trapped cursor possible. Capture stops when
the recording stops.

`build.py` writes a plain-English version of this into `READ ME FIRST.txt` inside the
built folder, so anyone you hand the zip to gets the disclosure with the program rather
than having to be told separately.

When the packaged `.exe` arrives in a later milestone it will be unsigned, so Windows
SmartScreen will show "Windows protected your PC". Choose **More info → Run anyway** to
launch it.

## A note on server rules

Automating input on a public server (e.g. Hypixel Skyblock) may violate its rules
regardless of how the input is generated, and can get an account actioned. Prefer a
private or single-player world.
