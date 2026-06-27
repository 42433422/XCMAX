from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from retort_engine.real_absorption import apply_real_absorption
from retort_engine.real_absorption_run_proof import code_graph_proof_gate, record_real_absorption_run


def test_real_absorption_records_per_run_code_graph_proof(tmp_path: Path) -> None:
    project = tmp_path / "own"
    external = tmp_path / "external"
    (project / "retort_engine").mkdir(parents=True)
    (project / "retort_engine" / "__init__.py").write_text("", encoding="utf-8")
    (external / "src").mkdir(parents=True)
    (external / "src" / "review.py").write_text("review pipeline changed files diff hunk benchmark provider plugin\n", encoding="utf-8")

    result = apply_real_absorption(
        {
            "own_project": str(project),
            "external_path": str(external),
            "source": "proof-source",
            "tasks": [{"task_id": "retort-absorb-review", "title": "Review pipeline", "dimension": "comparative_analysis_depth", "priority": "P1"}],
            "python": sys.executable,
        }
    )

    run_path = Path(result["run_record_path"])
    run_payload = json.loads(run_path.read_text(encoding="utf-8"))
    proof = run_payload["code_graph_proof"]

    assert run_path.name == f"{result['run_id']}.json"
    assert proof["run_id"] == result["run_id"]
    assert proof["per_run_required"] is True
    assert proof["evidence"]["scope"] == "per_real_absorption_run"
    assert proof["evidence"]["style"] == "deterministic_post_absorption_code_graph"
    assert "changed_file_count" in proof["summary"]
    assert any(gate["command"][:2] == ["retort", "verify-per-run-code-graph-proof"] and gate["ok"] for gate in result["gates"])


def test_real_absorption_run_record_rejects_missing_per_run_proof(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="missing per-run code graph proof"):
        record_real_absorption_run(tmp_path, {"run_id": "run-1", "code_graph_proof": {"run_id": "other"}})


def test_code_graph_proof_gate_reports_missing_structure() -> None:
    gate = code_graph_proof_gate({"run_id": "wrong"}, run_id="run-1")

    assert gate["ok"] is False
    assert gate["exit_code"] == 1
    assert "code_graph_proof_run_id_mismatch" in gate["stderr_tail"]
