from __future__ import annotations

from pathlib import Path

from retort_engine.absorption_state import closed_loop_proof, public_absorption_state, save_absorption_state
from retort_engine.core import RetortService
from retort_engine.quality_metrics import is_generated_absorption_file, test_code_health as code_health
from retort_engine.quality_policy import TEST_TO_SOURCE_HEALTHY_RATIO, apply_default_llm_policy, test_source_ratio_status as ratio_status


def test_default_llm_policy_enables_dispatch_without_requiring_scores() -> None:
    payload = apply_default_llm_policy({"project": "retort"})

    assert payload["use_llm"] is True
    assert payload["require_deep_review"] is False
    assert payload["llm_default_policy"] == "enabled_by_default"
    assert payload["wait_llm_sec"] > 0


def test_default_llm_policy_allows_explicit_disable() -> None:
    payload = apply_default_llm_policy({"project": "retort", "no_llm": True})

    assert payload["use_llm"] is False
    assert payload["require_deep_review"] is False
    assert payload["llm_default_policy"] == "explicitly_disabled"


def test_default_llm_policy_require_scores_promotes_deep_review() -> None:
    payload = apply_default_llm_policy({"project": "retort"}, require_scores=True)

    assert payload["use_llm"] is True
    assert payload["require_deep_review"] is True


def test_source_ratio_status_thresholds() -> None:
    assert ratio_status(TEST_TO_SOURCE_HEALTHY_RATIO) == "healthy"
    assert ratio_status(TEST_TO_SOURCE_HEALTHY_RATIO * 0.75) == "watch"
    assert ratio_status(TEST_TO_SOURCE_HEALTHY_RATIO * 0.25) == "low"
    assert ratio_status(None) == "unknown"


def test_quality_metrics_counts_behavior_code_and_excludes_generated(tmp_path: Path) -> None:
    root = tmp_path / "project"
    source = root / "retort_engine" / "feature.py"
    test = root / "tests" / "test_feature.py"
    generated = root / "docs" / "retort_external_review_report.json"
    source.parent.mkdir(parents=True)
    test.parent.mkdir(parents=True)
    generated.parent.mkdir(parents=True)
    source.write_text("\n".join(f"value_{index} = {index}" for index in range(10)), encoding="utf-8")
    test.write_text("\n".join(f"assert {index} == {index}" for index in range(5)), encoding="utf-8")
    generated.write_text("{}", encoding="utf-8")

    health = code_health(root)

    assert is_generated_absorption_file("docs/retort_external_review_report.json")
    assert health["source_line_count"] == 10
    assert health["test_line_count"] == 5
    assert health["test_to_source_ratio"] == 0.5
    assert health["test_to_source_ratio_status"] == "healthy"


def test_absorption_state_module_public_proof(tmp_path: Path) -> None:
    root = tmp_path / "project"
    save_absorption_state(
        root,
        {
            "active": False,
            "status": "closed_loop_verified",
            "source": "https://github.com/example/project",
            "closed_loop_proof": {
                "branch_diff_verified": True,
                "employee_execution_verified": True,
                "post_absorption_tests_passed": True,
                "merge_verified": True,
                "external_advantage_reassessed": True,
                "evidence": ["merge_commit=abc123"],
            },
        },
    )

    public = public_absorption_state(root)
    proof = closed_loop_proof(root)

    assert public["status"] == "closed_loop_verified"
    assert proof["verified"] is True
    assert proof["missing"] == []
    assert proof["evidence"] == ["merge_commit=abc123"]


def test_retort_service_default_assess_dispatches_llm(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "own"
    project.mkdir()
    (project / "README.md").write_text("# Own\n", encoding="utf-8")
    calls: list[dict[str, object]] = []

    def fake_request(**kwargs: object) -> dict[str, object]:
        calls.append(dict(kwargs))
        return {"provider": "paibi", "enabled": True, "status": "accepted", "dispatch": {"status": "accepted", "task_id": "task-default"}}

    def fake_wait(task_id: str, *, timeout_sec: float, interval_sec: float = 5.0) -> dict[str, object]:
        return {"provider": "paibi", "task_id": task_id, "status": "running"}

    monkeypatch.setattr("retort_engine.core.request_paibi_llm_review", fake_request)
    monkeypatch.setattr("retort_engine.core.wait_for_paibi_llm_review", fake_wait)

    result = RetortService().assess({"project": str(project)})

    assert calls
    assert result["llm_review"]["dispatch"]["task_id"] == "task-default"
    assert result["metadata"]["score_source"] == "paibi_llm_pending"


def test_frontend_exposes_dense_ops_dashboard() -> None:
    root = Path(__file__).resolve().parents[1] / "retort_engine" / "frontend"
    index = (root / "index.html").read_text(encoding="utf-8")
    app = (root / "app.js").read_text(encoding="utf-8")
    styles = (root / "styles.css").read_text(encoding="utf-8")

    for element_id in ("opsDashboard", "opsLlm", "opsGates", "opsProof", "opsRatio", "opsBranch"):
        assert f'id="{element_id}"' in index
    assert "function renderOpsDashboard" in app
    assert "latest_test_to_source_ratio_status" in app
    assert ".ops-dashboard" in styles
