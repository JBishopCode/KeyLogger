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

Options:

- `-v` / `--verbose` — log every individual event (DEBUG)
- `--stop-key <key>` — use a different stop key when recording (default `esc`)

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
the original inter-event gaps. Mouse *movement* is deliberately never recorded or replayed.

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
| 2026-09-04 | Replay (steps 5–6) | **PENDING RE-RUN** — first attempt crashed before any click was sent (see below); fixed, awaiting a repeat run. |

Replay crash, 2026-09-04: `pydirectinput.mouseDown` takes `x` as its first positional
parameter and `button` third, so passing the button positionally made the library treat
`"right"` as an X coordinate and call `moveTo`, raising
`TypeError: unsupported operand type(s) for //: 'str' and 'int'`. The player now binds
mouse buttons by keyword (`mouseDown(button=...)`) with `x`/`y` left as `None`, so no
pointer movement is emitted. Regression tests:
`test_clicks_pass_the_button_by_keyword_not_as_a_coordinate` and
`test_replay_never_moves_the_mouse` in `tests/test_player_timing.py`.

Whether Minecraft Java actually registers replayed input is still unproven — the run never
reached a click. Re-run steps 5–6 and record the outcome here.

## Windows Defender / SmartScreen

This tool installs a global keyboard hook, which is the same pattern a keylogger uses, so
antivirus and SmartScreen may flag it. Nothing is transmitted — events stay in local JSON
files you can open and read.

When the packaged `.exe` arrives in a later milestone it will be unsigned, so Windows
SmartScreen will show "Windows protected your PC". Choose **More info → Run anyway** to
launch it.

## A note on server rules

Automating input on a public server (e.g. Hypixel Skyblock) may violate its rules
regardless of how the input is generated, and can get an account actioned. Prefer a
private or single-player world.
