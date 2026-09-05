"""Entry point for ``python -m macrologger`` and for the packaged .exe.

With no arguments it opens the control window, which is what double-clicking
the .exe does. With arguments it behaves exactly like the CLI.
"""

from __future__ import annotations

import sys


def main() -> int:
    # Absolute imports on purpose: when PyInstaller runs this file as the
    # frozen entry script it has no parent package, so relative imports fail.
    from macrologger.cli import main as cli_main

    if len(sys.argv) == 1:
        from macrologger.ui import run_app

        run_app()
        return 0
    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
