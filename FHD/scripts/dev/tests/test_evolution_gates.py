# FHD/scripts/dev/tests/test_evolution_gates.py
"""三重硬门禁脚本单元测试。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent


def _run_script(script_name: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / script_name), *args],
        capture_output=True,
        text=True,
        cwd=str(SCRIPTS_DIR.parent.parent),
    )


def test_check_footprint_passes_low_risk_paths(tmp_path):
    """employee_pack 文件不在 HIGH_RISK_PATTERNS 时通过。"""
    changed_files = [
        "成都修茈科技有限公司/MODstore_deploy/catalog_data/files/intent-clerk@1.0.0/prompt.txt",
        "成都修茈科技有限公司/MODstore_deploy/catalog_data/files/intent-clerk@1.0.0/skills.json",
    ]
    files_list = tmp_path / "changed.txt"
    files_list.write_text("\n".join(changed_files), encoding="utf-8")
    result = _run_script("check_footprint.py", "--files-list", str(files_list))
    assert result.returncode == 0, f"expected pass, got: {result.stderr}"


def test_check_footprint_fails_on_env_file(tmp_path):
    changed_files = ["foo.env", "config.yaml"]
    files_list = tmp_path / "changed.txt"
    files_list.write_text("\n".join(changed_files), encoding="utf-8")
    result = _run_script("check_footprint.py", "--files-list", str(files_list))
    assert result.returncode == 1
    assert "foo.env" in result.stderr


def test_check_footprint_fails_on_workflow_file(tmp_path):
    changed_files = [".github/workflows/evil.yml"]
    files_list = tmp_path / "changed.txt"
    files_list.write_text("\n".join(changed_files), encoding="utf-8")
    result = _run_script("check_footprint.py", "--files-list", str(files_list))
    assert result.returncode == 1
    assert ".github/workflows/evil.yml" in result.stderr


def test_check_budget_passes_under_limit(tmp_path):
    budget_file = tmp_path / "budget.json"
    budget_file.write_text(
        json.dumps(
            {
                "tokens_used": 45000,
                "tokens_limit": 100000,
                "time_used_minutes": 15,
                "time_limit_minutes": 30,
            }
        ),
        encoding="utf-8",
    )
    result = _run_script("check_budget.py", "--budget-file", str(budget_file))
    assert result.returncode == 0


def test_check_budget_fails_on_token_overrun(tmp_path):
    budget_file = tmp_path / "budget.json"
    budget_file.write_text(
        json.dumps(
            {
                "tokens_used": 150000,
                "tokens_limit": 100000,
                "time_used_minutes": 15,
                "time_limit_minutes": 30,
            }
        ),
        encoding="utf-8",
    )
    result = _run_script("check_budget.py", "--budget-file", str(budget_file))
    assert result.returncode == 1
    assert "tokens" in result.stderr.lower()


def test_check_budget_fails_on_time_overrun(tmp_path):
    budget_file = tmp_path / "budget.json"
    budget_file.write_text(
        json.dumps(
            {
                "tokens_used": 50000,
                "tokens_limit": 100000,
                "time_used_minutes": 45,
                "time_limit_minutes": 30,
            }
        ),
        encoding="utf-8",
    )
    result = _run_script("check_budget.py", "--budget-file", str(budget_file))
    assert result.returncode == 1
    assert "time" in result.stderr.lower()


def test_check_budget_handles_missing_file(tmp_path):
    result = _run_script("check_budget.py", "--budget-file", str(tmp_path / "nope.json"))
    assert result.returncode == 1
    assert "not found" in result.stderr.lower() or "missing" in result.stderr.lower()
