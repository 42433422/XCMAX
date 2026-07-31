from __future__ import annotations

from pathlib import Path

import pytest

from retort_engine.metric_search import (
    EvalSpec,
    MetricSearchConfig,
    MetricTreeSearchImprover,
    SolutionNode,
    SolutionTree,
    parse_metric_from_output,
    run_metric_search,
)
from retort_engine.models import ProjectAssessment, Score


def test_parse_metric_from_output() -> None:
    spec = EvalSpec(metric_name="resolved_rate", eval_command="echo ok")
    assert parse_metric_from_output("resolved_rate: 0.75\n", spec) == 0.75
    assert parse_metric_from_output("no metric here", spec) is None


def test_solution_tree_best_first_higher_is_better() -> None:
    tree = SolutionTree("score", higher_is_better=True)
    tree.add(
        SolutionNode("root", None, "scored", "score", metric_value=0.5, created_from="r")
    )
    tree.add(
        SolutionNode("a", "root", "scored", "score", metric_value=0.8, created_from="a")
    )
    tree.add(
        SolutionNode("b", "root", "scored", "score", metric_value=0.6, created_from="b")
    )
    assert tree.best_node() is not None
    assert tree.best_node().node_id == "a"
    assert tree.select_expand_parent().node_id == "a"


def test_solution_tree_lower_is_better() -> None:
    tree = SolutionTree("latency", higher_is_better=False)
    tree.add(
        SolutionNode("root", None, "scored", "latency", metric_value=10.0, created_from="r")
    )
    tree.add(
        SolutionNode("a", "root", "scored", "latency", metric_value=4.0, created_from="a")
    )
    tree.add(
        SolutionNode("b", "root", "scored", "latency", metric_value=7.0, created_from="b")
    )
    assert tree.best_node().node_id == "a"


def test_run_metric_search_synthetic_tree_and_budget(
    tmp_path: Path,
) -> None:
    scores = {"n": 0}

    def expand(parent: SolutionNode, child_index: int) -> list[dict]:
        scores["n"] += 1
        # Better children from better parents; inject metric to skip shell eval.
        base = float(parent.metric_value or 0.0)
        return [
            {
                "patch_summary": f"from {parent.node_id} #{child_index}",
                "files_touched": ["retort_engine/metric_search.py"],
                "metric_value": base + 0.1 * child_index + 0.01 * scores["n"],
                "created_from": f"synth:{parent.node_id}:{child_index}",
            }
        ]

    def fake_runner(command: list[str], **kwargs: object) -> dict:
        # Root scoring path
        return {
            "command": command,
            "returncode": 0,
            "timed_out": False,
            "stdout": "resolved_rate: 0.40\n",
            "stderr": "",
        }

    report = run_metric_search(
        MetricSearchConfig(
            project=tmp_path,
            eval_spec=EvalSpec(
                metric_name="resolved_rate",
                eval_command="echo resolved_rate: 0.40",
            ),
            max_nodes=5,
            beam=2,
            expand_fn=expand,
            command_runner=fake_runner,
            run_id="testsynth",
        )
    )
    assert report["status"] == "ok"
    assert report["nodes_evaluated"] == 5
    assert report["scored_count"] >= 3
    assert report["best_score"] is not None
    assert float(report["best_score"]) > 0.40
    tree_path = Path(report["tree_path"])
    assert tree_path.is_file()
    assert (tmp_path / ".retort" / "metric_search" / "testsynth" / "report.json").is_file()


def test_run_metric_search_stops_at_max_nodes(tmp_path: Path) -> None:
    def expand(parent: SolutionNode, child_index: int) -> list[dict]:
        return [
            {
                "patch_summary": f"{parent.node_id}-{child_index}",
                "metric_value": 0.5 + 0.01 * child_index,
            }
        ]

    def fake_runner(command: list[str], **kwargs: object) -> dict:
        return {
            "command": command,
            "returncode": 0,
            "timed_out": False,
            "stdout": "m: 0.5\n",
            "stderr": "",
        }

    report = run_metric_search(
        MetricSearchConfig(
            project=tmp_path,
            eval_spec=EvalSpec(metric_name="m", eval_command="echo m: 0.5"),
            max_nodes=3,
            beam=2,
            expand_fn=expand,
            command_runner=fake_runner,
            run_id="budget",
        )
    )
    assert report["nodes_evaluated"] == 3
    assert report["stop_reason"] == "max_nodes"


def test_eval_parse_failure_marks_failed(tmp_path: Path) -> None:
    def expand(parent: SolutionNode, child_index: int) -> list[dict]:
        return [{"patch_summary": "x", "files_touched": []}]

    def fake_runner(command: list[str], **kwargs: object) -> dict:
        return {
            "command": command,
            "returncode": 0,
            "timed_out": False,
            "stdout": "nope\n",
            "stderr": "",
        }

    report = run_metric_search(
        MetricSearchConfig(
            project=tmp_path,
            eval_spec=EvalSpec(metric_name="resolved_rate", eval_command="echo nope"),
            max_nodes=3,
            beam=1,
            expand_fn=expand,
            command_runner=fake_runner,
            run_id="failparse",
        )
    )
    assert report["status"] == "failed"
    assert report["best_node_id"] == ""


def test_metric_tree_search_improver_updates_state(tmp_path: Path) -> None:
    def expand(parent: SolutionNode, child_index: int) -> list[dict]:
        return [
            {
                "patch_summary": "improv",
                "metric_value": 0.9,
                "files_touched": ["a.py"],
            }
        ]

    def fake_runner(command: list[str], **kwargs: object) -> dict:
        return {
            "command": command,
            "returncode": 0,
            "timed_out": False,
            "stdout": "resolved_rate: 0.5\n",
            "stderr": "",
        }

    improver = MetricTreeSearchImprover(
        project=tmp_path,
        eval_spec=EvalSpec(
            metric_name="resolved_rate", eval_command="echo resolved_rate: 0.5"
        ),
        max_nodes=3,
        beam=1,
        expand_fn=expand,
        command_runner=fake_runner,
    )
    state = improver.improve(
        {},
        ProjectAssessment("p", (Score("x", 50.0, "r"),), "t"),
        (),
        1,
    )
    assert "retort_metric_search" in state
    assert state["retort_last_metric"]["value"] == 0.9


def test_eval_spec_requires_fields() -> None:
    with pytest.raises(ValueError):
        EvalSpec(metric_name="", eval_command="echo 1")
    with pytest.raises(ValueError):
        EvalSpec(metric_name="m", eval_command="")
