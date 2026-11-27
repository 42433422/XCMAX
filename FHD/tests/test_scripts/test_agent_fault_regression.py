"""Negative controls for WG10 evidence, not simulated Agent acceptance."""

import json
from xml.etree import ElementTree

import pytest

from scripts.dev import run_agent_fault_regression as runner
from tests.test_scripts.test_task_benchmark_evidence import holdout as holdout


@pytest.fixture
def matrix(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "CASES", {"J01": ("tests/test_fault.py",)})
    junit = tmp_path / "faults.xml"
    collection = tmp_path / "collected.json"
    collection.write_text(
        json.dumps(
            {
                "nodes": [
                    "tests/test_fault.py::test_resume[timeout]",
                    "tests/test_fault.py::test_resume[disconnect]",
                ],
                "deselected": 0,
            }
        )
    )
    root = ElementTree.Element("testsuite")
    for name in ("test_resume[timeout]", "test_resume[disconnect]"):
        ElementTree.SubElement(root, "testcase", classname="tests.test_fault", name=name)
    ElementTree.ElementTree(root).write(junit)
    return junit, collection


def test_complete_fault_matrix_is_only_engineering_evidence(matrix):
    groups = runner.summarize_faults(*matrix)
    assert groups["J01"] == {"status": "PASS", "tests": 2, "failed": 0, "skipped": 0, "missing": []}
    assert "J10" not in groups


@pytest.mark.parametrize(
    "tag,status", [("skipped", "BLOCKED"), ("failure", "FAIL"), ("error", "FAIL")]
)
def test_failed_skipped_or_xfailed_case_never_passes(matrix, tag, status):
    junit, collection = matrix
    tree = ElementTree.parse(junit)
    ElementTree.SubElement(tree.getroot()[0], tag, type="pytest.xfail")
    tree.write(junit)
    assert runner.summarize_faults(junit, collection)["J01"]["status"] == status


@pytest.mark.parametrize(
    "change", ["missing_parameter", "duplicate_result", "deselected", "empty_collection"]
)
def test_incomplete_matrix_cannot_pass_because_one_case_from_a_file_passed(matrix, change):
    junit, collection = matrix
    tree = ElementTree.parse(junit)
    if change == "missing_parameter":
        tree.getroot().remove(tree.getroot()[0])
    elif change == "duplicate_result":
        tree.getroot().append(tree.getroot()[0])
    else:
        collected = json.loads(collection.read_text())
        if change == "deselected":
            collected["deselected"] = 1
        else:
            collected["nodes"] = []
        collection.write_text(json.dumps(collected))
    tree.write(junit)
    with pytest.raises(ValueError, match="matrix"):
        runner.summarize_faults(junit, collection)


def test_deleted_required_historical_scenario_blocks_its_group(matrix, monkeypatch):
    monkeypatch.setattr(runner, "CASES", {"J09": ("tests/test_fault.py::test_parent_wait",)})
    group = runner.summarize_faults(*matrix)["J09"]
    assert group["status"] == "BLOCKED" and group["missing"]


@pytest.mark.parametrize(
    "change", [{"source_sha": "b" * 40}, {"responses": 0}, {"mode": "observe"}, {"success": False}]
)
def test_j10_reuses_original_verifier_and_rejects_nonacceptance(holdout, change):
    directory, write = holdout
    write(**{"mode": "gate", **change})
    with pytest.raises(ValueError):
        runner.verify_real_model(directory, "a" * 40)


def test_j10_cannot_replace_the_13_tasks_with_one_passing_task(holdout):
    directory, write = holdout
    write(mode="gate")
    with pytest.raises(ValueError, match="13x3"):
        runner.verify_real_model(directory, "a" * 40)


def test_j10_cannot_certify_a_new_head_after_faults_completed(tmp_path, monkeypatch):
    from scripts.dev import verify_task_benchmark_evidence

    # A verifier can correctly validate B after another worker moves HEAD.
    # Its evidence must still be rejected for the fault run captured at A.
    monkeypatch.setattr(
        verify_task_benchmark_evidence,
        "write_task_evidence",
        lambda *a, **k: {
            "status": "VERIFIED",
            "gate_passed": True,
            "execution_mode": "model_workflow",
            "source_sha": "b" * 40,
            "evidence": {"total_tasks": 13, "trials": 3},
        },
    )
    with pytest.raises(ValueError, match="same-source"):
        runner.verify_real_model(tmp_path, "a" * 40)


def test_selectors_do_not_repeat_file_and_specific_node():
    selected = runner.selectors()
    assert len(selected) == len(set(selected))
    assert all("::" not in item or item.split("::")[0] not in selected for item in selected)
