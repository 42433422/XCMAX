from __future__ import annotations

import json
from pathlib import Path

from retort_engine.core import assess_project
from retort_engine.core_refactor_execution import EXTRACTED_BOUNDARY_MODULES, load_core_refactor_plan, verify_core_refactor_execution


def test_current_core_refactor_plan_is_backed_by_real_modules_and_tests() -> None:
    project = Path(__file__).resolve().parents[1]
    result = verify_core_refactor_execution(project)

    assert result["status"] == "implemented"
    assert result["task_count"] >= 11
    assert result["implemented_task_count"] == result["task_count"]
    assert result["missing"] == []
    assert set(EXTRACTED_BOUNDARY_MODULES) >= {item["component"] for item in result["components"]}
    assert all(item["test_function_count"] > 0 for item in result["components"])


def test_refactor_execution_blocks_missing_component_boundary(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "retort_core_refactor_plan.json").write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "component": "workflow_ci",
                        "ready_for_core_refactor": True,
                        "modules": ["retort_engine/absorption_workflow.py", "retort_engine/proof.py"],
                        "tests": ["tests/test_absorption_workflow.py"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "retort_engine").mkdir()
    (tmp_path / "retort_engine" / "proof.py").write_text("# ok\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_absorption_workflow.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    result = verify_core_refactor_execution(tmp_path, load_core_refactor_plan(tmp_path))

    assert result["status"] == "blocked"
    assert any("workflow_ci:missing_module:retort_engine/absorption_workflow.py" == item for item in result["missing"])


def test_assessment_reports_core_refactor_execution_status() -> None:
    project = Path(__file__).resolve().parents[1]
    assessment = assess_project(str(project))

    assert "core_refactor_execution_status=implemented" in assessment.evidence
    execution = assessment.metadata["core_refactor_execution"]
    assert f"core_refactor_implemented_tasks={execution['implemented_task_count']}/{execution['task_count']}" in assessment.evidence
    assert execution["implemented_task_count"] == execution["task_count"]
