"""Timezone-stable date formatting for generated capability pages."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "成都修茈科技有限公司/scripts/build_capability_center.py"
SPEC = importlib.util.spec_from_file_location("build_capability_center", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_commit_date_uses_project_timezone_for_utc_merge_timestamp() -> None:
    assert MODULE.project_code_date("2026-09-25T23:37:08+00:00") == "2026-09-26"


def test_commit_date_accepts_git_utc_suffix_on_python_39() -> None:
    assert MODULE.project_code_date("2026-09-25T23:37:08Z") == "2026-09-26"


def test_commit_date_preserves_product_local_offset() -> None:
    assert MODULE.project_code_date("2026-09-26T07:37:08+08:00") == "2026-09-26"


def test_commit_date_rejects_missing_timezone() -> None:
    assert MODULE.project_code_date("2026-09-26T07:37:08") is None
