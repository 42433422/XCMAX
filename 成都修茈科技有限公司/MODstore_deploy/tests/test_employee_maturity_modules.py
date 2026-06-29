from __future__ import annotations

import json
from datetime import datetime, timezone


def test_task_classifier_detects_bug_and_handoff_hint():
    from modstore_server.employee_task_classifier import classify_task

    out = classify_task("线上服务报错, 请转给运维同事处理")

    assert out["category"] in {"bug", "ops"}
    assert out["confidence"] > 0
    assert out["should_handoff"] is True
    assert out["matched_keywords"]


def test_path_guard_flags_out_of_scope_and_forbidden_files():
    from modstore_server.employee_path_guard import check_path_guard

    out = check_path_guard(
        employee_id="qa-runner",
        config={
            "workspace_policy": {
                "scope_globs": ["src/**"],
                "forbidden_globs": ["*.secret"],
            }
        },
        result={
            "outputs": [
                {
                    "handler": "writer",
                    "files_changed": ["src/app.py", "docs/readme.md", "prod.secret"],
                }
            ]
        },
    )

    assert out["checked"] is True
    assert out["ok"] is False
    reasons = {v["reason"] for v in out["violations"]}
    assert "out_of_scope" in reasons
    assert "matches_forbidden" in reasons


def test_handoff_keeps_orchestrator_compatibility_api():
    from modstore_server.employee_handoff import (
        HandoffDirective,
        build_followup_subtasks,
        extract_handoff_directives,
    )

    outcome = {
        "ok": True,
        "employee_id": "source",
        "result": {
            "handoff": {
                "handoff_to": "target",
                "task_brief": "continue work",
                "input_data": {"x": 1},
                "reason": "needs owner",
                "priority": 2,
            }
        },
    }

    directives = extract_handoff_directives(outcome, fallback_brief="fallback")
    assert directives == [
        HandoffDirective(
            to_employee_id="target",
            task_brief="continue work",
            input_data={"x": 1},
            reason="needs owner",
            priority=2,
        )
    ]

    visited = {"source"}
    followups = build_followup_subtasks(
        [outcome],
        visited=visited,
        depth=0,
        fallback_brief="fallback",
    )

    assert len(followups) == 1
    assert followups[0].employee_id == "target"
    assert followups[0].input_data["x"] == 1
    assert followups[0].input_data["_handoff_chain"][0]["from"] == "source"
    assert "target" in visited


def test_verification_passes_for_existing_declared_file(tmp_path):
    from modstore_server.employee_verification import run_verification

    declared = tmp_path / "src" / "app.py"
    declared.parent.mkdir()
    declared.write_text("print('ok')\n", encoding="utf-8")
    reasoning = {
        "reasoning": json.dumps(
            {
                "status": "success",
                "summary": "Updated application entrypoint with a verified change.",
                "files_changed": ["src/app.py"],
            }
        )
    }
    result = {"outputs": [{"handler": "writer", "output": "done"}]}

    out = run_verification(
        employee_id="qa-runner",
        task="update file",
        reasoning=reasoning,
        result=result,
        config={},
        project_root=tmp_path,
    )

    assert out["passed"] is True
    assert out["failed_count"] == 0
    assert out["files_declared"] == ["src/app.py"]


def test_human_report_mentions_verification_handoff_and_classification():
    from modstore_server.employee_human_report import build_human_report

    report = build_human_report(
        employee_id="source",
        task="fix bug",
        reasoning={"reasoning": json.dumps({"summary": "Fixed the bug."})},
        result={
            "outputs": [{"handler": "writer", "ok": True, "output": "done"}],
            "path_guard": {
                "checked": True,
                "all_changed_files": ["src/app.py"],
                "violations": [],
            },
            "verification": {
                "checks": [{"name": "summary", "ok": True, "evidence": "ok"}],
                "ok_count": 1,
                "total_count": 1,
                "failed_count": 0,
                "passed": True,
                "summary": "all good",
            },
            "handoff": {
                "ok": True,
                "skipped": False,
                "from": "source",
                "to": "target",
                "thread_id": 7,
                "message_id": 8,
            },
        },
        duration_ms=12.3,
        llm_tokens=4,
        exec_status="success",
        perceived={
            "type": "text",
            "normalized_input": {
                "_task_classification": {
                    "category": "bug",
                    "confidence": 0.8,
                    "reason": "matched bug",
                    "should_handoff": False,
                }
            },
        },
        memory={},
    )

    assert "任务分类" in report
    assert "程序化验证" in report
    assert "任务转交" in report
    assert "@target" in report


def test_scorecard_human_text_handles_empty_window(monkeypatch):
    import modstore_server.employee_scorecard as scorecard

    monkeypatch.setattr(
        scorecard,
        "get_employee_scorecard",
        lambda employee_id, days=7: {
            "ok": True,
            "employee_id": employee_id,
            "window_days": days,
            "total_tasks": 0,
        },
    )

    assert "0 任务" in scorecard.build_human_friendly_scorecard_text("worker", days=3)


class _MetricRow:
    id = 1
    employee_id = "worker"
    task = "fix bug"
    status = "failed"
    duration_ms = 123
    llm_tokens = 45
    failure_kind = "handler_failed"
    error_preview = "boom"
    created_at = datetime.now(timezone.utc)


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def all(self):
        return list(self._rows)


class _FakeMetricSession:
    def __init__(self, rows):
        self._rows = rows

    def query(self, *args, **kwargs):
        return _FakeQuery(self._rows)


def test_perception_enricher_reads_recent_metric_rows():
    from modstore_server.employee_perception_enricher import _recent_runs_from_db

    rows = _recent_runs_from_db(_FakeMetricSession([_MetricRow()]), "worker")

    assert rows[0]["task"] == "fix bug"
    assert rows[0]["failure_kind"] == "handler_failed"


def test_self_evolution_signal_counts_recent_failures():
    from modstore_server.employee_self_evolution import check_evolution_signal

    out = check_evolution_signal(
        employee_id="worker",
        session=_FakeMetricSession([_MetricRow(), _MetricRow(), _MetricRow()]),
        min_failures=3,
    )

    assert out["needed"] is True
    assert out["fail_count"] == 3
    assert out["recent_failures"][0]["error_preview"] == "boom"
