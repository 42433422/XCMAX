from __future__ import annotations

import json
from pathlib import Path

from retort_engine.evolution_map import build_evolution_map


def test_evolution_map_combines_graph_proof_and_refactor_priority(tmp_path: Path) -> None:
    project = tmp_path / "project"
    package = project / "retort_engine"
    docs = project / "docs"
    runs = project / ".retort" / "real_absorption_runs"
    package.mkdir(parents=True)
    docs.mkdir()
    runs.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "codebase_graph.py").write_text(
        "def target():\n    return 1\n\ndef caller():\n    return target()\n",
        encoding="utf-8",
    )
    (project / "tests").mkdir()
    (project / "tests" / "test_codebase_graph.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (docs / "retort_architecture_memory.json").write_text(
        json.dumps(
            {
                "summary": {"source_count": 3, "ready_component_count": 1},
                "deep_architecture_tasks": [{"task_id": "retort-architecture-codebase-graph", "priority": "P0"}],
                "component_index": {
                    "codebase_graph": {
                        "source_count": 3,
                        "gate_pass_rate": 1.0,
                        "architecture_depth_score": 90,
                        "ready_for_deep_refactor": True,
                        "code_graph_proof_count": 2,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (runs / "run.json").write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "source": "https://github.com/example/codegraph",
                "status": "applied",
                "pre_absorption_focus": {"status": "ready", "own_focus_files": ["retort_engine/codebase_graph.py"], "external_focus_files": ["src/graph.py"]},
                "code_graph_proof": {"passed": True, "changed_focus_files": ["retort_engine/codebase_graph.py"], "summary": {"changed_focus_file_count": 1}},
            }
        ),
        encoding="utf-8",
    )

    result = build_evolution_map(project)

    assert result["status"] == "ready"
    assert result["code_graph"]["summary"]["node_count"] >= 2
    assert result["latest_absorption"]["code_graph_proof"]["passed"] is True
    assert result["latest_absorption"]["pre_absorption_focus"]["own_focus_files"] == ["retort_engine/codebase_graph.py"]
    assert result["core_refactor_plan"]["tasks"][0]["component"] == "codebase_graph"
    assert result["core_refactor_plan"]["tasks"][0]["code_graph_proof_count"] == 2


def test_evolution_map_does_not_treat_closed_loop_smoke_as_per_run_proof(tmp_path: Path) -> None:
    project = tmp_path / "project"
    package = project / "retort_engine"
    runs = project / ".retort" / "real_absorption_runs"
    package.mkdir(parents=True)
    runs.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "core.py").write_text("def core():\n    return 1\n", encoding="utf-8")
    (project / ".retort" / "absorption_state.json").write_text(
        json.dumps({"closed_loop_proof": {"evidence": ["codebase_graph_smoke=ready_1_files_1_nodes_0_edges"]}}),
        encoding="utf-8",
    )
    (runs / "run.json").write_text(json.dumps({"run_id": "run-1", "status": "applied", "source": "source"}), encoding="utf-8")

    result = build_evolution_map(project)

    proof = result["latest_absorption"]["code_graph_proof"]
    assert proof["passed"] is False
    assert proof["status"] == "missing_per_run_code_graph_proof"
    assert proof["evidence"]["style"] == "missing_per_run_code_graph_proof"
    assert proof["summary"]["graph_smoke"] == "codebase_graph_smoke=ready_1_files_1_nodes_0_edges"
