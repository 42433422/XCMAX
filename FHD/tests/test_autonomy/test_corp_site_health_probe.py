from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_cli_bootstraps_fhd_import_path_outside_repo(tmp_path: Path) -> None:
    script = (
        Path(__file__).resolve().parents[2] / "scripts" / "autonomy" / "corp_site_health_probe.py"
    )

    completed = subprocess.run(
        [sys.executable, "-S", str(script), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--base-url" in completed.stdout
