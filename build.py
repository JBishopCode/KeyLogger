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
