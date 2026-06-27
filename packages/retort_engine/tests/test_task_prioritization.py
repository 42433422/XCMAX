from __future__ import annotations

import json
from pathlib import Path

from retort_engine.contracts import validate_contract
from retort_engine.task_prioritization import build_task_prioritization_report


def test_build_task_prioritization_report_uses_queue_and_results(tmp_path: Path) -> None:
    project = tmp_path / "project"
    queue = project / ".retort" / "employee_queue.jsonl"
    results = project / ".retort" / "employee_results"
    queue.parent.mkdir(parents=True)
    results.mkdir(parents=True)
    queue.write_text(
        "\n".join(
            [
                json.dumps({"task": {"dimension": "comparative_analysis_depth"}}, ensure_ascii=False),
                json.dumps({"task": {"dimension": "comparative_analysis_depth"}}, ensure_ascii=False),
                json.dumps({"task": {"dimension": "product_operability"}}, ensure_ascii=False),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (results / "run.json").write_text(
        json.dumps({"results": [{"status": "completed", "summary": "comparative_analysis_depth done"}]}, ensure_ascii=False),
        encoding="utf-8",
    )

    result = build_task_prioritization_report(project)

    assert result["status"] == "ready"
    assert result["summary"]["queued_task_count"] == 3
    assert result["summary"]["completed_result_count"] == 1
    assert result["summary"]["all_tasks_have_acceptance"] is True
    assert result["summary"]["ready_employee_task_count"] == 2
    assert result["priorities"][0]["dimension"] == "comparative_analysis_depth"
    assert result["priorities"][0]["acceptance"]
    assert result["priorities"][0]["evidence_required"]
    assert validate_contract("task_prioritization_result", result)["valid"] is True
