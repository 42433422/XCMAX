"""Direct-execution smoke tests for the online update daemon."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]


def test_script_help_imports_app_from_fhd_working_directory() -> None:
    """The production cron executes the daemon by path from the deploy root."""
    completed = subprocess.run(
        [sys.executable, "-I", "scripts/deploy/online_update_daemon.py", "--help"],
        cwd=FHD_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
