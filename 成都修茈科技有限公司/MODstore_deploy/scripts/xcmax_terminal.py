#!/usr/bin/env python3
"""Repository wrapper for :mod:`modstore_server.diagnostic_terminal_cli`."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_PYTHON = ROOT / ".venv/bin/python"
if VENV_PYTHON.is_file() and Path(sys.executable).absolute() != VENV_PYTHON.absolute():
    os.execv(
        str(VENV_PYTHON),
        [str(VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]],
    )

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modstore_server.diagnostic_terminal_cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
