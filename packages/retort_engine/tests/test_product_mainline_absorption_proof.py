from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from retort_engine.contracts import validate_contract
from retort_engine.product_mainline_absorption_proof import build_product_mainline_absorption_proof
from retort_engine.service import RetortService


def test_product_mainline_absorption_proof_requires_merge_with_behavior_and_tests(tmp_path: Path) -> None:
    project = _write_git_merge_fixture(tmp_path)

    result = build_product_mainline_absorption_proof(project)

    assert result["status"] == "ready"
    assert result["summary"]["is_merge_commit"] is True
    assert result["summary"]["behavior_source_changed_count"] >= 1
    assert result["summary"]["behavior_test_changed_count"] >= 1
    assert result["summary"]["post_merge_quality_gate_passed"] is True
    assert validate_contract("product_mainline_absorption_proof_result", result)["valid"] is True


def test_service_exposes_product_mainline_absorption_proof(tmp_path: Path) -> None:
    project = _write_git_merge_fixture(tmp_path)

    result = RetortService().product_mainline_absorption_proof({"project": str(project)})

    assert result["status"] == "ready"
    assert result["summary"]["docs_only"] is False


def test_product_mainline_absorption_proof_cli_outputs_contract(tmp_path: Path) -> None:
    project = _write_git_merge_fixture(tmp_path)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "retort_engine.cli",
            "product-mainline-absorption-proof",
            "--project",
            str(project),
            "--json",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert validate_contract("product_mainline_absorption_proof_result", payload)["valid"] is True
    assert payload["summary"]["is_merge_commit"] is True


def _write_git_merge_fixture(root: Path) -> Path:
    project = root / "packages" / "retort_engine"
    source = project / "retort_engine" / "mainline_behavior.py"
    test = project / "tests" / "test_mainline_behavior.py"
    docs = project / "docs"
    source.parent.mkdir(parents=True)
    test.parent.mkdir(parents=True)
    docs.mkdir(parents=True)
    source.write_text("def value():\n    return 1\n", encoding="utf-8")
    test.write_text("def test_value():\n    assert True\n", encoding="utf-8")
    _write_quality(project)
    _git(root, "init")
    _git(root, "config", "user.email", "retort@example.test")
    _git(root, "config", "user.name", "Retort Test")
    _git(root, "checkout", "-b", "main")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "initial")
    _git(root, "checkout", "-b", "absorb-feature")
    source.write_text("def value():\n    return 2\n", encoding="utf-8")
    test.write_text("from retort_engine.mainline_behavior import value\n\n\ndef test_value():\n    assert value() == 2\n", encoding="utf-8")
    _write_quality(project)
    _git(root, "add", ".")
    _git(root, "commit", "-m", "absorb behavior")
    _git(root, "checkout", "main")
    _git(root, "merge", "--no-ff", "absorb-feature", "-m", "merge absorption")
    return project


def _write_quality(project: Path) -> None:
    (project / "docs" / "retort_quality_gate_bundle.json").write_text(
        json.dumps({"status": "ready", "summary": {"all_gates_passed": True, "test_to_source_ratio": 1.0, "contract_schema_count": 48}}, ensure_ascii=False),
        encoding="utf-8",
    )


def _git(cwd: Path, *args: str) -> None:
    completed = subprocess.run(["git", *args], cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    assert completed.returncode == 0, completed.stderr
