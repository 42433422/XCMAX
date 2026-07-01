from __future__ import annotations

import json
from pathlib import Path

from retort_engine.generalization_proof import build_generalization_proof, write_generalization_proof


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_generalization_proof_requires_cross_language_ci_and_pr_replay(tmp_path: Path) -> None:
    root = tmp_path / "retort"
    _write(root / ".retort" / "cache" / "github" / "one" / "python-reviewer" / ".github" / "workflows" / "ci.yml")
    _write(root / ".retort" / "cache" / "github" / "one" / "python-reviewer" / "reviewer.py")
    _write(root / ".retort" / "cache" / "github" / "two" / "typescript-reviewer" / "src" / "index.ts")
    _write(root / ".retort" / "cache" / "github" / "three" / "java-reviewer" / "src" / "Main.java")
    for index in range(260):
        _write(root / ".retort" / "cache" / "github" / "three" / "java-reviewer" / "src" / f"Extra{index}.java")
    _write(root / "docs" / "retort_complex_pr_replay.json", json.dumps({"status": "ready"}))

    proof = build_generalization_proof(root)

    assert proof["status"] == "ready"
    assert proof["summary"]["external_project_count"] == 3
    assert proof["summary"]["language_count"] == 3
    assert proof["summary"]["ci_project_count"] == 1
    assert proof["summary"]["large_project_count"] == 1
    assert {check["id"]: check["passed"] for check in proof["checks"]}["pr_runtime_replay_available"] is True


def test_generalization_proof_reports_missing_runtime_pr_replay(tmp_path: Path) -> None:
    root = tmp_path / "retort"
    _write(root / ".retort" / "cache" / "github" / "one" / "python-reviewer" / ".github" / "workflows" / "ci.yml")
    _write(root / ".retort" / "cache" / "github" / "one" / "python-reviewer" / "reviewer.py")
    _write(root / ".retort" / "cache" / "github" / "two" / "typescript-reviewer" / "src" / "index.ts")
    _write(root / ".retort" / "cache" / "github" / "three" / "java-reviewer" / "src" / "Main.java")

    proof = build_generalization_proof(root)

    assert proof["status"] == "needs_more_generalization"
    checks = {check["id"]: check["passed"] for check in proof["checks"]}
    assert checks["pr_runtime_replay_available"] is False


def test_write_generalization_proof_persists_json_report(tmp_path: Path) -> None:
    root = tmp_path / "retort"
    _write(root / ".retort" / "cache" / "github" / "one" / "python-reviewer" / "reviewer.py")

    result = write_generalization_proof(root)

    output = Path(result["output"])
    assert output.name == "retort_generalization_proof.json"
    assert json.loads(output.read_text(encoding="utf-8"))["summary"]["external_project_count"] == 1
