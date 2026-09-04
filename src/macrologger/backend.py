"""Lazy loading of the Windows input backends.

``pynput`` (capture) and ``pydirectinput`` (replay) are imported late so the
pure logic stays importable anywhere, and so a missing dependency surfaces as
an actionable message at the CLI boundary instead of a raw
``ModuleNotFoundError`` traceback -- the usual cause being the system Python
running instead of the project virtualenv.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

logger = logging.getLogger(__name__)

_INSTALL_HINT = (
    "activate the project venv (.venv\\Scripts\\activate) "
    "or run: pip install -r requirements.txt"
)


class BackendUnavailableError(Exception):
    """Raised when an input backend cannot be imported."""


def _missing(package: str) -> BackendUnavailableError:
    return BackendUnavailableError(
        f"{package} is not installed for this Python ({sys.executable}); {_INSTALL_HINT}"
    )


def load_pynput() -> Any:
    """Return the ``pynput`` package, or raise with an actionable message."""
    try:
        import pynput

        return pynput
    except ImportError as exc:
        raise _missing("pynput") from exc


def load_pydirectinput() -> Any:
    """Return ``pydirectinput``, configured for faithful replay timing."""
    try:
        import pydirectinput
    except ImportError as exc:
        raise _missing("pydirectinput") from exc

    # Minecraft needs every event at the recorded time; the library's built-in
    # pause and corner failsafe would distort the gaps, so both are disabled.
    pydirectinput.PAUSE = 0
    pydirectinput.FAILSAFE = False
    return pydirectinput
