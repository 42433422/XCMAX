from __future__ import annotations

import json
from pathlib import Path

from retort_engine.architecture_refactor import build_core_refactor_plan, write_core_refactor_plan


def test_core_refactor_plan_does_not_block_before_architecture_tasks_are_ready(tmp_path: Path) -> None:
    plan = build_core_refactor_plan({"summary": {"source_count": 1}, "component_index": {}, "deep_architecture_tasks": []}, project_root=tmp_path)

    assert plan["tasks"] == []
    assert plan["gate"]["passed"] is True
    assert plan["gate"]["status"] == "not_ready"


def test_core_refactor_plan_maps_architecture_tasks_to_modules(tmp_path: Path) -> None:
    project = tmp_path
    for rel in [
        "retort_engine/review_pipeline.py",
        "retort_engine/pr_review.py",
        "retort_engine/real_absorption.py",
        "retort_engine/proof.py",
        "retort_engine/git_status.py",
        "tests/test_review_pipeline.py",
        "tests/test_pr_review.py",
        "tests/test_retort_engine.py",
        "tests/test_branching_git_status.py",
    ]:
        path = project / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# ok\n", encoding="utf-8")
    memory = {
        "summary": {"source_count": 3, "ready_component_count": 2},
        "deep_architecture_tasks": [
            {"task_id": "retort-architecture-review-pipeline", "priority": "P0"},
            {"task_id": "retort-architecture-workflow-ci", "priority": "P0"},
        ],
        "component_index": {
            "review_pipeline": {"source_count": 3, "gate_pass_rate": 1.0, "architecture_depth_score": 100, "ready_for_deep_refactor": True},
            "workflow_ci": {"source_count": 3, "gate_pass_rate": 1.0, "architecture_depth_score": 100, "ready_for_deep_refactor": True},
        },
    }

    plan = build_core_refactor_plan(memory, project_root=project)

    assert plan["gate"]["passed"] is True
    assert plan["summary"]["ready_task_count"] == 2
    components = {task["component"] for task in plan["tasks"]}
    assert components == {"review_pipeline", "workflow_ci"}
    assert any("retort_engine/review_pipeline.py" in task["modules"] for task in plan["tasks"])


def test_core_refactor_plan_blocks_missing_core_tests(tmp_path: Path) -> None:
    (tmp_path / "retort_engine").mkdir()
    (tmp_path / "retort_engine" / "review_pipeline.py").write_text("# ok\n", encoding="utf-8")
    memory = {
        "summary": {"source_count": 3, "ready_component_count": 1},
        "deep_architecture_tasks": [{"task_id": "retort-architecture-review-pipeline", "priority": "P0"}],
        "component_index": {"review_pipeline": {"source_count": 3, "gate_pass_rate": 1.0, "architecture_depth_score": 100}},
    }

    plan = build_core_refactor_plan(memory, project_root=tmp_path)

    assert plan["gate"]["passed"] is False
    assert "missing_core_tests" in plan["gate"]["missing"]
    assert plan["tasks"][0]["ready_for_core_refactor"] is False


def test_core_refactor_plan_maps_codebase_graph_component(tmp_path: Path) -> None:
    for rel in [
        "retort_engine/codebase_graph.py",
        "retort_engine/architecture_contracts.py",
        "retort_engine/service.py",
        "retort_engine/cli.py",
        "tests/test_codebase_graph.py",
        "tests/test_architecture_contracts.py",
        "tests/test_contracts_feedback.py",
    ]:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("def test_ok():\n    assert True\n" if rel.startswith("tests/") else "# ok\n", encoding="utf-8")
    memory = {
        "summary": {"source_count": 3, "ready_component_count": 1},
        "deep_architecture_tasks": [{"task_id": "retort-architecture-codebase-graph", "priority": "P0"}],
        "component_index": {"codebase_graph": {"source_count": 3, "gate_pass_rate": 1.0, "architecture_depth_score": 90, "ready_for_deep_refactor": True}},
    }

    plan = build_core_refactor_plan(memory, project_root=tmp_path)

    assert plan["gate"]["passed"] is True
    assert plan["tasks"][0]["component"] == "codebase_graph"
    assert "retort_engine/codebase_graph.py" in plan["tasks"][0]["modules"]
    assert plan["tasks"][0]["code_graph_hotspot_score"] >= 0


def test_core_refactor_plan_uses_code_graph_hotspots_to_order_equal_priority_tasks(tmp_path: Path) -> None:
    for rel in [
        "retort_engine/codebase_graph.py",
        "retort_engine/service.py",
        "retort_engine/cli.py",
        "retort_engine/review_pipeline.py",
        "retort_engine/pr_review.py",
        "tests/test_codebase_graph.py",
        "tests/test_contracts_feedback.py",
        "tests/test_review_pipeline.py",
        "tests/test_pr_review.py",
    ]:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# ok\n", encoding="utf-8")
    (tmp_path / "retort_engine" / "codebase_graph.py").write_text(
        "\n".join(
            [
                "def a(): return 1",
                "def b(): return a()",
                "def c(): return a() + b()",
                "def d(): return a() + b() + c()",
                "def e(): return a() + b() + c() + d()",
            ]
        ),
        encoding="utf-8",
    )
    memory = {
        "summary": {"source_count": 3, "ready_component_count": 2},
        "deep_architecture_tasks": [
            {"task_id": "retort-architecture-review-pipeline", "priority": "P0"},
            {"task_id": "retort-architecture-codebase-graph", "priority": "P0"},
        ],
        "component_index": {
            "review_pipeline": {"source_count": 3, "gate_pass_rate": 1.0, "architecture_depth_score": 90, "ready_for_deep_refactor": True},
            "codebase_graph": {"source_count": 3, "gate_pass_rate": 1.0, "architecture_depth_score": 90, "ready_for_deep_refactor": True},
        },
    }

    plan = build_core_refactor_plan(memory, project_root=tmp_path)

    assert plan["tasks"][0]["component"] == "codebase_graph"
    assert plan["tasks"][0]["code_graph_hotspot_score"] > 0
    assert plan["summary"]["code_graph_hotspot_task_count"] >= 1


def test_write_core_refactor_plan_persists_gate(tmp_path: Path) -> None:
    path = tmp_path / "docs" / "retort_core_refactor_plan.json"
    plan = {"summary": {"task_count": 1}, "gate": {"passed": True}, "tasks": [{"component": "review_pipeline"}]}

    write_core_refactor_plan(path, plan)

    assert json.loads(path.read_text(encoding="utf-8"))["gate"]["passed"] is True
