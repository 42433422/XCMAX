from __future__ import annotations

import json
from pathlib import Path

from retort_engine.employee_queue import RetortEmployeeQueue
from retort_engine.feedback import feedback_ingest
from retort_engine.history import RetortHistoryStore
from retort_engine.license_gate import license_gate
from retort_engine.models import ImprovementTask
from retort_engine.runtime_adapter import RetortEmployeeRuntimeAdapter
from retort_engine.semantic_reviewer import semantic_compare
from retort_engine.service import RetortService, create_app
from retort_engine.ui_server import RetortUIServer
from tests.test_static_evaluator import create_focused_tool_package, create_incomplete_package, write_file


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
    assert semantic_compare(own, external)


def test_product_service_and_blackhole_ui_surface(tmp_path: Path) -> None:
    project = tmp_path / "project"
    create_focused_tool_package(project)
    payload = RetortService().assess({"project": str(project), "context_policy": "provided", "gate_results": {"lint": True, "test": True}})
    assert payload["scores"]
    assert create_app() is not None
    ui_root = RetortUIServer().static_root
    assert "blackhole" in (ui_root / "app.js").read_text(encoding="utf-8").lower()
    assert "ownProjectFolder" in (ui_root / "index.html").read_text(encoding="utf-8")
