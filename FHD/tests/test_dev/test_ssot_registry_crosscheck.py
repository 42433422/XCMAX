"""registry-crosscheck：ssot.yaml ↔ SSOT_INDEX 机器注册表。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

FHD = Path(__file__).resolve().parents[2]
SCRIPT = FHD / "scripts" / "dev" / "ssot_registry_crosscheck.py"


def test_registry_crosscheck_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "check"],
        cwd=str(FHD),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
