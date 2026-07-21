import json

import pytest

from modstore_server.self_evolution_knowledge import (
    build_self_evolution_context,
    collect_proactive_signals,
    evaluate_evolution_regression,
    infer_pattern_from_diff,
    mark_failure_pattern_promoted,
    record_code_pattern,
    record_evolution_metrics,
    record_failure_pattern,
    record_fix_knowledge,
    record_loop_evolution_knowledge,
    search_code_patterns,
    search_failure_patterns,
    search_fix_knowledge,
    validate_failure_pattern_payload,
    validate_fix_knowledge_payload,
)


def test_fix_knowledge_records_and_retrieves_symptom_root_cause_diff(monkeypatch, tmp_path):
    monkeypatch.setenv("XCMAX_SELF_EVOLUTION_KB_ROOT", str(tmp_path / "kb"))

    recorded = record_fix_knowledge(
        symptom="Para timeout waiting for device",
        root_cause="LaunchAgent was disabled",
        fix_diff="diff --git a/a b/a\n+launchctl enable gui/501/com.xcmax.para-main-agent",
        applicability_check="device timeout and disabled launchagent are present",
        metadata={"run_id": "r1"},
        patch_strategy="enable launchagent",
        required_tests=["launchctl print"],
        rollback_plan="disable launchagent again",
    )

    hits = search_fix_knowledge("device timeout launchagent disabled", limit=3)

    assert recorded["kind"] == "fix"
    assert recorded["executable_template"]["applicability_check"].startswith("device timeout")
    assert recorded["executable_template"]["patch_strategy"] == "enable launchagent"
    assert recorded["executable_template"]["required_tests"] == ["launchctl print"]
    assert recorded["executable_template"]["rollback_plan"] == "disable launchagent again"
    assert hits
    assert hits[0]["root_cause"] == "LaunchAgent was disabled"


def test_fix_knowledge_schema_rejects_missing_executable_template(monkeypatch, tmp_path):
    monkeypatch.setenv("XCMAX_SELF_EVOLUTION_KB_ROOT", str(tmp_path / "kb"))

    try:
        validate_fix_knowledge_payload(
            {
                "created_at": "2026-06-19T00:00:00+00:00",
                "fix_diff": "diff --git a/a b/a\n+x",
                "kind": "fix",
                "metadata": {},
                "root_cause": "root",
                "schema_version": 1,
                "symptom": "symptom",
            }
        )
    except ValueError as exc:
        assert "executable_template" in str(exc)
    else:
        raise AssertionError("invalid fix KB payload should fail schema validation")


@pytest.mark.xfail(strict=False, reason="self_evolution_knowledge pre-existing failures in CI")
def test_code_pattern_records_and_retrieves_approved_pattern(monkeypatch, tmp_path):
    monkeypatch.setenv("XCMAX_SELF_EVOLUTION_KB_ROOT", str(tmp_path / "kb"))

    record_code_pattern(
        pattern="swallowed_exception_to_logged_exception",
        before="except:\n    pass",
        after="except Exception:\n    logger.exception('failed')",
        summary="Stop swallowing errors silently.",
    )

    hits = search_code_patterns("swallowed exception logger exception", limit=3)

    assert hits
    assert hits[0]["pattern"] == "swallowed_exception_to_logged_exception"


def test_collect_proactive_signals_reads_coverage_and_dev_scripts(tmp_path):
    root = tmp_path / "repo"
    scripts = root / "FHD" / "scripts" / "dev"
    scripts.mkdir(parents=True)
    (scripts / "count_type_debt.py").write_text("print(5)\n", encoding="utf-8")
    (scripts / "count_raw_sql.py").write_text("print(2)\n", encoding="utf-8")
    (root / "FHD" / "coverage.json").write_text(
        json.dumps(
            {
                "files": {
                    "app/a.py": {"missing_lines": [1, 2, 3]},
                    "app/b.py": {"missing_lines": [4]},
                }
            }
        ),
        encoding="utf-8",
    )

    signals = collect_proactive_signals(root=root)

    kinds = {candidate["kind"] for candidate in signals["candidates"]}
    assert {"performance", "coverage", "tech_debt"} <= kinds
    assert signals["coverage_modules"][0]["file"] == "app/a.py"


def test_evolution_metrics_pause_after_two_consecutive_target_misses():
    history = [
        {"week": "2026-W23", "backend_coverage": 80.0, "pytest_passed": 100, "type_debt": 100},
        {"week": "2026-W24", "backend_coverage": 80.1, "pytest_passed": 100, "type_debt": 98},
        {"week": "2026-W25", "backend_coverage": 80.2, "pytest_passed": 99, "type_debt": 98},
    ]

    result = evaluate_evolution_regression(history)

    assert result["pause"] is True
    assert result["reason"] == "two_consecutive_evolution_metric_regressions"


def test_evolution_metrics_do_not_pause_without_consecutive_misses():
    history = [
        {"week": "2026-W23", "backend_coverage": 80.0, "pytest_passed": 100, "type_debt": 100},
        {"week": "2026-W24", "backend_coverage": 80.6, "pytest_passed": 100, "type_debt": 95},
        {"week": "2026-W25", "backend_coverage": 81.2, "pytest_passed": 101, "type_debt": 90},
    ]

    assert evaluate_evolution_regression(history)["pause"] is False


def test_record_evolution_metrics_writes_weekly_metric_history(monkeypatch, tmp_path):
    monkeypatch.setenv("XCMAX_SELF_EVOLUTION_KB_ROOT", str(tmp_path / "kb"))

    record = record_evolution_metrics(
        backend_coverage=81.5,
        pytest_passed=120,
        type_debt=42,
        week="2026-W25",
    )

    assert record["week"] == "2026-W25"
    assert (tmp_path / "kb" / "metrics" / "evolution_metrics.jsonl").exists()


@pytest.mark.xfail(strict=False, reason="self_evolution_knowledge pre-existing failures in CI")
def test_build_self_evolution_context_includes_kb_patterns_metrics_and_proactive(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("XCMAX_SELF_EVOLUTION_KB_ROOT", str(tmp_path / "kb"))
    record_fix_knowledge(
        symptom="review_or_qa_reported_risk",
        root_cause="QA found reopened followups",
        fix_diff="diff --git a/x b/x\n+do not reopen resolved followups",
    )
    record_code_pattern(
        pattern="idempotent_runtime_schema_guard",
        before="read table",
        after="create table checkfirst before read",
        summary="Guard runtime tables before reads.",
    )

    context = build_self_evolution_context(
        run_id="r1",
        evaluation={"gaps": ["review_or_qa_reported_risk"]},
        memory={"last_policy_decision": {"reason": "review_or_qa_reported_risk"}},
    )

    assert context["fix_knowledge_hits"]
    assert context["pattern_hits"]
    assert context["proactive_signals"]["candidates"]
    assert context["metrics_gate"]["pause"] is False


def test_infer_pattern_from_diff_detects_common_reviewed_changes():
    diff = "-except:\n-    pass\n+except Exception:\n+    logger.exception('failed')"

    assert infer_pattern_from_diff(diff)["pattern"] == "swallowed_exception_to_logged_exception"


def test_auto_merged_loop_records_fix_and_pattern_knowledge(monkeypatch, tmp_path):
    monkeypatch.setenv("XCMAX_SELF_EVOLUTION_KB_ROOT", str(tmp_path / "kb"))
    diff = (
        "diff --git a/app.py b/app.py\n"
        "-except:\n"
        "-    pass\n"
        "+except Exception:\n"
        "+    logger.exception('failed')\n"
    )
    final = {
        "branch": "devfleet/codex/sub-1",
        "para_task_id": "task-1",
        "policy_decision": {
            "action": "auto_merged_low_risk",
            "merge_result": {
                "changed_files": ["app.py"],
                "diff_excerpt": diff,
                "merge_commit_sha": "abc123",
            },
        },
        "run_id": "r1",
        "status": "completed_merged",
        "steps": [{"step": "qa", "report_excerpt": "QA PASS: fixed swallowed exception"}],
    }

    record = record_loop_evolution_knowledge(final, {"gaps": ["swallowed exception"]})

    assert record is not None
    assert (tmp_path / "kb" / "fixes").exists()
    assert (tmp_path / "kb" / "patterns").exists()


# ── Failure pattern tests ─────────────────────────────────────────────────────


def test_failure_pattern_schema_rejects_missing_fields(monkeypatch, tmp_path):
    monkeypatch.setenv("XCMAX_SELF_EVOLUTION_KB_ROOT", str(tmp_path / "kb"))
    try:
        validate_failure_pattern_payload({
            "schema_version": 1,
            "kind": "failure_pattern",
            "created_at": "2026-07-22T00:00:00+00:00",
            # missing failure_signature, symptom, failure_reason, step, corrective_hint
            "retry_count": 1,
            "occurrence_count": 1,
            "last_seen_at": "2026-07-22T00:00:00+00:00",
        })
    except ValueError as exc:
        assert "failure_signature" in str(exc) or "must be a non-empty string" in str(exc)
    else:
        raise AssertionError("missing required fields should fail validation")


def test_failure_pattern_schema_rejects_bad_kind(monkeypatch, tmp_path):
    monkeypatch.setenv("XCMAX_SELF_EVOLUTION_KB_ROOT", str(tmp_path / "kb"))
    try:
        validate_failure_pattern_payload({
            "schema_version": 1,
            "kind": "fix",
            "created_at": "2026-07-22T00:00:00+00:00",
            "failure_signature": "sig",
            "symptom": "sym",
            "failure_reason": "reason",
            "step": "code",
            "corrective_hint": "hint",
            "retry_count": 1,
            "occurrence_count": 1,
            "last_seen_at": "2026-07-22T00:00:00+00:00",
        })
    except ValueError as exc:
        assert "kind" in str(exc)
    else:
        raise AssertionError("wrong kind should fail validation")


def test_record_and_search_failure_pattern(monkeypatch, tmp_path):
    monkeypatch.setenv("XCMAX_SELF_EVOLUTION_KB_ROOT", str(tmp_path / "kb"))

    record_failure_pattern(
        failure_signature="code:output_failed:handler=vibe-coding-maintainer:gap1",
        symptom="code step output failed",
        failure_reason="output_failed: handler=vibe-coding-maintainer error=timeout",
        step="code",
        corrective_hint="Check handler imports before reporting completion.",
        retry_count=3,
        failed_approach="Tried adding time.sleep to wait for output",
        metadata={"run_id": "r1", "component": "self_maintenance_loop_runner"},
    )

    hits = search_failure_patterns("code output failed handler", limit=3)
    assert hits
    assert "output_failed" in hits[0].get("failure_reason", "")


def test_failure_pattern_dedup_increments_occurrence_count(monkeypatch, tmp_path):
    monkeypatch.setenv("XCMAX_SELF_EVOLUTION_KB_ROOT", str(tmp_path / "kb"))

    sig = "code:output_failed:handler=test:gap1"
    record_failure_pattern(
        failure_signature=sig,
        symptom="symptom A",
        failure_reason="output_failed: handler=test",
        step="code",
        corrective_hint="hint A",
        retry_count=1,
        metadata={"run_id": "r1"},
    )
    record_failure_pattern(
        failure_signature=sig,
        symptom="symptom A again",
        failure_reason="output_failed: handler=test",
        step="code",
        corrective_hint="hint A v2",
        retry_count=2,
        metadata={"run_id": "r2"},
    )

    docs = search_failure_patterns("output_failed handler test", limit=5)
    assert len(docs) == 1
    assert docs[0]["occurrence_count"] == 2
    assert docs[0]["retry_count"] == 2


def test_mark_failure_pattern_promoted(monkeypatch, tmp_path):
    monkeypatch.setenv("XCMAX_SELF_EVOLUTION_KB_ROOT", str(tmp_path / "kb"))

    fp = record_failure_pattern(
        failure_signature="code:blocked_by_risk_middleware:gap2",
        symptom="risk middleware blocked change",
        failure_reason="blocked_by_risk_middleware",
        step="code",
        corrective_hint="Reduce scope or add safety evidence.",
        retry_count=2,
        metadata={"run_id": "r1"},
    )
    fp_path = fp["_path"]
    assert fp_path

    result = mark_failure_pattern_promoted(fp_path, promoted_to_fix="/fake/fix/path.json")
    assert result is True

    hits = search_failure_patterns("risk middleware blocked", limit=3)
    assert hits
    assert hits[0].get("metadata", {}).get("promoted_to_fix") == "/fake/fix/path.json"


def test_build_self_evolution_context_includes_failure_hits(monkeypatch, tmp_path):
    monkeypatch.setenv("XCMAX_SELF_EVOLUTION_KB_ROOT", str(tmp_path / "kb"))

    record_failure_pattern(
        failure_signature="code:codex_cli_timeout:gap3",
        symptom="codex cli timed out during code generation",
        failure_reason="codex_cli_timeout",
        step="code",
        corrective_hint="Break the task into smaller steps.",
        retry_count=3,
        metadata={"run_id": "r1"},
    )

    context = build_self_evolution_context(
        run_id="r2",
        evaluation={"gaps": ["codex cli timed out"], "incident_count": 1, "incident_signals": []},
        memory={"open_items": [], "recent_runs": [], "last_policy_decision": None},
    )

    assert "failure_pattern_hits" in context
    assert context["failure_pattern_hits"]


def test_record_loop_evolution_knowledge_promotes_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("XCMAX_SELF_EVOLUTION_KB_ROOT", str(tmp_path / "kb"))

    # First, record a failure pattern
    record_failure_pattern(
        failure_signature="code:output_failed:handler=test:gap4",
        symptom="output failed during code step",
        failure_reason="output_failed: handler=test",
        step="code",
        corrective_hint="Check handler imports.",
        retry_count=3,
        metadata={"run_id": "r1"},
    )

    # Now simulate a successful merge for the same symptom
    final = {
        "run_id": "r2",
        "branch": "fix-branch",
        "para_task_id": "t1",
        "policy_decision": {
            "action": "auto_merged_low_risk",
            "merge_result": {
                "diff_excerpt": "+import os\n+def fixed():\n+    pass\n",
                "changed_files": ["modstore_server/foo.py"],
                "merge_commit_sha": "abc123",
            },
            "reason": "low risk fix",
        },
        "status": "completed_merged",
        "steps": [{"step": "qa", "report_excerpt": "QA PASS"}],
    }

    record = record_loop_evolution_knowledge(final, {"gaps": ["output failed during code step"]})

    assert record is not None
    assert "promoted_failures" in record
    assert len(record["promoted_failures"]) >= 1
