"""Build the Windows executable with PyInstaller.

Two shapes, because they fail differently:

* ``--onedir`` (default) -- a folder containing MacroLogger.exe. Starts fast
  and is far less likely to be quarantined, because a one-file build unpacks
  itself into %TEMP% on every launch, which is behaviour antivirus heuristics
  treat as suspicious. Ship it zipped.
* ``--onefile`` -- a single .exe, nicer to hand over, slower to start and more
  likely to trip Defender.

Usage::

    python build.py            # onedir  -> dist/MacroLogger/
    python build.py --onefile  # onefile -> dist/MacroLogger.exe
    python build.py --both     # build both and compare
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENTRY = ROOT / "src" / "macrologger" / "__main__.py"
APP_NAME = "MacroLogger"


def human_size(size: int) -> str:
    megabytes = size / (1024 * 1024)
    return f"{megabytes:.1f} MB"


def tree_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def build(onefile: bool, console: bool = False) -> tuple[Path, float]:
    """Run PyInstaller; returns the artifact path and how long it took.

    Two targets get built, because one binary cannot do both jobs well on
    Windows: a --windowed build has no console, so CLI output is invisible,
    while a --console build flashes a terminal when double-clicked.
    """
    shape = "--onefile" if onefile else "--onedir"
    name = f"{APP_NAME}-cli" if console else APP_NAME
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        shape,
        "--console" if console else "--windowed",
        "--noconfirm",
        "--clean",
        "--name",
        name,
        # The package lives under src/, which is not on the path when
        # PyInstaller analyses the entry script.
        "--paths",
        str(ROOT / "src"),
        # pywin32 and pynput import these dynamically, so static analysis
        # misses them and the frozen app dies on first use.
        "--hidden-import",
        "win32gui",
        "--hidden-import",
        "win32api",
        "--hidden-import",
        "pynput.keyboard._win32",
        "--hidden-import",
        "pynput.mouse._win32",
        str(ENTRY),
    ]
    print(f"\n=== building {name} {shape} ===")
    started = time.perf_counter()
    subprocess.run(command, check=True, cwd=ROOT)
    elapsed = time.perf_counter() - started

    artifact = ROOT / "dist" / (f"{name}.exe" if onefile else name)
    return artifact, elapsed


RECIPIENT_NOTICE = """MACRO LOGGER - READ THIS BEFORE RUNNING

What it is
  A Minecraft macro tool. It records the keys you press, your mouse clicks
  and (optionally) your mouse movement, then replays them.

What that means in practice
  * To record your input it installs a system-wide keyboard and mouse hook.
    That is the same technique a keylogger uses, so antivirus and Windows
    SmartScreen may warn about it or block it. The app is not signed.
  * If you enable "Record mouse movement", mouse motion is captured through
    Windows Raw Input while recording is active, INCLUDING while another
    window is focused. It stops the moment you stop recording.
  * Everything is saved to plain JSON files in the "macros" folder next to
    this program. You can open them in Notepad and read exactly what was
    recorded.
  * Nothing is sent anywhere. The app makes no network connections of any
    kind: no uploads, no telemetry, no accounts.

If Windows blocks it
  SmartScreen: "More info" -> "Run anyway".
  Windows Defender may quarantine it; you would need to allow it explicitly.
  Only do that if you trust whoever gave you this file.

Check it works
  Run MacroLogger-cli.exe doctor in a terminal. It reports whether every
  input backend loaded.

Using it
  Double-click MacroLogger.exe for the control window.
  Mouse movement replays accurately only if Windows "Enhance pointer
  precision" is turned OFF (Settings -> Mouse -> Additional mouse settings
  -> Pointer Options).

A note on servers
  Automating input can break the rules of public Minecraft servers
  regardless of how it is done. Prefer a private or single-player world.
"""


def _write_readme(path: Path) -> None:
    path.write_text(RECIPIENT_NOTICE, encoding="utf-8")
    print(f"  wrote {path.name}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the Windows executable.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--onefile", action="store_true", help="single .exe")
    group.add_argument("--both", action="store_true", help="build both and compare")
    args = parser.parse_args()

    shapes = [False, True] if args.both else [args.onefile]
    results = []
    for onefile in shapes:
        for console in (False, True):
            artifact, elapsed = build(onefile, console=console)
            results.append((artifact, tree_size(artifact), elapsed))

    print("\n=== result ===")
    for artifact, size, elapsed in results:
        print(f"{artifact.name:<20} {human_size(size):>10}  built in {elapsed:.0f}s")
        print(f"  {artifact}")

    gui_folder = ROOT / "dist" / APP_NAME
    cli_folder = ROOT / "dist" / f"{APP_NAME}-cli"
    if gui_folder.is_dir():
        # Put the console build inside the shared folder so one zip carries
        # both: double-click the GUI, or run the -cli one for commands.
        if cli_folder.is_dir():
            for item in cli_folder.iterdir():
                target = gui_folder / item.name
                if item.is_file() and not target.exists():
                    shutil.copy2(item, target)
            # Remove the staging folder: two near-identical folders in dist/
            # is confusing, and only the merged one should be shipped.
            shutil.rmtree(cli_folder, ignore_errors=True)
        # The disclosure has to travel with the binary: whoever receives the
        # zip cannot read the repo, and this app behaves like a keylogger.
        _write_readme(gui_folder / "READ ME FIRST.txt")

        zipped = shutil.make_archive(
            str(ROOT / "dist" / APP_NAME), "zip", root_dir=gui_folder
        )
        size = human_size(Path(zipped).stat().st_size)
        print(f"\nZipped for sharing: {zipped} ({size})")
        print(f"  double-click       : {APP_NAME}.exe")
        print(f"  commands / doctor  : {APP_NAME}-cli.exe doctor")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
