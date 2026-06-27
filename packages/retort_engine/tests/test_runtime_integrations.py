from __future__ import annotations

import json
from pathlib import Path

from retort_engine.core import RetortService as CoreRetortService
from retort_engine.employee_queue import RetortEmployeeQueue
from retort_engine.feedback import feedback_ingest
from retort_engine.history import RetortHistoryStore
from retort_engine.license_gate import license_gate
from retort_engine.models import ImprovementTask
from retort_engine.runtime_adapter import RetortEmployeeRuntimeAdapter
from retort_engine.semantic_reviewer import semantic_compare
from retort_engine.service import RetortService, create_app
from retort_engine.ui_server import RetortUIServer
from tests.test_evidence_evaluator import create_focused_tool_package, create_incomplete_package, write_file


def test_employee_runtime_adapter_dispatches_and_records(tmp_path: Path) -> None:
    queue_path = tmp_path / "employee_queue.jsonl"
    history_path = tmp_path / "retort_history.sqlite"
    dispatched = []
    task = ImprovementTask("retort-absorb-adapter", "Adapter", "employee_execution_integration", "why", "act", "accept", "fhd-core-maintainer")
    adapter = RetortEmployeeRuntimeAdapter(queue_path, history_store=history_path, dispatch_hook=dispatched.append)
    records = adapter.submit_tasks((task,), source="unit")
    assert records[0].task.task_id == task.task_id
    assert dispatched[0].task.task_id == task.task_id
    assert RetortEmployeeQueue(queue_path).load()[0]["task"]["task_id"] == task.task_id
    assert RetortHistoryStore(history_path).path.is_file()


def test_feedback_ingest_accepts_result_file(tmp_path: Path) -> None:
    result_file = tmp_path / "employee_result.json"
    history_path = tmp_path / "retort_history.sqlite"
    result_file.write_text(json.dumps({"task_id": "task-1", "status": "completed", "summary": "ok", "score_after": {"feedback_loop_closure": 92}}), encoding="utf-8")
    result = feedback_ingest(history_store=str(history_path), result_file=str(result_file))
    assert result.score_after["feedback_loop_closure"] == 92


def test_license_gate_and_semantic_compare(tmp_path: Path) -> None:
    licensed = tmp_path / "licensed"
    missing = tmp_path / "missing"
    own = tmp_path / "own"
    external = tmp_path / "external"
    licensed.mkdir()
    missing.mkdir()
    write_file(licensed / "LICENSE", "MIT License\n")
    create_incomplete_package(own)
    create_focused_tool_package(external)
    assert license_gate(licensed).passed
    assert license_gate(missing).status == "warning"
    assert license_gate(missing, enforce=True).status == "blocked"
    assert semantic_compare(own, external)


def test_license_gate_blocks_incompatible_and_reads_metadata(tmp_path: Path) -> None:
    gpl = tmp_path / "gpl"
    package = tmp_path / "package"
    gpl.mkdir()
    package.mkdir()
    write_file(gpl / "LICENSE", "GNU Affero General Public License v3.0\n")
    write_file(package / "package.json", json.dumps({"license": "Apache-2.0"}))

    assert license_gate(gpl).status == "blocked"
    assert license_gate(gpl, enforce=True).status == "blocked"
    metadata_result = license_gate(package, enforce=True)
    assert metadata_result.status == "passed"
    assert metadata_result.detected_license == "Apache-2.0"


def test_product_service_and_blackhole_ui_surface(tmp_path: Path) -> None:
    project = tmp_path / "project"
    create_focused_tool_package(project)
    payload = RetortService().assess({"project": str(project), "context_policy": "provided", "gate_results": {"lint": True, "test": True}})
    assert payload["scores"] == []
    assert payload["metadata"]["score_source"] == "paibi_llm_pending"
    assert payload["metadata"]["score_authority"] == "paibi_llm_prompt_only"
    assert create_app() is not None
    ui_root = RetortUIServer().static_root
    assert "blackhole" in (ui_root / "app.js").read_text(encoding="utf-8").lower()
    assert "ownProjectFolder" in (ui_root / "index.html").read_text(encoding="utf-8")


def test_service_exposes_codebase_graph_report(tmp_path: Path) -> None:
    project = tmp_path / "project"
    package = project / "retort_engine"
    package.mkdir(parents=True)
    write_file(package / "flow.py", "def target():\n    return 1\n\ndef caller():\n    return target()\n")

    report = RetortService().codebase_graph_report({"project": str(project)})

    assert report["status"] == "ready"
    assert report["summary"]["call_edge_count"] == 1
    assert any(edge["kind"] == "calls" and edge["to"].endswith(":target") for edge in report["edges"])
    assert CoreRetortService().codebase_graph_report({"project": str(project)})["status"] == "ready"


def test_service_exposes_evolution_map(tmp_path: Path) -> None:
    project = tmp_path / "project"
    package = project / "retort_engine"
    package.mkdir(parents=True)
    write_file(package / "__init__.py", "")
    write_file(package / "codebase_graph.py", "def graph():\n    return 'code graph'\n")

    wrapped = RetortService().evolution_map({"project": str(project)})
    core = CoreRetortService().evolution_map({"project": str(project)})

    assert wrapped["status"] == "ready"
    assert wrapped["code_graph"]["summary"]["file_count"] == 2
    assert core["status"] == "ready"


def test_service_exposes_architecture_contract_report(tmp_path: Path) -> None:
    project = tmp_path / "project"
    package = project / "retort_engine"
    package.mkdir(parents=True)
    write_file(package / "codebase_graph.py", "import ast\n")

    report = RetortService().architecture_contract_report({"project": str(project)})
    core_report = CoreRetortService().architecture_contract_report({"project": str(project)})

    assert report["status"] == "passed"
    assert report["summary"]["violation_count"] == 0
    assert core_report["status"] == "passed"
