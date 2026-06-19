import json

from modstore_server.self_evolution_knowledge import (
    build_self_evolution_context,
    collect_proactive_signals,
    evaluate_evolution_regression,
    infer_pattern_from_diff,
    record_code_pattern,
    record_evolution_metrics,
    record_fix_knowledge,
    record_loop_evolution_knowledge,
    search_code_patterns,
    search_fix_knowledge,
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


def test_build_self_evolution_context_includes_kb_patterns_metrics_and_proactive(monkeypatch, tmp_path):
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
