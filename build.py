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


def build(onefile: bool) -> tuple[Path, float]:
    """Run PyInstaller; returns the artifact path and how long it took."""
    shape = "--onefile" if onefile else "--onedir"
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        shape,
        "--windowed",  # no console window when double-clicked
        "--noconfirm",
        "--clean",
        "--name",
        APP_NAME,
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
    print(f"\n=== building {shape} ===")
    started = time.perf_counter()
    subprocess.run(command, check=True, cwd=ROOT)
    elapsed = time.perf_counter() - started

    artifact = ROOT / "dist" / (f"{APP_NAME}.exe" if onefile else APP_NAME)
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
        artifact, elapsed = build(onefile)
        results.append((artifact, tree_size(artifact), elapsed))

    print("\n=== result ===")
    for artifact, size, elapsed in results:
        print(f"{artifact.name:<20} {human_size(size):>10}  built in {elapsed:.0f}s")
        print(f"  {artifact}")

    folder = ROOT / "dist" / APP_NAME
    if folder.is_dir():
        zipped = shutil.make_archive(
            str(ROOT / "dist" / APP_NAME), "zip", root_dir=folder
        )
        size = human_size(Path(zipped).stat().st_size)
        print(f"\nZipped for sharing: {zipped} ({size})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
