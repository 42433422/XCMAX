from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "ci" / "check_broad_except_gate.py"
SPEC = importlib.util.spec_from_file_location("check_broad_except_gate", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


def test_scan_ignores_a_file_deleted_after_git_inventory(tmp_path: Path) -> None:
    missing = tmp_path / "deleted.py"

    assert gate._scan([missing]) == []
