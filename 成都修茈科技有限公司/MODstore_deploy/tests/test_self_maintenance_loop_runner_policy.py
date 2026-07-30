import json
import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from modstore_server import self_maintenance_loop_runner as loop_runner
from modstore_server.autonomous_risk_gate import (
    _historical_rollback_rate as _historical_rollback_rate_v3,
)
from modstore_server.self_maintenance_loop_runner import (
    _PARA_GUEST_AUTH_CACHE,
    KB_SCHEMA_FAILED_LABEL,
    KB_SCHEMA_FAILED_STATUS,
    KB_SCHEMA_RETRY_MAX,
    NEEDS_HUMAN_LABEL,
    _assess_branch_auto_merge_policy,
    _base_para_input,
    _code_task_text,
    _employee_result_ok,
    _existing_kb_schema_retry_item,
    _extract_failure_reason,
    _find_delivery_validation,
    _find_pr_number_for_branch,
    _focused_test_command,
    _gh_pr_add_label,
    _guest_auth_headers,
    _has_high_risk_report,
    _historical_rollback_rate,
    _is_accepted_para_wait_timeout,
    _is_transient_employee_dispatch_failure,
    _load_loop_memory,
    _matches_focused_test_command,
    _qa_task_text,
    _reconcile_requested_merge_feedback,
    _reconcile_retort_scope_remediations,
    _reject_and_retry_kb_schema_failure,
    _resume_dispatch_context,
    _resume_review_qa_candidate,
    _resume_steps,
    _review_task_text,
    _self_maintenance_actor_user_id,
    _structured_report_gate,
    _update_loop_memory,
    clean_baseline_path,
    close_loop_memory_items,
    ensure_clean_baseline,
    loop_memory_path,
)
from modstore_server.self_maintenance_para_merge_remediation import (
    classify_para_merge_review_detail,
)
from modstore_server.self_maintenance_quality_gate import (
    matches_black_check_command,
    matches_isort_check_command,
    matches_source_governance_command,
    quality_check_failure,
)
from modstore_server.self_maintenance_remediation_lineage import (
    normalize_automated_remediation_reason,
    remediation_lineage_fields,
    resume_candidate_from_context,
)
from modstore_server.self_maintenance_remediation_prompts import (
    para_merge_conflict_continues_on_rejected_branch,
)

QUALITY_CHECKS_JSON = (
    '"quality_checks":{'
    '"black":{"command":"python3 -m black --check modman/ modstore_server/ tests/",'
    '"exit_code":0,"status":"passed"},'
    '"isort":{"command":"python3 -m isort --check-only --diff modman/ modstore_server/ tests/",'
    '"exit_code":0,"status":"passed"},'
    '"source_governance":{"command":"python3 scripts/dev/source_governance.py --top 10",'
    '"exit_code":0,"status":"passed"}},'
)


def test_scheduler_selected_remediation_is_resolved_exactly() -> None:
    memory = {
        "open_items": [
            {
                "kind": "failed_steps",
                "run_id": "newer-general-run",
                "branch": "devfleet/cursor/newer",
                "para_task_id": "newer-task",
                "steps": ["review"],
            },
            {
                "kind": "automated_remediation",
                "run_id": "incident-run",
                "branch": "devfleet/cursor/incident",
                "task_id": "incident-task",
                "reason": "structured_qa_verdict_not_pass",
            },
        ]
    }
    context = {
        "branch": "devfleet/cursor/incident",
        "origin_run_id": "incident-run",
        "origin_triggered_by": "incident_event",
        "reason": "structured_qa_verdict_not_pass",
        "run_id": "incident-run",
        "task_id": "incident-task",
    }

    assert resume_candidate_from_context(memory, context) == {
        "branch": "devfleet/cursor/incident",
        "continue_existing_code_task": True,
        "failed_run_id": "incident-run",
        "failed_steps": ["code"],
        "origin_run_id": "incident-run",
        "origin_triggered_by": "incident_event",
        "para_task_id": "incident-task",
        "reason": "resume_automated_remediation_candidate",
    }


def test_resume_candidate_from_context_normalizes_legacy_target_ref_hold() -> None:
    branch = "devfleet/cursor/sub-1-legacy-target-ref"
    memory = {
        "last_policy_decision": {
            "reason": "structured_qa_verdict_not_pass",
            "structured_gate": {
                "qa": {
                    "blocking_findings": [
                        f"target_branch_unavailable: refs/remotes/origin/{branch} cannot be resolved"
                    ],
                    "target_branch_available": False,
                    "verdict": "FAIL",
                },
                "reason": "structured_qa_verdict_not_pass",
            },
        },
        "open_items": [
            {
                "branch": branch,
                "kind": "automated_remediation",
                "reason": "structured_qa_verdict_not_pass",
                "run_id": "r-legacy-target-ref",
                "task_id": "task-legacy-target-ref",
            }
        ],
    }
    context = {
        "branch": branch,
        "reason": "structured_qa_verdict_not_pass",
        "run_id": "r-legacy-target-ref",
        "task_id": "task-legacy-target-ref",
    }

    assert resume_candidate_from_context(memory, context) == {
        "branch": branch,
        "failed_run_id": "r-legacy-target-ref",
        "failed_steps": ["qa"],
        "para_task_id": "task-legacy-target-ref",
        "reason": "resume_automated_remediation_candidate",
    }


def test_normalize_automated_remediation_reason_maps_legacy_target_ref() -> None:
    branch = "devfleet/cursor/sub-1"
    memory = {
        "last_policy_decision": {
            "reason": "structured_qa_verdict_not_pass",
            "structured_gate": {
                "qa": {
                    "blocking_findings": [f"target_branch_unavailable: origin/{branch}"],
                    "target_branch_available": False,
                }
            },
        }
    }
    item = {"branch": branch, "reason": "structured_qa_verdict_not_pass"}

    assert (
        normalize_automated_remediation_reason(memory, item)
        == "structured_qa_target_branch_unavailable"
    )


def test_remediation_lineage_emits_scorecard_visible_event() -> None:
    assert remediation_lineage_fields(
        {
            "origin_reason": "nginx error",
            "origin_run_id": "incident-run",
            "origin_triggered_by": "incident_event",
            "run_id": "parent-run",
        }
    ) == {
        "event": "incident_remediation",
        "origin_reason": "nginx error",
        "origin_run_id": "incident-run",
        "origin_triggered_by": "incident_event",
        "parent_run_id": "parent-run",
    }
    assert (
        remediation_lineage_fields(
            {
                "origin_run_id": "evolution-run",
                "origin_triggered_by": "proactive_signal",
                "run_id": "parent-run",
            }
        )["event"]
        == "proactive_evolution_remediation"
    )


def _stats(line_changes=12, binary_files=None):
    return {
        "additions": line_changes,
        "binary_files": binary_files or [],
        "deletions": 0,
        "files": {},
        "line_changes": line_changes,
    }


def test_self_maintenance_heartbeat_records_only_gate_liveness(monkeypatch):
    appended = []
    monkeypatch.setattr(
        loop_runner,
        "should_run_self_maintenance_loop",
        lambda **kwargs: {
            "should_run": False,
            "reason": "cooldown",
            "runtime_provenance": {"ok": True, "detail": "not projected"},
            "evolution_metrics_gate": {"pause": False},
        },
    )
    monkeypatch.setattr(loop_runner, "_append_ledger", appended.append)

    receipt = loop_runner.record_self_maintenance_heartbeat(triggered_by="test")

    assert receipt["phase"] == "heartbeat"
    assert receipt["status"] == "heartbeat_idle"
    assert receipt["gate"] == {
        "should_run": False,
        "reason": "cooldown",
        "runtime_provenance_ok": True,
        "evolution_metrics_paused": False,
    }
    assert receipt["read_only"] is True
    assert receipt["side_effects"] == []
    assert appended == [receipt]
    assert "detail" not in receipt["gate"]


def test_remote_merge_request_runs_only_after_structured_gate_and_ssot(monkeypatch):
    monkeypatch.setenv("MODSTORE_PARA_REPO_URL", "https://github.com/example/repo.git")
    monkeypatch.setenv("MODSTORE_PARA_BRANCH", "main")
    monkeypatch.setenv("MODSTORE_PARA_API_BASE", "http://127.0.0.1:3001")
    monkeypatch.setenv("MODSTORE_AUTO_MERGE_ALLOW_REMOTE", "1")
    monkeypatch.setattr(
        loop_runner,
        "_structured_report_gate",
        lambda steps: {"ok": True, "reason": "structured_reports_passed"},
    )
    risk_calls = []
    monkeypatch.setattr(
        "modstore_server.autonomy_guard_delegate.evaluate_risk",
        lambda action, **kwargs: (
            risk_calls.append((action, kwargs))
            or SimpleNamespace(allowed=True, to_dict=lambda: {"decision": "allow"})
        ),
    )
    merge_calls = []
    monkeypatch.setattr(
        loop_runner,
        "_request_para_task_merge",
        lambda **kwargs: merge_calls.append(kwargs) or {"ok": True},
    )
    heads = {"main": "b" * 40, "devfleet/codex/sub-1": "a" * 40}
    monkeypatch.setattr(loop_runner, "_remote_branch_head", lambda _repo, branch: heads[branch])
    ledger_rows = []
    governance_rows = []
    monkeypatch.setattr(loop_runner, "_append_ledger", ledger_rows.append)
    monkeypatch.setattr(loop_runner, "_append_governance_audit", governance_rows.append)

    result = loop_runner._auto_merge_low_risk_branch(
        run_id="remote-risk-gate",
        task_id="task-remote",
        branch="devfleet/codex/sub-1",
        steps=[{"step": "review"}, {"step": "qa"}],
    )

    assert result["ok"] is True
    assert result["merge_requested"] is True
    assert result["branch_head_sha"] == "a" * 40
    assert risk_calls[0][0] == "self_maintenance_l1_merge"
    assert risk_calls[0][1]["source"] == "self_maintenance_loop.remote_merge_request"
    assert merge_calls == [{"api_base": "http://127.0.0.1:3001", "task_id": "task-remote"}]
    assert ledger_rows[0]["event"] == "merge_requested"
    assert ledger_rows[0]["run_id"] == "remote-risk-gate"
    assert governance_rows[0]["kind"] == "merge_requested"


def test_remote_merge_request_is_not_emitted_when_ssot_blocks(monkeypatch):
    monkeypatch.setenv("MODSTORE_PARA_REPO_URL", "https://github.com/example/repo.git")
    monkeypatch.setenv("MODSTORE_PARA_BRANCH", "main")
    monkeypatch.setenv("MODSTORE_PARA_API_BASE", "http://127.0.0.1:3001")
    monkeypatch.setenv("MODSTORE_AUTO_MERGE_ALLOW_REMOTE", "1")
    monkeypatch.setattr(loop_runner, "_structured_report_gate", lambda steps: {"ok": True})
    heads = {"main": "b" * 40, "devfleet/codex/sub-1": "a" * 40}
    monkeypatch.setattr(loop_runner, "_remote_branch_head", lambda _repo, branch: heads[branch])
    monkeypatch.setattr(
        "modstore_server.autonomy_guard_delegate.evaluate_risk",
        lambda *args, **kwargs: SimpleNamespace(
            allowed=False,
            to_dict=lambda: {"decision": "blocked"},
        ),
    )
    monkeypatch.setattr(
        loop_runner,
        "_request_para_task_merge",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("merge request bypassed SSOT")),
    )

    result = loop_runner._auto_merge_low_risk_branch(
        run_id="remote-risk-block",
        task_id="task-remote",
        branch="devfleet/codex/sub-1",
        steps=[],
    )

    assert result["ok"] is False
    assert result["reason"] == "autonomy_guard_blocked"


def test_remote_merge_request_defers_unreachable_head_to_para_worker(monkeypatch):
    monkeypatch.setenv("MODSTORE_PARA_REPO_URL", "https://github.com/example/repo.git")
    monkeypatch.setenv("MODSTORE_PARA_BRANCH", "main")
    monkeypatch.setenv("MODSTORE_PARA_API_BASE", "http://127.0.0.1:3001")
    monkeypatch.setenv("MODSTORE_AUTO_MERGE_ALLOW_REMOTE", "1")
    monkeypatch.setattr(loop_runner, "_structured_report_gate", lambda steps: {"ok": True})
    monkeypatch.setattr(loop_runner, "_remote_branch_head", lambda _repo, _branch: None)
    monkeypatch.setattr(
        "modstore_server.autonomy_guard_delegate.evaluate_risk",
        lambda *args, **kwargs: SimpleNamespace(
            allowed=True,
            to_dict=lambda: {"decision": "allow"},
        ),
    )
    merge_calls = []
    monkeypatch.setattr(
        loop_runner,
        "_request_para_task_merge",
        lambda **kwargs: merge_calls.append(kwargs) or {"ok": True},
    )
    ledger_rows = []
    monkeypatch.setattr(loop_runner, "_append_ledger", ledger_rows.append)
    monkeypatch.setattr(loop_runner, "_append_governance_audit", lambda _row: None)

    result = loop_runner._auto_merge_low_risk_branch(
        run_id="remote-missing-head",
        task_id="task-remote",
        branch="devfleet/codex/sub-1",
        steps=[],
    )

    assert result["ok"] is True
    assert result["merge_requested"] is True
    assert result["branch_head_sha"] == ""
    assert result["head_verification"] == "delegated_to_para_merge_worker"
    assert merge_calls == [{"api_base": "http://127.0.0.1:3001", "task_id": "task-remote"}]
    assert ledger_rows[0]["head_verification"] == "delegated_to_para_merge_worker"


def test_local_auto_merge_cleans_ephemeral_workspace_on_return(monkeypatch, tmp_path):
    runtime_dir = tmp_path / "runtime"
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(runtime_dir))
    monkeypatch.setenv("MODSTORE_PARA_REPO_URL", "file:///tmp/repo.git")
    monkeypatch.setenv("MODSTORE_PARA_BRANCH", "main")
    monkeypatch.setenv("MODSTORE_PARA_API_BASE", "http://127.0.0.1:3001")

    def no_changes(**kwargs):
        workspace = kwargs["workspace"]
        workspace.mkdir(parents=True)
        (workspace / "clone-marker").write_text("created", encoding="utf-8")
        return []

    monkeypatch.setattr(loop_runner, "_changed_files_for_branch", no_changes)

    result = loop_runner._auto_merge_low_risk_branch(
        run_id="cleanup-return",
        task_id="task-local",
        branch="devfleet/codex/sub-1",
        steps=[],
    )

    assert result["reason"] == "branch_not_on_remote_or_empty"
    assert not (runtime_dir / loop_runner.DEFAULT_MERGE_WORKSPACE_ROOT / "cleanup-return").exists()


def test_local_auto_merge_cleans_ephemeral_workspace_on_exception(monkeypatch, tmp_path):
    runtime_dir = tmp_path / "runtime"
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(runtime_dir))
    monkeypatch.setenv("MODSTORE_PARA_REPO_URL", "file:///tmp/repo.git")
    monkeypatch.setenv("MODSTORE_PARA_BRANCH", "main")
    monkeypatch.setenv("MODSTORE_PARA_API_BASE", "http://127.0.0.1:3001")

    def failed_clone(**kwargs):
        workspace = kwargs["workspace"]
        workspace.mkdir(parents=True)
        (workspace / "partial-clone").write_text("created", encoding="utf-8")
        raise RuntimeError("clone failed")

    monkeypatch.setattr(loop_runner, "_changed_files_for_branch", failed_clone)

    try:
        loop_runner._auto_merge_low_risk_branch(
            run_id="cleanup-exception",
            task_id="task-local",
            branch="devfleet/codex/sub-1",
            steps=[],
        )
    except RuntimeError as exc:
        assert str(exc) == "clone failed"
    else:
        raise AssertionError("expected clone failure")

    assert not (
        runtime_dir / loop_runner.DEFAULT_MERGE_WORKSPACE_ROOT / "cleanup-exception"
    ).exists()


def test_early_kb_validation_cleans_ephemeral_workspace(monkeypatch, tmp_path):
    runtime_dir = tmp_path / "runtime"
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(runtime_dir))
    monkeypatch.setenv("MODSTORE_PARA_REPO_URL", "file:///tmp/repo.git")
    monkeypatch.setenv("MODSTORE_PARA_BRANCH", "main")

    def no_changes(**kwargs):
        workspace = kwargs["workspace"]
        workspace.mkdir(parents=True)
        (workspace / "clone-marker").write_text("created", encoding="utf-8")
        return []

    monkeypatch.setattr(loop_runner, "_changed_files_for_branch", no_changes)

    result = loop_runner._early_kb_validation_for_branch(
        run_id="cleanup-kb",
        branch="devfleet/codex/sub-1",
    )

    assert result["reason"] == "early_kb_validation_no_changed_files"
    assert not (
        runtime_dir / loop_runner.DEFAULT_MERGE_WORKSPACE_ROOT / "cleanup-kb-kb-early"
    ).exists()


def test_merge_workspace_cleanup_refuses_outside_runtime_root(monkeypatch, tmp_path):
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path / "runtime"))
    outside = tmp_path / "outside"
    outside.mkdir()

    assert loop_runner._cleanup_merge_workspace(outside) is False
    assert outside.exists()


def test_changed_files_prefers_configured_para_transport(monkeypatch, tmp_path):
    workspace = tmp_path / "runtime" / "merge"
    para_transport = "git@github-xcagi-modstore:example/XCMAX.git"
    public_origin = "https://github.com/example/XCMAX.git"
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("MODSTORE_PARA_BARE_REPO", para_transport)
    clone_commands = []

    def fake_run_cmd(args, cwd=None, timeout=120):
        if args[:3] == ["git", "clone", "--no-tags"]:
            clone_commands.append(args)
            workspace.mkdir(parents=True)
            return ""
        if "diff" in args and "--name-only" in args:
            return "FHD/app/example.py"
        return ""

    monkeypatch.setattr(loop_runner, "_run_cmd", fake_run_cmd)
    monkeypatch.setattr(
        loop_runner.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    files = loop_runner._changed_files_for_branch(
        repo_url=public_origin,
        base_branch="main",
        branch="devfleet/codex/sub-1",
        workspace=workspace,
    )

    assert files == ["FHD/app/example.py"]
    assert [item[-2] for item in clone_commands] == [para_transport]
    assert "--filter=blob:none" in clone_commands[0]
    assert "--no-checkout" in clone_commands[0]


def test_changed_files_falls_back_after_configured_transport_clone_failure(monkeypatch, tmp_path):
    runtime_dir = tmp_path / "runtime"
    workspace = runtime_dir / loop_runner.DEFAULT_MERGE_WORKSPACE_ROOT / "fallback"
    para_transport = "git@github-xcagi-modstore:example/XCMAX.git"
    public_origin = "https://github.com/example/XCMAX.git"
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(runtime_dir))
    monkeypatch.setenv("MODSTORE_PARA_BARE_REPO", para_transport)
    clone_commands = []

    def fake_run_cmd(args, cwd=None, timeout=120):
        if args[:3] == ["git", "clone", "--no-tags"]:
            clone_commands.append(args)
            workspace.mkdir(parents=True, exist_ok=True)
            if args[-2] == para_transport:
                (workspace / "partial").write_text("partial", encoding="utf-8")
                raise RuntimeError("ssh unavailable")
            assert not (workspace / "partial").exists()
            return ""
        if "diff" in args and "--name-only" in args:
            return "FHD/app/fallback.py"
        return ""

    monkeypatch.setattr(loop_runner, "_run_cmd", fake_run_cmd)
    monkeypatch.setattr(
        loop_runner.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    files = loop_runner._changed_files_for_branch(
        repo_url=public_origin,
        base_branch="main",
        branch="devfleet/codex/sub-1",
        workspace=workspace,
    )

    assert files == ["FHD/app/fallback.py"]
    assert [item[-2] for item in clone_commands] == [para_transport, public_origin]


def test_dynamic_low_risk_policy_allows_self_maintenance_code_and_tests(monkeypatch):
    monkeypatch.delenv("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_SCOPE_GLOBS", raising=False)
    monkeypatch.delenv("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_FORBIDDEN_GLOBS", raising=False)
    # 关闭 v2/v3 评分门禁，让流程走到 dynamic_low_risk 策略（本测试验证 dynamic_low_risk 逻辑）
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_SCORING_GATE_V2", "0")
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_SCORING_GATE_V3", "0")
    files = [
        "成都修茈科技有限公司/MODstore_deploy/modstore_server/self_maintenance_policy.py",
        "成都修茈科技有限公司/MODstore_deploy/tests/test_self_maintenance_policy.py",
    ]

    result = _assess_branch_auto_merge_policy(files, _stats())

    assert result["ok"] is True
    assert result["reason"] == "dynamic_low_risk_policy_passed"


def test_historical_rollback_rate_ignores_rollback_paths_without_execution() -> None:
    memory = {
        "recent_runs": [
            {
                "status": "completed_merged",
                "policy_decision": {
                    "action": "auto_merged_low_risk",
                    "merge_result": {
                        "autonomy_risk_decision": {"rollback_path": "revert_merge_commit"},
                        "reason": "merged_low_risk_branch",
                    },
                },
            },
            {
                "status": "completed_rolled_back",
                "policy_decision": {
                    "action": "auto_merged_low_risk",
                    "merge_result": {"reason": "merged_low_risk_branch"},
                },
            },
        ]
    }

    assert _historical_rollback_rate(memory) == 0.5
    assert _historical_rollback_rate_v3(memory) == 0.5


def test_safety_score_v2_allows_small_independently_verified_change_to_reach_90():
    steps = [
        {
            "step": "review",
            "report_excerpt": (
                f"{loop_runner.STRUCTURED_REVIEW_MARKER}: "
                '{"max_severity":"none","blocking_findings":[],"risk_class":"low",'
                '"target_branch_available":true,"tested_commands":[],'
                '"dimensions":{'
                '"security":{"status":"pass","findings":[]},'
                '"business_logic":{"status":"pass","findings":[]},'
                '"performance":{"status":"pass","findings":[]}}}'
            ),
        },
        {
            "step": "qa",
            "report_excerpt": (
                f"{loop_runner.STRUCTURED_QA_MARKER}: "
                '{"verdict":"PASS","blocking_findings":[],"tested_commands":['
                '{"command":"pytest focused.py -q","exit_code":0,"status":"passed"}],'
                '"target_branch_available":true,"test_delta":{"baseline_id":"base",'
                '"new_failures":[],"new_errors":[]},"changed_files_scope":"low",'
                '"risk_class":"low"}'
            ),
        },
    ]
    files = [
        "成都修茈科技有限公司/MODstore_deploy/modstore_server/self_maintenance_policy.py",
        "成都修茈科技有限公司/MODstore_deploy/tests/test_self_maintenance_policy.py",
    ]

    result = loop_runner._auto_merge_safety_score_v2(
        files,
        _stats(line_changes=60),
        diff_excerpt="narrow scheduling guard with focused regression coverage",
        memory={"recent_runs": []},
        steps=steps,
    )

    assert result["score"] >= 90
    assert result["risk_class"] == "low"
    assert result["components"]["semantic_llm_penalty"] == 0
    assert result["components"]["rollback_penalty"] == 2


def test_diff_semantic_scan_ignores_context_and_kb_explanation():
    diff = """diff --git a/成都修茈科技有限公司/MODstore_deploy/modstore_server/cr_narrow_ci.py b/成都修茈科技有限公司/MODstore_deploy/modstore_server/cr_narrow_ci.py
--- a/成都修茈科技有限公司/MODstore_deploy/modstore_server/cr_narrow_ci.py
+++ b/成都修茈科技有限公司/MODstore_deploy/modstore_server/cr_narrow_ci.py
@@ -188,3 +188,3 @@
     proc = subprocess.run(
-        [\"python3\", \"-m\", \"py_compile\", tmp_path],
+        [sys.executable, \"-m\", \"py_compile\", tmp_path],
diff --git a/FHD/XCAGI/kb/fixes/fix.json b/FHD/XCAGI/kb/fixes/fix.json
--- /dev/null
+++ b/FHD/XCAGI/kb/fixes/fix.json
@@ -0,0 +1 @@
+{\"root_cause\": \"subprocess used the wrong Python interpreter\"}
"""

    result = loop_runner._diff_semantic_penalty(diff)

    assert result["high_hits"] == []
    assert result["penalty"] == 0
    assert result["source"] == "diff_added_source_keyword_scan"


def test_diff_semantic_scan_still_flags_added_subprocess_call():
    diff = """diff --git a/worker.py b/worker.py
--- a/worker.py
+++ b/worker.py
@@ -1,0 +1 @@
+subprocess.run(command)
"""

    result = loop_runner._diff_semantic_penalty(diff)

    assert result["high_hits"] == ["subprocess"]
    assert result["penalty"] == 16


def test_diff_semantic_scan_ignores_risky_api_named_only_by_regression_test():
    diff = """diff --git a/tests/test_worker.py b/tests/test_worker.py
--- /dev/null
+++ b/tests/test_worker.py
@@ -0,0 +1,2 @@
+def test_subprocess_uses_current_interpreter():
+    assert worker.subprocess.run.called
"""

    result = loop_runner._diff_semantic_penalty(diff)

    assert result["high_hits"] == []
    assert result["penalty"] == 0


def test_validate_remediation_branch_delivery_requires_advanced_work_branch(
    monkeypatch,
):
    heads = {
        "candidate": "a" * 40,
        "work-unchanged": "a" * 40,
        "work-advanced": "b" * 40,
    }
    monkeypatch.setattr(loop_runner, "_remote_branch_head", lambda _repo, branch: heads.get(branch))
    monkeypatch.setenv("MODSTORE_PARA_REPO_URL", "file:///tmp/repo.git")

    unchanged = loop_runner._validate_remediation_branch_delivery(
        base_branch="candidate", delivered_branch="work-unchanged"
    )
    advanced = loop_runner._validate_remediation_branch_delivery(
        base_branch="candidate", delivered_branch="work-advanced"
    )

    assert unchanged["ok"] is False
    assert unchanged["reason"] == "remediation_branch_not_advanced"
    assert advanced["ok"] is True
    assert advanced["reason"] == "remediation_branch_advanced"


def test_dynamic_low_risk_policy_blocks_marker_only_when_memory_requires_executable_change():
    files = ["成都修茈科技有限公司/MODstore_deploy/modstore_server/self_maintenance_loop_status.py"]
    memory = {
        "open_items": [
            {
                "kind": "review_qa_failure",
                "reason": "marker-only status file is not executable evidence",
            }
        ]
    }

    result = _assess_branch_auto_merge_policy(files, _stats(), memory=memory)

    assert result["ok"] is False
    assert result["reason"] == "marker_only_diff_requires_executable_change"


def test_dynamic_low_risk_policy_blocks_forbidden_paths():
    files = [
        "成都修茈科技有限公司/MODstore_deploy/modstore_server/api/app_factory.py",
    ]

    result = _assess_branch_auto_merge_policy(files, _stats())

    assert result["ok"] is False
    assert result["reason"] == "changed_files_match_forbidden_globs"


def test_forbidden_paths_override_legacy_allowed_globs(monkeypatch):
    monkeypatch.setenv(
        "MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_GLOBS",
        "成都修茈科技有限公司/MODstore_deploy/modstore_server/api/app_factory.py",
    )
    files = [
        "成都修茈科技有限公司/MODstore_deploy/modstore_server/api/app_factory.py",
    ]

    result = _assess_branch_auto_merge_policy(files, _stats())

    assert result["ok"] is False
    assert result["reason"] == "changed_files_match_forbidden_globs"


def test_dynamic_low_risk_policy_blocks_name_only_numstat_mismatch():
    files = [
        "成都修茈科技有限公司/MODstore_deploy/modstore_server/self_maintenance_policy.py",
    ]
    diff_stats = {
        "binary_files": [],
        "changed_files": [
            "成都修茈科技有限公司/MODstore_deploy/modstore_server/self_maintenance_policy.py",
            "成都修茈科技有限公司/MODstore_deploy/modstore_server/api/app_factory.py",
        ],
        "files": {
            "成都修茈科技有限公司/MODstore_deploy/modstore_server/self_maintenance_policy.py": {
                "additions": 1,
                "deletions": 0,
            },
            "成都修茈科技有限公司/MODstore_deploy/modstore_server/api/app_factory.py": {
                "additions": 1,
                "deletions": 0,
            },
        },
        "line_changes": 2,
        "source": "git_diff_numstat",
    }

    result = _assess_branch_auto_merge_policy(files, diff_stats)

    assert result["ok"] is False
    assert result["reason"] == "changed_files_diff_stats_mismatch"


def test_dynamic_low_risk_policy_allows_project_context_followup_files(monkeypatch):
    monkeypatch.delenv("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_SCOPE_GLOBS", raising=False)
    monkeypatch.delenv("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_FORBIDDEN_GLOBS", raising=False)
    # 关闭 v2/v3 评分门禁 + 放宽 risk_score_v1 阈值，让流程走到 dynamic_low_risk 策略
    # （本测试验证 dynamic_low_risk 逻辑，不验证 risk_score 评分）
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_SCORING_GATE_V2", "0")
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_SCORING_GATE_V3", "0")
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_MAX_RISK_SCORE", "100")
    files = [
        "成都修茈科技有限公司/MODstore_deploy/modstore_server/cr_narrow_ci.py",
        "成都修茈科技有限公司/MODstore_deploy/modstore_server/models_project_context.py",
        "成都修茈科技有限公司/MODstore_deploy/tests/test_project_context_followups.py",
    ]

    result = _assess_branch_auto_merge_policy(files, _stats(line_changes=512))

    assert result["ok"] is True
    assert result["reason"] == "dynamic_low_risk_policy_passed"


def test_dynamic_low_risk_policy_allows_self_evolution_knowledge_files(monkeypatch):
    monkeypatch.delenv("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_SCOPE_GLOBS", raising=False)
    monkeypatch.delenv("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_FORBIDDEN_GLOBS", raising=False)
    # 关闭 v2/v3 评分门禁 + 放宽 risk_score_v1 阈值，让流程走到 dynamic_low_risk 策略
    # （本测试验证 dynamic_low_risk 逻辑，不验证 risk_score 评分）
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_SCORING_GATE_V2", "0")
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_SCORING_GATE_V3", "0")
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_MAX_RISK_SCORE", "100")
    files = [
        "成都修茈科技有限公司/MODstore_deploy/modstore_server/duty_workforce_learning.py",
        "成都修茈科技有限公司/MODstore_deploy/modstore_server/self_evolution_knowledge.py",
        "FHD/XCAGI/kb/fixes/2026-06-18-modstore-narrow-ci-pycache-prefix.md",
        "成都修茈科技有限公司/MODstore_deploy/tests/test_duty_workforce_learning.py",
        "成都修茈科技有限公司/MODstore_deploy/tests/test_self_evolution_knowledge.py",
    ]

    result = _assess_branch_auto_merge_policy(files, _stats(line_changes=580))

    assert result["ok"] is True
    assert result["reason"] == "dynamic_low_risk_policy_passed"


def test_dynamic_low_risk_policy_blocks_large_changes(monkeypatch):
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_MAX_LINES", "10")
    files = [
        "成都修茈科技有限公司/MODstore_deploy/modstore_server/self_maintenance_policy.py",
    ]

    result = _assess_branch_auto_merge_policy(files, _stats(line_changes=11))

    assert result["ok"] is False
    assert result["reason"] == "too_many_changed_lines_for_dynamic_auto_merge"


def test_transient_para_api_outbox_failure_is_retryable():
    result = {
        "result": {
            "outputs": [
                {
                    "error": "Para API 调用失败，已写入 outbox: [Errno 61] Connection refused",
                    "status": "para_api_failed_outboxed",
                }
            ]
        }
    }

    assert _is_transient_employee_dispatch_failure(result) is True


def test_report_only_cursor_tls_failure_is_retryable():
    error = (
        ("echoed report-only prompt without transport evidence " * 300)
        + "[e2e-agent] report-only 执行器失败: Cursor Agent 失败: "
        + "Client network socket disconnected before secure TLS connection was established"
    )
    result = {
        "result": {
            "outputs": [
                {
                    "error": error,
                    "ok": False,
                }
            ]
        }
    }

    assert _is_transient_employee_dispatch_failure(result) is True


def test_report_only_executor_failure_without_transport_detail_is_retryable():
    result = {
        "result": {
            "outputs": [
                {
                    "error": "[e2e-agent] report-only 执行器失败: Cursor Agent 失败: Command failed",
                    "handler": "para_delegate",
                    "ok": False,
                }
            ]
        }
    }

    assert _is_transient_employee_dispatch_failure(result) is True


def test_employee_dispatch_retries_report_only_cursor_tls_failure(monkeypatch):
    attempts = [
        {
            "result": {
                "outputs": [
                    {
                        "error": (
                            "[e2e-agent] report-only 执行器失败: Cursor Agent 失败: "
                            "Client network socket disconnected before secure TLS "
                            "connection was established"
                        ),
                        "ok": False,
                    }
                ]
            }
        },
        {"result": {"ok": True}},
    ]
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_STEP_RETRIES", "2")
    monkeypatch.setattr(loop_runner, "_wait_for_para_device_online", lambda: {"online": True})
    monkeypatch.setattr(loop_runner.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        loop_runner,
        "execute_employee_task",
        lambda *_args, **_kwargs: attempts.pop(0),
    )

    result = loop_runner._execute_employee_task_with_retries(
        "test-qa-runner",
        "report-only QA",
        {},
        user_id=0,
    )

    assert result["self_maintenance_retry_attempts"] == 2
    assert result["result"]["ok"] is True
    assert attempts == []


def test_business_failure_is_not_retryable():
    result = {"result": {"outputs": [{"error": "pytest failed: assertion error"}]}}

    assert _is_transient_employee_dispatch_failure(result) is False


def test_accepted_para_wait_timeout_is_not_a_code_delivery_failure():
    result = {
        "result": {
            "outputs": [
                {
                    "accepted": True,
                    "handler": "para_delegate",
                    "status": "para_task_timeout",
                }
            ]
        }
    }

    assert _is_accepted_para_wait_timeout(result) is True


def test_accepted_para_wait_timeout_detects_flat_and_nested_shapes():
    flat = {
        "accepted": True,
        "handler": "para_delegate",
        "status": "para_task_timeout",
        "error": "Para task task-flat 未在 1800s 内完成",
    }
    nested_status = {
        "result": {
            "outputs": [
                {
                    "accepted": "true",
                    "handler": "para_delegate",
                    "ok": False,
                    "para_result": {"status": "para_task_timeout", "task_id": "task-nested"},
                }
            ]
        }
    }
    not_accepted = {
        "result": {
            "outputs": [
                {
                    "accepted": False,
                    "handler": "para_delegate",
                    "status": "para_task_timeout",
                }
            ]
        }
    }
    wrong_handler = {
        "result": {
            "outputs": [
                {
                    "accepted": True,
                    "handler": "local_shell",
                    "status": "para_task_timeout",
                }
            ]
        }
    }

    assert _is_accepted_para_wait_timeout(flat) is True
    assert _is_accepted_para_wait_timeout(nested_status) is True
    assert _is_accepted_para_wait_timeout(not_accepted) is False
    assert _is_accepted_para_wait_timeout(wrong_handler) is False
    # Must not be treated as a redispatchable transient failure once fixed.
    assert _is_transient_employee_dispatch_failure(flat) is False
    assert _is_transient_employee_dispatch_failure(nested_status) is False


def test_base_para_input_default_wait_budget_covers_real_agent_runtime(monkeypatch):
    monkeypatch.delenv("MODSTORE_PARA_WAIT_TIMEOUT_SEC", raising=False)
    assert _base_para_input()["wait_timeout_sec"] == 1800

    monkeypatch.setenv("MODSTORE_PARA_WAIT_TIMEOUT_SEC", "2100")
    assert _base_para_input()["wait_timeout_sec"] == 2100


def test_guest_auth_headers_uses_injected_token(monkeypatch):
    monkeypatch.setenv("MODSTORE_PARA_AUTH_TOKEN", "local-token")

    headers = _guest_auth_headers("http://127.0.0.1:3001")

    assert headers == {"Authorization": "Bearer local-token"}


def test_guest_auth_headers_uses_persistent_cache(monkeypatch, tmp_path):
    cache_path = tmp_path / "para_auth.json"
    monkeypatch.delenv("MODSTORE_PARA_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("DEVFLEET_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("MODSTORE_PARA_AUTH_CACHE", str(cache_path))
    _PARA_GUEST_AUTH_CACHE.clear()
    cache_path.write_text(
        json.dumps(
            {
                "api_base": "http://127.0.0.1:3001",
                "expires_at": 4102444800,
                "token": "cached-token",
            }
        ),
        encoding="utf-8",
    )

    headers = _guest_auth_headers("http://127.0.0.1:3001/")

    assert headers == {"Authorization": "Bearer cached-token"}
    assert _PARA_GUEST_AUTH_CACHE["http://127.0.0.1:3001"][0] == "cached-token"


def test_guest_auth_headers_can_mint_local_guest_token(monkeypatch, tmp_path):
    cache_path = tmp_path / "para_auth.json"
    db_path = tmp_path / "devfleet.db"
    monkeypatch.delenv("MODSTORE_PARA_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("DEVFLEET_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("MODSTORE_PARA_AUTH_CACHE", str(cache_path))
    monkeypatch.setenv("MODSTORE_PARA_DB_FILE", str(db_path))
    monkeypatch.setenv("MODSTORE_PARA_JWT_SECRET", "test-secret")
    _PARA_GUEST_AUTH_CACHE.clear()
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("create table users (id text primary key, email text not null)")
        conn.execute(
            "insert into users (id, email) values (?, ?)",
            ("guest-id", "guest@devfleet.local"),
        )

    headers = _guest_auth_headers("http://127.0.0.1:3001")
    token = headers["Authorization"].replace("Bearer ", "", 1)
    cache = json.loads(cache_path.read_text(encoding="utf-8"))

    assert token.count(".") == 2
    assert cache["api_base"] == "http://127.0.0.1:3001"
    assert cache["token"] == token


def test_self_maintenance_actor_defaults_to_platform_identity(monkeypatch):
    # 默认无 env 覆盖时走平台身份 0：chat_dispatch_via_session 不再过个人
    # llm_calls 配额闸，避免历史「记到 owner 配额→额度耗尽→403 死循环」根因。
    monkeypatch.delenv("MODSTORE_SELF_MAINTENANCE_USER_ID", raising=False)

    assert _self_maintenance_actor_user_id() == 0


def test_self_maintenance_actor_honors_env_override(monkeypatch):
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_USER_ID", "7")

    assert _self_maintenance_actor_user_id() == 7


def test_self_maintenance_actor_falls_back_to_platform_on_bad_env(monkeypatch):
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_USER_ID", "not-an-int")

    assert _self_maintenance_actor_user_id() == 0


def test_employee_result_rejects_e2e_codex_timeout():
    result = {
        "result": {
            "ok": True,
            "status": "completed",
            "outputs": [
                {"message": "[e2e-agent] Codex CLI 失败: Codex CLI timeout after 600000ms"}
            ],
        }
    }

    assert _employee_result_ok(result) is False


def test_extract_failure_reason_picks_up_delivery_validation_failure():
    # delivery_validation 由 Para 远端返回，嵌在 result.result.outputs[].para_result
    # 等任意层级。模拟真实结构：change_delivery.ok=true（代码已交付）但验证命令失败。
    result = {
        "result": {
            "ok": False,
            "status": "failed",
            "outputs": [
                {
                    "handler": "para_delegate",
                    "para_result": {
                        "delivery_validation": {
                            "commands": [
                                {
                                    "command": "-m pytest tests/test_x.py",
                                    "exit_code": 1,
                                    "output_tail": "FAILED tests/test_x.py::test_safe_branch_name",
                                },
                                {"command": "-m py_compile main.py", "exit_code": 0},
                            ],
                        }
                    },
                }
            ],
        }
    }

    reason = _extract_failure_reason(result, {})

    assert "delivery_validation_failed" in reason
    assert "exit=1" in reason
    assert "pytest tests/test_x.py" in reason


def test_extract_failure_reason_falls_back_when_no_delivery_validation():
    # 无 delivery_validation 时走原有兜底逻辑，返回非空原因
    result = {"result": {"ok": False, "status": "completed"}}

    reason = _extract_failure_reason(result, {})

    assert reason and reason != "delivery_validation_failed"


def test_resume_review_qa_candidate_uses_failed_review_branch():
    memory = {
        "open_items": [
            {"kind": "failed_steps", "run_id": "r1", "steps": ["review"]},
        ],
        "recent_runs": [
            {
                "branch": "devfleet/codex/sub-1",
                "para_task_id": "task-1",
                "run_id": "r1",
                "status": "failed",
            }
        ],
    }

    result = _resume_review_qa_candidate(memory)

    assert result == {
        "branch": "devfleet/codex/sub-1",
        "failed_run_id": "r1",
        "failed_steps": ["review"],
        "para_task_id": "task-1",
        "reason": "resume_failed_review_or_qa",
    }


def test_resume_candidate_prefers_newer_same_task_code_hold_over_old_review_failure():
    memory = {
        "open_items": [
            {
                "branch": "devfleet/cursor/sub-1-quality",
                "kind": "failed_steps",
                "para_task_id": "task-quality",
                "retry_count": 1,
                "run_id": "run-old-review",
                "steps": ["review"],
            },
            {
                "branch": "devfleet/cursor/sub-1-quality",
                "kind": "automated_remediation",
                "reason": "structured_qa_black_not_passed",
                "run_id": "run-new-quality-hold",
                "task_id": "task-quality",
            },
        ],
        "recent_runs": [
            {
                "branch": "devfleet/cursor/sub-1-quality",
                "para_task_id": "task-quality",
                "run_id": "run-old-review",
                "status": "failed",
            }
        ],
    }

    result = _resume_review_qa_candidate(memory)

    assert result == {
        "branch": "devfleet/cursor/sub-1-quality",
        "continue_existing_code_task": True,
        "failed_run_id": "run-new-quality-hold",
        "failed_steps": ["code"],
        "para_task_id": "task-quality",
        "reason": "resume_automated_remediation_candidate",
    }


def test_resume_candidate_prefers_latest_code_hold_over_stale_paired_hold():
    memory = {
        "open_items": [
            {
                "branch": "devfleet/cursor/stale",
                "kind": "failed_steps",
                "para_task_id": "task-stale",
                "retry_count": 1,
                "run_id": "run-stale-review",
                "steps": ["review"],
            },
            {
                "branch": "devfleet/cursor/stale",
                "kind": "automated_remediation",
                "reason": "structured_qa_black_not_passed",
                "run_id": "run-stale-hold",
                "task_id": "task-stale",
            },
            {
                "branch": "devfleet/cursor/latest",
                "kind": "automated_remediation",
                "reason": "structured_review_blocking_findings",
                "run_id": "run-latest-hold",
                "task_id": "task-latest",
            },
        ],
        "recent_runs": [],
    }

    result = _resume_review_qa_candidate(memory)

    assert result == {
        "branch": "devfleet/cursor/latest",
        "failed_run_id": "run-latest-hold",
        "failed_steps": ["code"],
        "para_task_id": "task-latest",
        "reason": "resume_automated_remediation_candidate",
    }
    assert _resume_dispatch_context(result, _resume_steps(result)) == (None, None)


def test_resume_steps_rerun_failed_step_and_downstream_chain():
    assert _resume_steps(None) == {"code", "review", "qa"}
    assert _resume_steps({"failed_steps": ["code"]}) == {"code", "review", "qa"}
    assert _resume_steps({"failed_steps": ["review"]}) == {"review", "qa"}
    assert _resume_steps({"failed_steps": ["qa"]}) == {"qa"}
    assert _resume_steps({"failed_steps": []}) == set()


def test_resume_review_qa_candidate_uses_human_strategy_branch():
    memory = {
        "open_items": [
            {
                "branch": "devfleet/codex/sub-2",
                "kind": "human_strategy_approval",
                "reason": "changed_files_match_forbidden_globs",
                "run_id": "r2",
                "task_id": "task-2",
            }
        ],
        "recent_runs": [],
    }

    result = _resume_review_qa_candidate(memory)

    assert result == {
        "branch": "devfleet/codex/sub-2",
        "failed_run_id": "r2",
        "failed_steps": ["qa"],
        "para_task_id": "task-2",
        "reason": "resume_automated_remediation_candidate",
    }


def test_resume_review_qa_candidate_retries_nonportable_focused_command():
    memory = {
        "open_items": [
            {
                "branch": "devfleet/trae/sub-1",
                "kind": "human_strategy_approval",
                "reason": "structured_qa_focused_command_not_passed",
                "run_id": "r-platform",
                "task_id": "task-platform",
            }
        ],
        "recent_runs": [],
    }

    result = _resume_review_qa_candidate(memory)

    assert result == {
        "branch": "devfleet/trae/sub-1",
        "failed_run_id": "r-platform",
        "failed_steps": ["qa"],
        "para_task_id": "task-platform",
        "reason": "resume_automated_remediation_candidate",
    }


def test_resume_review_qa_candidate_retries_missing_target_ref_as_qa_only():
    memory = {
        "open_items": [
            {
                "branch": "devfleet/cursor/sub-1-target-ref",
                "kind": "automated_remediation",
                "reason": "structured_qa_target_branch_unavailable",
                "run_id": "r-target-ref",
                "task_id": "task-target-ref",
            }
        ],
        "recent_runs": [],
    }

    result = _resume_review_qa_candidate(memory)

    assert result == {
        "branch": "devfleet/cursor/sub-1-target-ref",
        "failed_run_id": "r-target-ref",
        "failed_steps": ["qa"],
        "para_task_id": "task-target-ref",
        "reason": "resume_automated_remediation_candidate",
    }


def test_resume_review_qa_candidate_retries_executor_outage_as_qa_only():
    memory = {
        "open_items": [
            {
                "branch": "devfleet/cursor/sub-1-executor-outage",
                "kind": "automated_remediation",
                "reason": "structured_qa_executor_unavailable",
                "run_id": "r-executor-outage",
                "task_id": "task-executor-outage",
            }
        ],
        "recent_runs": [],
    }

    result = _resume_review_qa_candidate(memory)

    assert result == {
        "branch": "devfleet/cursor/sub-1-executor-outage",
        "failed_run_id": "r-executor-outage",
        "failed_steps": ["qa"],
        "para_task_id": "task-executor-outage",
        "reason": "resume_automated_remediation_candidate",
    }


def test_resume_review_qa_candidate_recovers_legacy_target_ref_failure_as_qa_only():
    branch = "devfleet/cursor/sub-1-legacy-target-ref"
    memory = {
        "last_policy_decision": {
            "reason": "structured_qa_verdict_not_pass",
            "structured_gate": {
                "qa": {
                    "blocking_findings": [
                        f"target_branch_unavailable: refs/remotes/origin/{branch} cannot be resolved"
                    ],
                    "target_branch_available": False,
                    "verdict": "FAIL",
                },
                "reason": "structured_qa_verdict_not_pass",
            },
        },
        "open_items": [
            {
                "branch": branch,
                "kind": "automated_remediation",
                "reason": "structured_qa_verdict_not_pass",
                "run_id": "r-legacy-target-ref",
                "task_id": "task-legacy-target-ref",
            }
        ],
        "recent_runs": [],
    }

    result = _resume_review_qa_candidate(memory)

    assert result == {
        "branch": branch,
        "failed_run_id": "r-legacy-target-ref",
        "failed_steps": ["qa"],
        "para_task_id": "task-legacy-target-ref",
        "reason": "resume_automated_remediation_candidate",
    }


@pytest.mark.parametrize(
    ("hold_reason", "expected_steps", "expect_continue_code"),
    [
        ("missing_structured_qa_result", ["qa"], False),
        ("missing_structured_review_object", ["review"], False),
        ("invalid_max_severity", ["review"], False),
    ],
)
def test_resume_review_qa_candidate_retries_report_only_protocol_holds(
    hold_reason: str,
    expected_steps: list[str],
    expect_continue_code: bool,
):
    memory = {
        "open_items": [
            {
                "branch": "devfleet/codex/sub-1-protocol",
                "kind": "automated_remediation",
                "reason": hold_reason,
                "run_id": "r-protocol",
                "task_id": "task-protocol",
            }
        ],
        "recent_runs": [],
    }

    result = _resume_review_qa_candidate(memory)

    assert result is not None
    assert result["failed_steps"] == expected_steps
    assert result["para_task_id"] == "task-protocol"
    if expect_continue_code:
        assert result.get("continue_existing_code_task") is True
    else:
        assert "continue_existing_code_task" not in result
    assert _resume_steps(result) == set(expected_steps) | (
        {"qa"} if "review" in expected_steps else set()
    )


@pytest.mark.parametrize(
    "hold_reason",
    [
        "structured_qa_verdict_not_pass",
        "structured_qa_blocking_findings",
    ],
)
def test_resume_review_qa_candidate_retries_structured_qa_on_existing_branch(
    hold_reason: str,
):
    memory = {
        "open_items": [
            {
                "branch": "devfleet/codex/sub-1-structured",
                "kind": "automated_remediation",
                "reason": hold_reason,
                "run_id": "r-structured",
                "task_id": "task-structured",
            }
        ],
        "recent_runs": [],
    }

    result = _resume_review_qa_candidate(memory)

    assert result == {
        "branch": "devfleet/codex/sub-1-structured",
        "continue_existing_code_task": True,
        "failed_run_id": "r-structured",
        "failed_steps": ["code"],
        "para_task_id": "task-structured",
        "reason": "resume_automated_remediation_candidate",
    }
    assert _resume_steps(result) == {"code", "review", "qa"}
    assert _resume_dispatch_context(result, _resume_steps(result)) == (
        None,
        "devfleet/codex/sub-1-structured",
    )


def test_retort_scope_hold_is_reconciled_to_clean_base_code_remediation(monkeypatch):
    memory = {
        "last_policy_decision": {"action": "stop", "reason": "loop_not_completed"},
        "open_items": [
            {
                "branch": "devfleet/cursor/too-wide",
                "kind": "failed_steps",
                "para_task_id": "task-wide",
                "retry_count": 1,
                "run_id": "run-wide",
                "steps": ["review"],
            }
        ],
        "recent_runs": [],
    }
    monkeypatch.setattr(
        loop_runner,
        "_read_ledger",
        lambda limit: [
            {
                "branch": "devfleet/cursor/too-wide",
                "error": "retort_clarification_pending",
                "para_task_id": "task-wide",
                "phase": "complete",
                "retort_clarification": {
                    "changed_file_count": 13,
                    "clarification": {
                        "questions": [
                            {"reason": "elevated_risk_or_large_diff"},
                        ]
                    },
                },
                "run_id": "run-wide",
                "status": "failed",
            }
        ],
    )

    assert _reconcile_retort_scope_remediations(memory) == {
        "added": 1,
        "changed": True,
        "run_ids": ["run-wide"],
    }
    result = _resume_review_qa_candidate(memory)

    assert result == {
        "branch": "devfleet/cursor/too-wide",
        "failed_run_id": "run-wide",
        "failed_steps": ["code"],
        "para_task_id": "task-wide",
        "reason": "resume_automated_remediation_candidate",
        "remediation_feedback": (
            "Retort requested risk acceptance for 13 changed files; "
            "rebuild the smallest valid fix from the clean base."
        ),
        "remediation_reason": "retort_scope_too_large",
    }
    assert "continue_existing_code_task" not in result
    prompt = _code_task_text("run-next", {}, memory, result)
    assert "RETORT SCOPE REMEDIATION" in prompt
    assert "never continue, merge, rebase, or cherry-pick the rejected branch" in prompt
    assert "overrides the generic KB-writing instruction" in prompt
    assert '"max_changed_files": 6' in prompt
    assert '"max_changed_lines": 400' in prompt
    assert '"max_diff_chars": 12000' in prompt
    assert '"FHD/XCAGI/kb/"' in prompt


def test_retort_non_scope_question_is_not_auto_remediated(monkeypatch):
    memory = {"open_items": []}
    monkeypatch.setattr(
        loop_runner,
        "_read_ledger",
        lambda limit: [
            {
                "branch": "devfleet/cursor/ambiguous",
                "error": "retort_clarification_pending",
                "para_task_id": "task-ambiguous",
                "phase": "complete",
                "retort_clarification": {
                    "clarification": {
                        "questions": [{"reason": "missing_business_intent"}],
                    },
                },
                "run_id": "run-ambiguous",
                "status": "failed",
            }
        ],
    )

    assert _reconcile_retort_scope_remediations(memory) == {
        "added": 0,
        "changed": False,
        "run_ids": [],
    }
    assert memory["open_items"] == []


@pytest.mark.parametrize(
    "hold_reason",
    [
        "structured_review_blocking_findings",
        "structured_review_dimension_fail",
        "structured_review_high_severity",
    ],
)
def test_resume_candidate_rebuilds_structured_review_rejection_from_clean_base(
    hold_reason: str,
):
    memory = {
        "open_items": [
            {
                "branch": "devfleet/codex/old-veto",
                "kind": "automated_remediation",
                "reason": "para_ai_review_rejected",
                "review_feedback": "old finding",
                "run_id": "run-old",
                "task_id": "task-old",
            },
            {
                "branch": "devfleet/trae/current-review",
                "kind": "automated_remediation",
                "reason": hold_reason,
                "run_id": "run-current",
                "task_id": "task-current",
            },
        ],
        "recent_runs": [],
    }

    result = _resume_review_qa_candidate(memory)

    assert result == {
        "branch": "devfleet/trae/current-review",
        "failed_run_id": "run-current",
        "failed_steps": ["code"],
        "para_task_id": "task-current",
        "reason": "resume_automated_remediation_candidate",
    }
    assert _resume_dispatch_context(result, _resume_steps(result)) == (None, None)


def test_resume_review_qa_candidate_continues_score_remediation_on_existing_task():
    memory = {
        "open_items": [
            {
                "branch": "devfleet/codex/sub-1-score",
                "kind": "automated_remediation",
                "reason": "auto_merge_safety_score_v2_too_low",
                "run_id": "r-score",
                "task_id": "task-score",
            }
        ],
        "recent_runs": [],
    }

    result = _resume_review_qa_candidate(memory)

    assert result == {
        "branch": "devfleet/codex/sub-1-score",
        "continue_existing_code_task": True,
        "failed_run_id": "r-score",
        "failed_steps": ["code"],
        "para_task_id": "task-score",
        "reason": "resume_safety_score_remediation",
    }
    assert _resume_steps(result) == {"code", "review", "qa"}
    assert _resume_dispatch_context(result, _resume_steps(result)) == (
        None,
        "devfleet/codex/sub-1-score",
    )


def test_resume_dispatch_context_reuses_task_only_for_review_or_qa():
    candidate = {
        "branch": "devfleet/codex/sub-1-review",
        "failed_steps": ["review"],
        "para_task_id": "task-review",
    }

    assert _resume_dispatch_context(candidate, _resume_steps(candidate)) == (
        "task-review",
        "devfleet/codex/sub-1-review",
    )


def test_resume_dispatch_context_starts_failed_code_fresh_from_configured_base():
    candidate = {
        "branch": "devfleet/codex/sub-1-failed",
        "failed_steps": ["code"],
        "para_task_id": "task-failed",
    }

    assert _resume_dispatch_context(candidate, _resume_steps(candidate)) == (None, None)


def test_code_task_text_pins_selected_score_remediation_when_last_decision_was_overwritten():
    memory = {
        "last_policy_decision": {"reason": "low_risk_policy_passed"},
        "open_items": [
            {
                "branch": "devfleet/codex/sub-1-score",
                "kind": "automated_remediation",
                "reason": "auto_merge_safety_score_v2_too_low",
                "run_id": "r-score",
                "task_id": "task-score",
            }
        ],
        "recent_runs": [],
    }
    resume_candidate = _resume_review_qa_candidate(memory)

    text = _code_task_text("run-new", {}, memory, resume_candidate)

    assert "EXISTING BRANCH SCORE REMEDIATION" in text
    assert "`devfleet/codex/sub-1-score`" in text
    assert '"failed_run_id": "r-score"' in text
    assert "test-only follow-up commit is valid" in text


def test_resume_review_qa_candidate_stops_when_latest_policy_has_real_risk():
    memory = {
        "last_policy_decision": {
            "action": "await_human_strategy_approval",
            "reason": "review_or_qa_reported_risk",
        },
        "open_items": [
            {
                "branch": "devfleet/codex/sub-2",
                "kind": "human_strategy_approval",
                "reason": "changed_files_match_forbidden_globs",
                "run_id": "r2",
                "task_id": "task-2",
            }
        ],
        "recent_runs": [],
    }

    assert _resume_review_qa_candidate(memory) is None


def test_report_only_review_and_qa_prompt_pin_target_branch(monkeypatch):
    monkeypatch.setenv("MODSTORE_PARA_BRANCH", "feat/base")
    monkeypatch.setenv("MODSTORE_PARA_REPO_URL", "file:///tmp/repo.git")
    monkeypatch.setenv(
        "MODSTORE_SELF_MAINTENANCE_FOCUSED_TEST_COMMAND",
        "verified-python -m pytest focused.py -q",
    )

    review = _review_task_text("run-1", "devfleet/codex/sub-1", {})
    qa = _qa_task_text("run-1", "devfleet/codex/sub-1", {})

    assert "Target branch to inspect: `devfleet/codex/sub-1`" in review
    assert "Target branch to verify: `devfleet/codex/sub-1`" in qa
    assert "Do not inspect your own report-only task branch" in review
    assert "Do not inspect your own report-only task branch" in qa
    assert "bootstrap has already fetched" in review
    assert "bootstrap has already fetched" in qa
    assert "Do not run git fetch, clone" in review
    assert "Do not run git fetch, clone" in qa
    assert "Verify both refs with `git cat-file -e`" in review
    assert "Verify both refs with `git cat-file -e`" in qa
    assert "file:///tmp/repo.git" in qa
    assert "`verified-python -m pytest focused.py -q`" in qa
    assert "platform-equivalent local `python -m pytest` command" in qa
    assert "same focused test file" in qa
    assert "Materialize the COMPLETE target ref" in qa
    assert "do not archive only `成都修茈科技有限公司/MODstore_deploy`" in qa
    assert "sibling `FHD/` autonomy-guard SSOT" in qa
    assert "never report PASS with no successful focused tested_commands entry" in qa
    assert "Do not fail solely because the scheduler's absolute Python path" in qa
    assert (
        "python -m modstore_server.self_maintenance_diff_quality --tool black "
        "--base-ref origin/feat/base --target-ref origin/devfleet/codex/sub-1"
    ) in qa
    assert (
        "python -m modstore_server.self_maintenance_diff_quality --tool isort "
        "--base-ref origin/feat/base --target-ref origin/devfleet/codex/sub-1"
    ) in qa
    assert "python scripts/dev/source_governance.py --top 10" in qa
    assert '"quality_checks"' in qa

    code = _code_task_text("run-1", {}, {})
    assert "`verified-python -m pytest focused.py -q`" in code
    assert (
        "python -m modstore_server.self_maintenance_diff_quality --tool black "
        "--base-ref origin/feat/base --target-ref WORKTREE"
    ) in code
    assert (
        "python -m modstore_server.self_maintenance_diff_quality --tool isort "
        "--base-ref origin/feat/base --target-ref WORKTREE"
    ) in code
    assert "python scripts/dev/source_governance.py --top 10" in code
    assert "executable_template object" in code
    assert "validate_kb_payload" in code


def test_focused_test_command_prefers_explicit_command(monkeypatch):
    monkeypatch.setenv(
        "MODSTORE_SELF_MAINTENANCE_FOCUSED_TEST_COMMAND",
        "runtime-python -m pytest focused.py -q",
    )

    assert _focused_test_command() == "runtime-python -m pytest focused.py -q"


def test_high_risk_report_detects_standalone_qa_fail():
    steps = [
        {
            "step": "qa",
            "report_excerpt": (
                "FAIL\n\nBlocking QA findings:\nRecommendation: do not merge this target as-is."
            ),
        }
    ]

    assert _has_high_risk_report(steps) is True


def test_structured_report_gate_requires_qa_json_pass(monkeypatch):
    focused = "runtime-python -m pytest focused.py -q"
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_FOCUSED_TEST_COMMAND", focused)
    steps = [
        {
            "step": "review",
            "report_excerpt": (
                'SELF_MAINTENANCE_REVIEW_JSON: {"max_severity":"low",'
                '"blocking_findings":[],"risk_class":"low","target_branch_available":true,'
                '"tested_commands":[],"dimensions":{'
                '"security":{"status":"pass","findings":[]},'
                '"business_logic":{"status":"pass","findings":[]},'
                '"performance":{"status":"pass","findings":[]}}}'
            ),
        },
        {
            "step": "qa",
            "report_excerpt": (
                'SELF_MAINTENANCE_QA_JSON: {"verdict":"PASS","blocking_findings":[],'
                f'"tested_commands":[{{"command":"{focused}","exit_code":0,"status":"passed"}}],'
                f"{QUALITY_CHECKS_JSON}"
                '"target_branch_available":true,'
                '"test_delta":{"baseline_id":"b1","new_failures":[],"new_errors":[]},'
                '"changed_files_scope":"low","risk_class":"low"}'
            ),
        },
    ]

    assert _structured_report_gate(steps)["ok"] is True


def test_structured_report_gate_blocks_missing_or_failed_qa_json(monkeypatch):
    monkeypatch.setenv(
        "MODSTORE_SELF_MAINTENANCE_FOCUSED_TEST_COMMAND",
        "runtime-python -m pytest focused.py -q",
    )
    missing = [{"step": "qa", "report_excerpt": "PASS in prose only"}]
    failed = [
        {
            "step": "qa",
            "report_excerpt": (
                'SELF_MAINTENANCE_QA_JSON: {"verdict":"FAIL","blocking_findings":["x"],'
                '"tested_commands":[],"target_branch_available":true,'
                '"test_delta":{"new_failures":[],"new_errors":[]},'
                '"changed_files_scope":"low","risk_class":"high"}'
            ),
        }
    ]

    assert _structured_report_gate(missing)["reason"] == "missing_structured_qa_result"
    assert _structured_report_gate(failed)["reason"] == "structured_qa_verdict_not_pass"


def test_structured_report_gate_classifies_executor_outage_separately(monkeypatch):
    monkeypatch.setenv(
        "MODSTORE_SELF_MAINTENANCE_FOCUSED_TEST_COMMAND",
        "runtime-python -m pytest focused.py -q",
    )
    outage = [
        {
            "step": "qa",
            "report_excerpt": (
                'SELF_MAINTENANCE_QA_JSON: {"verdict":"FAIL",'
                '"blocking_findings":['
                '"QA worker shell execution backend unavailable; could not run focused pytest.",'
                '"Missing successful focused tested_commands entry.",'
                '"Diff review not executed due same backend failure."],'
                '"tested_commands":[{"command":"runtime-python -m pytest focused.py -q",'
                '"exit_code":1,"status":"failed"}],'
                '"target_branch_available":true,'
                '"test_delta":{"new_failures":["focused pytest not executed"],'
                '"new_errors":["shell execution backend unavailable; no observable exit codes"]},'
                '"changed_files_scope":"medium","risk_class":"high"}'
            ),
        }
    ]
    real_failure = [
        {
            "step": "qa",
            "report_excerpt": (
                'SELF_MAINTENANCE_QA_JSON: {"verdict":"FAIL",'
                '"blocking_findings":["focused pytest assertion failed"],'
                '"tested_commands":[{"command":"runtime-python -m pytest focused.py -q",'
                '"exit_code":1,"status":"failed"}],'
                '"target_branch_available":true,'
                '"test_delta":{"new_failures":["test_policy assertion failed"],'
                '"new_errors":[]},'
                '"changed_files_scope":"medium","risk_class":"high"}'
            ),
        }
    ]

    assert _structured_report_gate(outage)["reason"] == "structured_qa_executor_unavailable"
    assert _structured_report_gate(real_failure)["reason"] == "structured_qa_verdict_not_pass"


def test_structured_report_gate_prioritizes_missing_target_ref(monkeypatch):
    monkeypatch.setenv(
        "MODSTORE_SELF_MAINTENANCE_FOCUSED_TEST_COMMAND",
        "runtime-python -m pytest focused.py -q",
    )
    steps = [
        {
            "step": "qa",
            "report_excerpt": (
                'SELF_MAINTENANCE_QA_JSON: {"verdict":"FAIL",'
                '"blocking_findings":["target_branch_unavailable"],'
                '"tested_commands":[],"target_branch_available":false,'
                '"test_delta":{"new_failures":[],"new_errors":[]},'
                '"changed_files_scope":"high","risk_class":"high"}'
            ),
        }
    ]

    result = _structured_report_gate(steps)

    assert result["reason"] == "structured_qa_target_branch_unavailable"
    assert result["qa"]["target_branch_available"] is False


def test_structured_report_gate_blocks_failed_focused_command(monkeypatch):
    focused = "runtime-python -m pytest focused.py -q"
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_FOCUSED_TEST_COMMAND", focused)
    steps = [
        {
            "step": "qa",
            "report_excerpt": (
                'SELF_MAINTENANCE_QA_JSON: {"verdict":"PASS","blocking_findings":[],'
                f'"tested_commands":[{{"command":"{focused}","exit_code":2,"status":"failed"}}],'
                '"target_branch_available":true,'
                '"test_delta":{"baseline_id":"b1","new_failures":[],"new_errors":[]},'
                '"changed_files_scope":"low","risk_class":"low"}'
            ),
        }
    ]

    result = _structured_report_gate(steps)

    assert result["ok"] is False
    assert result["reason"] == "structured_qa_focused_command_not_passed"
    assert result["focused_command"] == focused


def test_structured_report_gate_accepts_platform_equivalent_focused_command(
    monkeypatch,
):
    focused = (
        "'/root/XCMAX/成都修茈科技有限公司/MODstore_deploy/.venv/bin/python' "
        "-m pytest '成都修茈科技有限公司/MODstore_deploy/tests/"
        "test_self_maintenance_loop_runner_policy.py' -q"
    )
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_FOCUSED_TEST_COMMAND", focused)
    steps = [
        {
            "step": "qa",
            "report_excerpt": (
                'SELF_MAINTENANCE_QA_JSON: {"verdict":"PASS","blocking_findings":[],'
                '"tested_commands":['
                f'{{"command":"{focused}","exit_code":127,"status":"failed"}},'
                '{"command":"cd /tmp/xcmax-qa-target && '
                "PYTHONPATH='成都修茈科技有限公司/MODstore_deploy:FHD' python3 -m pytest "
                "'成都修茈科技有限公司/MODstore_deploy/tests/"
                "test_self_maintenance_loop_runner_policy.py' -q\","
                '"exit_code":0,"status":"passed (27 tests passed)"}],'
                f"{QUALITY_CHECKS_JSON}"
                '"target_branch_available":true,'
                '"test_delta":{"baseline_id":"b1","new_failures":[],"new_errors":[]},'
                '"changed_files_scope":"low","risk_class":"low"}'
            ),
        }
    ]

    assert _structured_report_gate(steps)["ok"] is True


def test_structured_report_gate_rejects_unrelated_platform_pytest(monkeypatch):
    focused = "runtime-python -m pytest focused.py -q"
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_FOCUSED_TEST_COMMAND", focused)
    steps = [
        {
            "step": "qa",
            "report_excerpt": (
                'SELF_MAINTENANCE_QA_JSON: {"verdict":"PASS","blocking_findings":[],'
                '"tested_commands":[{"command":"cd /tmp/xcmax-qa-target && '
                "PYTHONPATH='成都修茈科技有限公司/MODstore_deploy:FHD' "
                'python3 -m pytest tests/test_other.py -q",'
                '"exit_code":0,"status":"passed"}],"target_branch_available":true,'
                '"test_delta":{"baseline_id":"b1","new_failures":[],"new_errors":[]},'
                '"changed_files_scope":"low","risk_class":"low"}'
            ),
        }
    ]

    assert _structured_report_gate(steps)["reason"] == "structured_qa_focused_command_not_passed"


def test_structured_report_gate_requires_black_isort_and_source_governance(monkeypatch):
    focused = "runtime-python -m pytest focused.py -q"
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_FOCUSED_TEST_COMMAND", focused)

    def qa_report(quality_checks):
        return [
            {
                "step": "qa",
                "report_excerpt": (
                    'SELF_MAINTENANCE_QA_JSON: {"verdict":"PASS","blocking_findings":[],'
                    f'"tested_commands":[{{"command":"{focused}","exit_code":0,'
                    '"status":"passed"}],'
                    f'"quality_checks":{json.dumps(quality_checks)},'
                    '"target_branch_available":true,'
                    '"test_delta":{"baseline_id":"b1","new_failures":[],"new_errors":[]},'
                    '"changed_files_scope":"low","risk_class":"low"}'
                ),
            }
        ]

    missing_black = {
        "isort": {
            "command": ("python3 -m isort --check-only --diff modman/ modstore_server/ tests/"),
            "exit_code": 0,
            "status": "passed",
        },
        "source_governance": {
            "command": "python3 scripts/dev/source_governance.py --top 10",
            "exit_code": 0,
            "status": "passed",
        },
    }
    missing_isort = {
        "black": {
            "command": "python3 -m black --check modman/ modstore_server/ tests/",
            "exit_code": 0,
            "status": "passed",
        },
        "source_governance": {
            "command": "python3 scripts/dev/source_governance.py --top 10",
            "exit_code": 0,
            "status": "passed",
        },
    }
    failed_governance = {
        "black": {
            "command": "python3 -m black --check modman/ modstore_server/ tests/",
            "exit_code": 0,
            "status": "passed",
        },
        "isort": {
            "command": ("python3 -m isort --check-only --diff modman/ modstore_server/ tests/"),
            "exit_code": 0,
            "status": "passed",
        },
        "source_governance": {
            "command": "python3 scripts/dev/source_governance.py --top 10",
            "exit_code": 1,
            "status": "failed",
        },
    }

    assert (
        _structured_report_gate(qa_report(missing_black))["reason"]
        == "structured_qa_black_not_passed"
    )
    assert (
        _structured_report_gate(qa_report(missing_isort))["reason"]
        == "structured_qa_isort_not_passed"
    )
    assert (
        _structured_report_gate(qa_report(failed_governance))["reason"]
        == "structured_qa_source_governance_not_passed"
    )


def test_quality_command_matchers_require_real_commands_and_scopes():
    assert matches_black_check_command(
        "python -m modstore_server.self_maintenance_diff_quality --tool black "
        "--base-ref origin/main --target-ref origin/feature"
    )
    assert matches_isort_check_command(
        "python3 -m modstore_server.self_maintenance_diff_quality --tool isort "
        "--base-ref origin/main --target-ref HEAD"
    )
    assert matches_black_check_command(
        "cd /tmp/target && GIT_DIR=/tmp/repo/.git GIT_WORK_TREE=/tmp/target "
        "python3 -m modstore_server.self_maintenance_diff_quality --tool black "
        "--base-ref origin/main --target-ref origin/feature"
    )
    assert matches_isort_check_command(
        "cd /tmp/target && GIT_DIR=/tmp/repo/.git GIT_WORK_TREE=/tmp/target "
        "python3 -m modstore_server.self_maintenance_diff_quality --tool isort "
        "--base-ref origin/main --target-ref origin/feature"
    )
    assert not matches_black_check_command(
        "python -m modstore_server.self_maintenance_diff_quality --tool isort "
        "--base-ref origin/main --target-ref HEAD"
    )
    assert not matches_black_check_command(
        "python -m modstore_server.self_maintenance_diff_quality --tool black "
        "--base-ref HEAD --target-ref HEAD"
    )
    assert matches_black_check_command(
        "cd 成都修茈科技有限公司/MODstore_deploy && "
        "python3 -m black --check modman/ modstore_server/ tests/"
    )
    assert not matches_black_check_command(
        "echo python3 -m black --check modman/ modstore_server/ tests/"
    )
    assert not matches_black_check_command("python3 -m black --check modstore_server/ tests/")
    assert matches_isort_check_command(
        "python3 -m isort --check-only --diff modman/ modstore_server/ tests/"
    )
    assert not matches_isort_check_command(
        "echo python3 -m isort --check-only --diff modman/ modstore_server/ tests/"
    )
    assert matches_source_governance_command("python3 scripts/dev/source_governance.py --top 10")
    assert matches_source_governance_command(
        "PYTHONPATH=/tmp/target python3 scripts/dev/source_governance.py --top 10"
    )
    assert not matches_source_governance_command(
        "echo python3 scripts/dev/source_governance.py --top 10"
    )


def test_quality_gate_accepts_worker_env_prefixes_on_real_commands():
    diff_prefix = (
        "cd /tmp/target && GIT_DIR=/tmp/repo/.git GIT_WORK_TREE=/tmp/target "
        "python3 -m modstore_server.self_maintenance_diff_quality"
    )
    qa_json = {
        "quality_checks": {
            "black": {
                "command": (
                    f"{diff_prefix} --tool black --base-ref origin/main "
                    "--target-ref origin/feature"
                ),
                "exit_code": 0,
                "status": "passed",
            },
            "isort": {
                "command": (
                    f"{diff_prefix} --tool isort --base-ref origin/main "
                    "--target-ref origin/feature"
                ),
                "exit_code": 0,
                "status": "passed",
            },
            "source_governance": {
                "command": "PYTHONPATH=/tmp/target python3 scripts/dev/source_governance.py --top 10",
                "exit_code": 0,
                "status": "passed",
            },
        }
    }

    assert quality_check_failure(qa_json) is None


def test_focused_command_matcher_fails_closed_on_malformed_quotes():
    focused = "runtime-python -m pytest focused.py -q"

    assert not _matches_focused_test_command(
        "python3 -m pytest 'focused.py -q",
        focused,
    )
    assert not _matches_focused_test_command(
        "python3 -m pytest focused.py -q",
        "runtime-python -m pytest 'focused.py -q",
    )


def test_focused_command_matcher_preserves_parentheses_in_test_path():
    focused = "runtime-python -m pytest 'tests/test_(special).py' -q"

    assert _matches_focused_test_command(
        "python3 -m pytest 'tests/test_(special).py' -q (target branch)",
        focused,
    )


def test_focused_command_matcher_ignores_trailing_note_targets():
    focused = "runtime-python -m pytest focused.py -q"

    assert not _matches_focused_test_command(
        "python3 -m pytest other.py -q (see focused.py )",
        focused,
    )


def test_focused_command_matcher_requires_target_in_same_shell_segment():
    focused = "runtime-python -m pytest focused.py -q"

    assert not _matches_focused_test_command(
        "python3 -m pytest other.py -q && echo focused.py",
        focused,
    )


def test_structured_report_gate_uses_latest_marker_after_echoed_prompt(monkeypatch):
    focused = "runtime-python -m pytest focused.py -q"
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_FOCUSED_TEST_COMMAND", focused)
    steps = [
        {
            "step": "qa",
            "report_excerpt": (
                "Prompt says output SELF_MAINTENANCE_QA_JSON: with schema ...\n"
                "SELF_MAINTENANCE_QA_JSON: "
                '{"verdict":"PASS","blocking_findings":[],'
                f'"tested_commands":[{{"command":"{focused}","exit_code":0,"status":"passed"}}],'
                f"{QUALITY_CHECKS_JSON}"
                '"target_branch_available":true,'
                '"test_delta":{"baseline_id":"b1","new_failures":[],"new_errors":[]},'
                '"changed_files_scope":"low","risk_class":"low"}'
            ),
        }
    ]

    assert _structured_report_gate(steps)["ok"] is True


def test_ensure_clean_baseline_writes_default_file(monkeypatch, tmp_path):
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_CLEAN_BASELINE", str(tmp_path / "baseline.json"))

    baseline = ensure_clean_baseline()

    assert clean_baseline_path().exists()
    assert baseline["baseline_id"] == "initial-current-known-failures-2026-06-18"
    assert baseline["pytest"]["allowed_failure_count"] == 80


def test_close_loop_memory_items_moves_open_item_to_closed(monkeypatch, tmp_path):
    memory_path = tmp_path / "loop_memory.json"
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MEMORY", str(memory_path))
    loop_memory_path().write_text(
        json.dumps(
            {
                "closed_items": [],
                "open_items": [
                    {
                        "kind": "human_strategy_approval",
                        "reason": "changed_files_outside_dynamic_low_risk_scope",
                        "run_id": "run-1",
                    }
                ],
                "recent_runs": [],
            }
        ),
        encoding="utf-8",
    )

    result = close_loop_memory_items(
        actor="test",
        resolution_reason="kb scope now allows approved knowledge artifacts",
        run_ids=["run-1"],
    )
    memory = _load_loop_memory()

    assert result["closed_count"] == 1
    assert memory["open_items"] == []
    assert memory["closed_items"][0]["actor"] == "test"
    assert memory["closed_items"][0]["original_item"]["run_id"] == "run-1"


def test_update_loop_memory_closes_resumed_item_after_success(monkeypatch, tmp_path):
    memory_path = tmp_path / "loop_memory.json"
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MEMORY", str(memory_path))
    loop_memory_path().write_text(
        json.dumps(
            {
                "closed_items": [],
                "open_items": [
                    {
                        "branch": "devfleet/codex/sub-1",
                        "kind": "failed_steps",
                        "run_id": "failed-run",
                        "steps": ["qa"],
                        "task_id": "task-1",
                    }
                ],
                "recent_runs": [],
                "run_count": 0,
            }
        ),
        encoding="utf-8",
    )

    _update_loop_memory(
        {
            "branch": "devfleet/codex/sub-1",
            "completed_at": "2026-06-18T00:00:00+00:00",
            "para_task_id": "task-1",
            "policy_decision": {"action": "auto_continue", "reason": "no_code_branch"},
            "resume_candidate": {
                "branch": "devfleet/codex/sub-1",
                "failed_run_id": "failed-run",
                "failed_steps": ["qa"],
                "para_task_id": "task-1",
            },
            "run_id": "new-run",
            "status": "completed",
            "steps": [{"ok": True, "step": "qa"}],
        },
        {"reason": "force"},
    )
    memory = _load_loop_memory()

    assert memory["open_items"] == []
    assert memory["closed_items"][0]["original_item"]["run_id"] == "failed-run"
    assert memory["last_resolution_record"]["closed_count"] == 1


def test_update_loop_memory_retires_code_remediation_after_downstream_qa_failure(
    monkeypatch, tmp_path
):
    memory_path = tmp_path / "loop_memory.json"
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MEMORY", str(memory_path))
    loop_memory_path().write_text(
        json.dumps(
            {
                "closed_items": [],
                "open_items": [
                    {
                        "branch": "devfleet/cursor/old-code",
                        "kind": "automated_remediation",
                        "reason": "structured_qa_black_not_passed",
                        "run_id": "old-run",
                        "task_id": "old-task",
                    }
                ],
                "recent_runs": [],
                "run_count": 0,
            }
        ),
        encoding="utf-8",
    )

    _update_loop_memory(
        {
            "branch": "devfleet/cursor/delivered-code",
            "completed_at": "2026-07-27T00:00:00+00:00",
            "para_task_id": "new-task",
            "policy_decision": {"action": "stop", "reason": "loop_not_completed"},
            "resume_candidate": {
                "branch": "devfleet/cursor/old-code",
                "failed_run_id": "old-run",
                "failed_steps": ["code"],
                "para_task_id": "old-task",
            },
            "run_id": "new-run",
            "status": "failed",
            "steps": [
                {"ok": True, "step": "code"},
                {"ok": True, "step": "review"},
                {"ok": False, "step": "qa"},
            ],
        },
        {"reason": "force"},
    )
    memory = _load_loop_memory()

    assert len(memory["open_items"]) == 1
    assert memory["open_items"][0]["branch"] == "devfleet/cursor/delivered-code"
    assert memory["open_items"][0]["kind"] == "failed_steps"
    assert memory["open_items"][0]["para_task_id"] == "new-task"
    assert memory["open_items"][0]["run_id"] == "new-run"
    assert memory["open_items"][0]["steps"] == ["qa"]
    assert memory["closed_items"][-1]["original_item"]["run_id"] == "old-run"
    assert memory["closed_items"][-1]["resolution_reason"] == "superseded_by_successful_code_step"


def test_merge_request_does_not_close_open_remediation(monkeypatch, tmp_path):
    memory_path = tmp_path / "loop_memory.json"
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MEMORY", str(memory_path))
    loop_memory_path().write_text(
        json.dumps(
            {
                "closed_items": [],
                "open_items": [
                    {
                        "branch": "devfleet/codex/fix-1",
                        "kind": "failed_steps",
                        "run_id": "failed-run",
                        "steps": ["qa"],
                        "para_task_id": "task-1",
                    }
                ],
                "recent_runs": [],
                "run_count": 0,
            }
        ),
        encoding="utf-8",
    )

    _update_loop_memory(
        {
            "branch": "devfleet/codex/fix-1",
            "completed_at": "2026-07-23T00:00:00+00:00",
            "para_task_id": "task-1",
            "policy_decision": {
                "action": "auto_merge_requested_low_risk",
                "reason": "low_risk_merge_requested",
            },
            "run_id": "new-run",
            "status": "completed_merge_requested",
            "steps": [{"ok": True, "step": "qa"}],
        },
        {"reason": "force"},
    )
    memory = _load_loop_memory()

    assert len(memory["open_items"]) == 1
    assert memory["closed_items"] == []
    assert memory["last_resolution_record"]["closed_count"] == 0


def test_reconcile_para_review_veto_preserves_exact_findings_for_next_code_task():
    memory = {
        "closed_items": [],
        "open_items": [],
        "recent_runs": [
            {
                "branch": "devfleet/codex/fix-1",
                "para_task_id": "task-1",
                "run_id": "run-1",
                "status": "completed_merge_requested",
            }
        ],
    }
    feedback = "REJECT: only mark escalated after enqueue succeeds"

    result = _reconcile_requested_merge_feedback(
        memory,
        api_base="http://para.test",
        task_fetcher=lambda _base, _task_id: {
            "status": "merge_conflict",
            "merge_conflict": {
                "branch_name": "devfleet/codex/fix-1",
                "detail": feedback,
                "source": "ai-review-veto",
            },
        },
    )

    assert result["remediation_added"] == 1
    assert memory["open_items"][0]["review_feedback"] == feedback
    candidate = _resume_review_qa_candidate(memory)
    assert candidate == {
        "branch": "devfleet/codex/fix-1",
        "failed_run_id": "run-1",
        "failed_steps": ["code"],
        "para_task_id": "task-1",
        "reason": "resume_para_ai_review_rejection",
        "rejected_branch": "devfleet/codex/fix-1",
        "review_actionable_findings": True,
        "review_feedback": feedback,
        "review_veto_branch_hint": "",
        "review_veto_code": "",
    }
    assert _resume_dispatch_context(candidate, _resume_steps(candidate)) == (None, None)
    prompt = _code_task_text("run-2", {"gaps": []}, memory, candidate)
    assert "EXTERNAL MERGE REVIEW REMEDIATION" in prompt
    assert "starts from the configured clean base" in prompt
    assert "do not inherit or cherry-pick the whole rejected diff" in prompt
    assert feedback in prompt

    repeated = _reconcile_requested_merge_feedback(
        memory,
        api_base="http://para.test",
        task_fetcher=lambda _base, _task_id: {
            "status": "merge_conflict",
            "merge_conflict": {
                "branch_name": "devfleet/codex/fix-1",
                "detail": feedback,
                "source": "ai-review-veto",
            },
        },
    )
    assert repeated["changed"] is False
    assert len(memory["open_items"]) == 1


def test_classify_indeterminate_merge_review_detail():
    meta = classify_para_merge_review_detail(
        "devfleet/codex/sub-1-46107b: indeterminate-review",
    )
    assert meta["veto_code"] == "indeterminate-review"
    assert meta["branch_hint"] == "devfleet/codex/sub-1-46107b"
    assert meta["actionable_code_findings"] is False


def test_classify_diff_too_large_merge_review_detail():
    meta = classify_para_merge_review_detail(
        "devfleet/cursor/sub-1-ee8a21: diff-too-large:37810",
    )
    assert meta["veto_code"] == "diff-too-large"
    assert meta["branch_hint"] == "devfleet/cursor/sub-1-ee8a21"
    assert meta["actionable_code_findings"] is False
    assert meta["review_diff_chars"] == 37810


def test_dynamic_low_risk_policy_blocks_kb_only_when_indeterminate_veto_open():
    memory = {
        "open_items": [
            {
                "branch": "devfleet/cursor/sub-1-d0a091",
                "kind": "automated_remediation",
                "para_task_id": "task-cursor-indeterminate",
                "reason": "para_ai_review_rejected",
                "review_feedback": "devfleet/cursor/sub-1-d0a091: indeterminate-review",
                "review_veto_code": "indeterminate-review",
            }
        ]
    }
    files = [
        "FHD/XCAGI/kb/fixes/sample-fix.json",
        "成都修茈科技有限公司/MODstore_deploy/tests/test_self_maintenance_loop_runner_policy.py",
    ]

    result = _assess_branch_auto_merge_policy(files, _stats(), memory=memory)

    assert result["ok"] is False
    assert result["reason"] == "kb_paths_blocked_during_indeterminate_remediation"
    assert result["kb_paths"] == [files[0]]


def test_dynamic_low_risk_policy_blocks_kb_only_when_retort_scope_open():
    memory = {
        "open_items": [
            {
                "branch": "devfleet/cursor/sub-1-6d8f01",
                "kind": "automated_remediation",
                "para_task_id": "task-retort-scope",
                "reason": "retort_scope_too_large",
                "detail": (
                    "Retort requested risk acceptance for 12 changed files; "
                    "rebuild the smallest valid fix from the clean base."
                ),
            }
        ]
    }
    files = [
        "FHD/XCAGI/kb/fixes/sample-fix.json",
        "成都修茈科技有限公司/MODstore_deploy/tests/test_self_maintenance_loop_runner_policy.py",
    ]

    result = _assess_branch_auto_merge_policy(files, _stats(), memory=memory)

    assert result["ok"] is False
    assert result["reason"] == "kb_paths_blocked_during_retort_scope_remediation"
    assert result["kb_paths"] == [files[0]]


def test_dynamic_low_risk_policy_blocks_tests_only_when_retort_scope_open():
    memory = {
        "open_items": [
            {
                "branch": "devfleet/cursor/sub-1-6d8f01",
                "kind": "automated_remediation",
                "para_task_id": "task-retort-scope",
                "reason": "retort_scope_too_large",
            }
        ]
    }
    files = [
        "成都修茈科技有限公司/MODstore_deploy/tests/test_self_maintenance_loop_runner_policy.py",
    ]

    result = _assess_branch_auto_merge_policy(files, _stats(), memory=memory)

    assert result["ok"] is False
    assert result["reason"] == "auxiliary_only_diff_requires_executable_change"


def test_auto_merge_policy_blocks_kb_paths_during_retort_scope_remediation():
    memory = {
        "open_items": [
            {
                "branch": "devfleet/cursor/sub-1-6d8f01",
                "kind": "automated_remediation",
                "para_task_id": "task-retort-scope",
                "reason": "retort_scope_too_large",
            }
        ]
    }
    files = [
        "FHD/XCAGI/kb/fixes/sample-fix.json",
        "成都修茈科技有限公司/MODstore_deploy/modstore_server/self_maintenance_policy.py",
        "成都修茈科技有限公司/MODstore_deploy/tests/test_self_maintenance_loop_runner_policy.py",
    ]

    result = _assess_branch_auto_merge_policy(files, _stats(), memory=memory)

    assert result["ok"] is False
    assert result["reason"] == "kb_paths_blocked_during_retort_scope_remediation"
    assert result["kb_paths"] == [files[0]]


def test_auto_merge_policy_blocks_retort_excluded_paths_mixed_with_production():
    memory = {
        "open_items": [
            {
                "branch": "devfleet/cursor/sub-1-6d8f01",
                "kind": "automated_remediation",
                "para_task_id": "task-retort-scope",
                "reason": "retort_scope_too_large",
            }
        ]
    }
    files = [
        "scripts/dev/source_governance.py",
        "成都修茈科技有限公司/MODstore_deploy/modstore_server/self_maintenance_policy.py",
        "成都修茈科技有限公司/MODstore_deploy/tests/test_self_maintenance_policy.py",
    ]

    result = _assess_branch_auto_merge_policy(files, _stats(), memory=memory)

    assert result["ok"] is False
    assert result["reason"] == "retort_scope_excluded_paths_blocked_during_remediation"
    assert result["excluded_paths"] == [files[0]]


def test_auto_merge_policy_blocks_diff_too_large_excluded_paths_mixed_with_production():
    memory = {
        "open_items": [
            {
                "branch": "devfleet/cursor/sub-1-327c02",
                "kind": "automated_remediation",
                "para_task_id": "task-diff-large-327",
                "reason": "para_ai_review_rejected",
                "review_feedback": "devfleet/cursor/sub-1-327c02: diff-too-large:50140",
                "review_veto_code": "diff-too-large",
            }
        ]
    }
    files = [
        "config/source_governance_baseline.json",
        "成都修茈科技有限公司/MODstore_deploy/modstore_server/self_maintenance_policy.py",
    ]

    result = _assess_branch_auto_merge_policy(files, _stats(), memory=memory)

    assert result["ok"] is False
    assert result["reason"] == "remediation_excluded_paths_blocked_during_diff_too_large"
    assert result["excluded_paths"] == [files[0]]


def test_auto_merge_policy_blocks_kb_paths_during_diff_too_large_remediation():
    memory = {
        "open_items": [
            {
                "branch": "devfleet/cursor/sub-1-327c02",
                "kind": "automated_remediation",
                "para_task_id": "task-diff-large-327",
                "reason": "para_ai_review_rejected",
                "review_feedback": "devfleet/cursor/sub-1-327c02: diff-too-large:50140",
                "review_veto_code": "diff-too-large",
            }
        ]
    }
    files = [
        "FHD/XCAGI/kb/fixes/sample-fix.json",
        "成都修茈科技有限公司/MODstore_deploy/modstore_server/self_maintenance_policy.py",
        "成都修茈科技有限公司/MODstore_deploy/tests/test_self_maintenance_loop_runner_policy.py",
    ]
    diff_stats = {**_stats(line_changes=12), "git_diff_chars": 29900}

    result = _assess_branch_auto_merge_policy(files, diff_stats, memory=memory)

    assert result["ok"] is False
    assert result["reason"] == "kb_paths_blocked_during_diff_too_large_remediation"
    assert result["kb_paths"] == [files[0]]


def test_auto_merge_policy_rejects_diff_over_para_merge_review_budget():
    files = [
        "成都修茈科技有限公司/MODstore_deploy/modstore_server/self_maintenance_policy.py",
    ]
    diff_stats = {**_stats(line_changes=5), "git_diff_chars": 59051}

    result = _assess_branch_auto_merge_policy(files, diff_stats, memory={})

    assert result["ok"] is False
    assert result["reason"] == "diff_too_large_for_para_merge_review"


def test_reconcile_diff_too_large_merge_review_veto_prompts_shrink_hint():
    memory = {
        "closed_items": [],
        "open_items": [],
        "recent_runs": [
            {
                "branch": "devfleet/cursor/sub-1-3ee902",
                "para_task_id": "task-diff-large",
                "run_id": "run-diff-large",
                "status": "completed_merge_requested",
            }
        ],
    }
    feedback = "devfleet/cursor/sub-1-3ee902: diff-too-large:59051"

    result = _reconcile_requested_merge_feedback(
        memory,
        api_base="http://para.test",
        task_fetcher=lambda _base, _task_id: {
            "status": "merge_conflict",
            "merge_conflict": {
                "branch_name": "devfleet/cursor/sub-1-3ee902",
                "detail": feedback,
                "source": "ai-review-veto",
            },
        },
    )

    assert result["remediation_added"] == 1
    item = memory["open_items"][0]
    assert item["review_veto_code"] == "diff-too-large"
    assert item["review_diff_chars"] == 59051
    candidate = _resume_review_qa_candidate(memory)
    prompt = _code_task_text("run-followup", {"gaps": []}, memory, candidate)
    assert "DIFF TOO LARGE MERGE REVIEW VETO" in prompt


def test_reconcile_real_para_merge_sha_closes_matching_open_item():
    memory = {
        "closed_items": [],
        "open_items": [
            {
                "branch": "devfleet/codex/fix-1",
                "kind": "automated_remediation",
                "para_task_id": "task-1",
                "reason": "para_ai_review_rejected",
            }
        ],
        "recent_runs": [
            {
                "branch": "devfleet/codex/fix-1",
                "para_task_id": "task-1",
                "run_id": "run-1",
                "status": "completed_merge_requested",
            }
        ],
    }

    result = _reconcile_requested_merge_feedback(
        memory,
        api_base="http://para.test",
        task_fetcher=lambda _base, _task_id: {
            "status": "merged",
            "merge_commit_sha": "a" * 40,
        },
    )

    assert result["merged"] == 1
    assert memory["open_items"] == []
    assert memory["closed_items"][0]["resolution_reason"] == "para_reported_real_merge_sha"


@pytest.mark.parametrize(
    ("task", "expected_reason"),
    [
        (
            {
                "status": "merge_conflict",
                "merge_conflict": {
                    "branch_name": "devfleet/codex/fix-conflict",
                    "detail": "content conflict in policy.py",
                    "source": "git-merge",
                },
            },
            "para_merge_conflict",
        ),
        (
            {
                "status": "failed",
                "fail_reason": "required CI checks failed",
            },
            "para_merge_task_failed",
        ),
    ],
)
def test_reconcile_terminal_para_merge_failure_restarts_from_clean_base(task, expected_reason):
    memory = {
        "closed_items": [],
        "open_items": [],
        "recent_runs": [
            {
                "branch": "devfleet/codex/fix-conflict",
                "para_task_id": "task-failed",
                "run_id": "run-failed",
                "status": "completed_merge_requested",
            }
        ],
    }

    result = _reconcile_requested_merge_feedback(
        memory,
        api_base="http://para.test",
        task_fetcher=lambda _base, _task_id: task,
    )

    assert result["remediation_added"] == 1
    assert memory["open_items"][0]["reason"] == expected_reason
    assert memory["open_items"][0]["resume_from_clean_baseline"] is True
    candidate = _resume_review_qa_candidate(memory)
    assert candidate["failed_steps"] == ["code"]
    assert "continue_existing_code_task" not in candidate
    assert _resume_dispatch_context(candidate, _resume_steps(candidate)) == (None, None)
    prompt = _code_task_text("run-retry", {"gaps": []}, memory, candidate)
    assert "EXTERNAL MERGE FAILURE REMEDIATION" in prompt
    assert expected_reason in prompt

    repeated = _reconcile_requested_merge_feedback(
        memory,
        api_base="http://para.test",
        task_fetcher=lambda _base, _task_id: task,
    )
    assert repeated["changed"] is False
    assert len(memory["open_items"]) == 1


def test_reconcile_post_dispatch_merge_failure_continues_on_rejected_branch():
    memory = {
        "closed_items": [],
        "open_items": [],
        "recent_runs": [
            {
                "branch": "devfleet/cursor/sub-1-bd3ea8",
                "para_task_id": "task-ci",
                "run_id": "run-ci",
                "status": "completed_merge_requested",
            }
        ],
    }
    task = {
        "status": "merge_conflict",
        "merge_conflict": {
            "branch_name": "devfleet/cursor/sub-1-bd3ea8",
            "detail": "post-dispatch-check-failed: PR #765 checks=docker-build-fhd-api",
            "source": "merge-worker",
        },
    }

    result = _reconcile_requested_merge_feedback(
        memory,
        api_base="http://para.test",
        task_fetcher=lambda _base, _task_id: task,
    )

    assert result["remediation_added"] == 1
    assert memory["open_items"][0]["resume_from_clean_baseline"] is False
    candidate = _resume_review_qa_candidate(memory)
    assert candidate["continue_existing_code_task"] is True
    assert _resume_dispatch_context(candidate, _resume_steps(candidate)) == (
        None,
        "devfleet/cursor/sub-1-bd3ea8",
    )
    prompt = _code_task_text("run-ci-retry", {"gaps": []}, memory, candidate)
    assert "Continue on the rejected branch as the mutable base" in prompt
    assert "docker-build-fhd-api" in prompt


def test_reconcile_indeterminate_review_merge_failure_continues_on_rejected_branch():
    memory = {
        "closed_items": [],
        "open_items": [],
        "recent_runs": [
            {
                "branch": "devfleet/cursor/sub-1-16960f",
                "para_task_id": "task-indeterminate",
                "run_id": "run-indeterminate",
                "status": "completed_merge_requested",
            }
        ],
    }
    task = {
        "status": "merge_conflict",
        "merge_conflict": {
            "branch_name": "devfleet/cursor/sub-1-16960f",
            "detail": (
                'indeterminate-review: {"chunks":[{"chunk":1,'
                '"diagnostics":{"primary":"Command failed: trae-cli","fallback":"empty"}}]}'
            ),
            "source": "merge-worker",
        },
    }

    result = _reconcile_requested_merge_feedback(
        memory,
        api_base="http://para.test",
        task_fetcher=lambda _base, _task_id: task,
    )

    assert result["remediation_added"] == 1
    assert memory["open_items"][0]["resume_from_clean_baseline"] is False
    candidate = _resume_review_qa_candidate(memory)
    assert candidate["continue_existing_code_task"] is True
    assert _resume_dispatch_context(candidate, _resume_steps(candidate)) == (
        None,
        "devfleet/cursor/sub-1-16960f",
    )
    prompt = _code_task_text("run-indeterminate-retry", {"gaps": []}, memory, candidate)
    assert "indeterminate AI review infrastructure" in prompt
    assert "indeterminate-review" in prompt


def test_reconcile_hold_merge_label_failure_continues_on_rejected_branch():
    memory = {
        "closed_items": [],
        "open_items": [],
        "recent_runs": [
            {
                "branch": "devfleet/cursor/sub-1-81ba09",
                "para_task_id": "task-hold",
                "run_id": "run-hold",
                "status": "completed_merge_requested",
            }
        ],
    }
    task = {
        "status": "merge_conflict",
        "merge_conflict": {
            "branch_name": "devfleet/cursor/sub-1-81ba09",
            "detail": "hold-merge-label-failed-before-review",
            "source": "merge-worker",
        },
    }

    result = _reconcile_requested_merge_feedback(
        memory,
        api_base="http://para.test",
        task_fetcher=lambda _base, _task_id: task,
    )

    assert result["remediation_added"] == 1
    assert memory["open_items"][0]["resume_from_clean_baseline"] is False
    candidate = _resume_review_qa_candidate(memory)
    assert candidate["continue_existing_code_task"] is True
    assert _resume_dispatch_context(candidate, _resume_steps(candidate)) == (
        None,
        "devfleet/cursor/sub-1-81ba09",
    )
    prompt = _code_task_text("run-hold-retry", {"gaps": []}, memory, candidate)
    assert "hold-merge label infrastructure" in prompt
    assert "hold-merge-label-failed-before-review" in prompt


def test_reconcile_bot_merge_checks_unavailable_continues_on_rejected_branch():
    memory = {
        "closed_items": [],
        "open_items": [],
        "recent_runs": [
            {
                "branch": "devfleet/cursor/sub-1-67f884",
                "para_task_id": "task-gh-checks",
                "run_id": "run-gh-checks",
                "status": "completed_merge_requested",
            }
        ],
    }
    task = {
        "status": "merge_conflict",
        "merge_conflict": {
            "branch_name": "devfleet/cursor/sub-1-67f884",
            "detail": (
                "bot merge checks failed or unavailable: Command failed: gh pr checks 813 "
                "--watch --fail-fast --interval 10 --repo 42433422/XCMAX"
            ),
            "source": "merge-worker",
        },
    }

    result = _reconcile_requested_merge_feedback(
        memory,
        api_base="http://para.test",
        task_fetcher=lambda _base, _task_id: task,
    )

    assert result["remediation_added"] == 1
    assert memory["open_items"][0]["resume_from_clean_baseline"] is False
    candidate = _resume_review_qa_candidate(memory)
    assert candidate["continue_existing_code_task"] is True
    assert _resume_dispatch_context(candidate, _resume_steps(candidate)) == (
        None,
        "devfleet/cursor/sub-1-67f884",
    )
    prompt = _code_task_text("run-gh-checks-retry", {"gaps": []}, memory, candidate)
    assert "gh pr checks polling infrastructure" in prompt
    assert "bot merge checks failed or unavailable" in prompt


@pytest.mark.parametrize(
    "detail",
    [
        (
            "devfleet/cursor/sub-1-16960f: indeterminate-review: "
            '{"chunks":[{"chunk":1,"diagnostics":{"primary":"timeout"}}]}'
        ),
        (
            "devfleet/cursor/sub-1-67f884: Error: bot merge checks failed or unavailable: "
            "Command failed: gh pr checks 813 --watch --fail-fast"
        ),
        "Error: bot merge checks failed or unavailable: gh CLI unavailable",
        "hold-merge-label-failed-before-review",
        "devfleet/cursor/sub-1-81ba09: hold-merge-label-remove-failed-after-review",
    ],
)
def test_para_merge_conflict_continues_on_merge_worker_detail_formats(detail: str):
    assert para_merge_conflict_continues_on_rejected_branch(detail) is True


def test_para_merge_conflict_does_not_continue_on_git_content_conflict():
    assert para_merge_conflict_continues_on_rejected_branch("git merge conflict in foo.py") is False


def test_reconcile_update_branch_content_conflict_restarts_from_clean_base():
    memory = {
        "closed_items": [],
        "open_items": [],
        "recent_runs": [
            {
                "branch": "devfleet/cursor/sub-1-225e80",
                "para_task_id": "task-update-branch",
                "run_id": "run-update-branch",
                "status": "completed_merge_requested",
            }
        ],
    }
    detail = (
        "devfleet/cursor/sub-1-225e80: Error: update-branch failed: Command failed: "
        "gh pr update-branch 830 --repo 42433422/XCMAX\n"
        "X Cannot update PR branch due to conflicts"
    )
    task = {
        "status": "merge_conflict",
        "merge_conflict": {
            "branch_name": "devfleet/cursor/sub-1-225e80",
            "detail": detail,
            "source": "merge-worker",
        },
    }

    result = _reconcile_requested_merge_feedback(
        memory,
        api_base="http://para.test",
        task_fetcher=lambda _base, _task_id: task,
    )

    assert result["remediation_added"] == 1
    assert memory["open_items"][0]["resume_from_clean_baseline"] is True
    candidate = _resume_review_qa_candidate(memory)
    assert "continue_existing_code_task" not in candidate
    prompt = _code_task_text("run-update-branch-retry", {"gaps": []}, memory, candidate)
    assert "update-branch content conflicts" in prompt
    assert para_merge_conflict_continues_on_rejected_branch(detail) is False


def test_para_merge_remediation_branch_preserving_helpers():
    from modstore_server.self_maintenance_para_merge_remediation import (
        is_branch_preserving_para_merge_failure_detail,
        resume_from_clean_baseline_for_para_merge,
    )

    assert is_branch_preserving_para_merge_failure_detail(
        "post-dispatch-check-failed: PR #765 checks=docker-build-fhd-api"
    )
    assert is_branch_preserving_para_merge_failure_detail("hold-merge-label-failed-before-review")
    assert is_branch_preserving_para_merge_failure_detail(
        "bot merge checks failed or unavailable: Command failed: gh pr checks 813"
    )
    update_branch_detail = (
        "devfleet/cursor/sub-1-225e80: Error: update-branch failed: Command failed: "
        "gh pr update-branch 830 --repo 42433422/XCMAX\n"
        "X Cannot update PR branch due to conflicts"
    )
    assert not is_branch_preserving_para_merge_failure_detail(update_branch_detail)
    assert (
        resume_from_clean_baseline_for_para_merge(
            "para_merge_conflict", "hold-merge-label-failed-before-review"
        )
        is False
    )
    assert (
        resume_from_clean_baseline_for_para_merge(
            "para_merge_conflict",
            "bot merge checks failed or unavailable: gh pr checks 813",
        )
        is False
    )
    assert resume_from_clean_baseline_for_para_merge("para_merge_conflict", update_branch_detail)
    assert resume_from_clean_baseline_for_para_merge("para_merge_conflict", "true conflict")


def test_reconcile_merge_worker_branch_prefixed_indeterminate_review_detail():
    memory = {
        "closed_items": [],
        "open_items": [],
        "recent_runs": [
            {
                "branch": "devfleet/cursor/sub-1-16960f",
                "para_task_id": "task-indeterminate-prefixed",
                "run_id": "run-indeterminate-prefixed",
                "status": "completed_merge_requested",
            }
        ],
    }
    task = {
        "status": "merge_conflict",
        "merge_conflict": {
            "branch_name": "devfleet/cursor/sub-1-16960f",
            "detail": (
                "devfleet/cursor/sub-1-16960f: indeterminate-review: "
                '{"chunks":[{"chunk":1,"diagnostics":{"primary":"Command failed: trae-cli"}}]}'
            ),
            "source": "merge-worker",
        },
    }

    result = _reconcile_requested_merge_feedback(
        memory,
        api_base="http://para.test",
        task_fetcher=lambda _base, _task_id: task,
    )

    assert result["remediation_added"] == 1
    assert memory["open_items"][0]["resume_from_clean_baseline"] is False


# ---------------------------------------------------------------------------
# _find_delivery_validation: 直接单元测试（2026-07-20 修复核心）
# ---------------------------------------------------------------------------


class TestFindDeliveryValidation:
    """验证 `_find_delivery_validation` 在 Para 远端返回结构中递归定位
    delivery_validation dict 的能力。"""

    def test_find_delivery_validation_single_level_nesting(self):
        """单层嵌套：result.result.outputs[0].para_result.delivery_validation。"""
        dv = {"commands": [{"exit_code": 1, "command": "pytest"}]}
        result = {
            "result": {
                "outputs": [
                    {
                        "handler": "para_delegate",
                        "para_result": {"delivery_validation": dv},
                    }
                ]
            }
        }

        found = _find_delivery_validation(result)

        assert found is dv

    def test_find_delivery_validation_deep_nesting(self):
        """depth=4 多层嵌套，模拟 Para 真实结构
        result.result.outputs[0].response.data.subtask.delivery_validation。"""
        dv = {"commands": [{"exit_code": 2}]}
        result = {
            "result": {
                "outputs": [
                    {
                        "response": {
                            "data": {
                                "subtask": {"delivery_validation": dv},
                            },
                        },
                    }
                ]
            }
        }

        found = _find_delivery_validation(result)

        assert found is dv

    def test_find_delivery_validation_depth_truncation(self):
        """depth>6 时返回 None：构造 7 层嵌套，delivery_validation 在第 7 层。"""
        dv = {"commands": [{"exit_code": 1}]}
        # 嵌套结构：a -> b -> c -> d -> e -> f -> g -> delivery_validation
        # 调用 _find_delivery_validation(top) 时 depth=0, 进入 a 后 depth=1,
        # 进入 b 后 depth=2, ..., 进入 g 后 depth=7 → 立即返回 None
        nested = {"delivery_validation": dv}
        for key in ("g", "f", "e", "d", "c", "b", "a"):
            nested = {key: nested}

        found = _find_delivery_validation(nested)

        assert found is None

    def test_find_delivery_validation_list_truncation(self):
        """列表超过 12 项时只搜前 12 项：delivery_validation 放在第 13 项应返回 None。"""
        dv = {"commands": [{"exit_code": 1}]}
        items = [{"index": i} for i in range(12)] + [{"delivery_validation": dv}]
        result = {"items": items}

        found = _find_delivery_validation(result)

        assert found is None

    def test_find_delivery_validation_skips_non_dict(self):
        """delivery_validation 字段值为字符串/list 时返回 None（只识别 dict）。"""
        result_str = {"delivery_validation": "not a dict"}
        result_list = {"delivery_validation": ["not", "a", "dict"]}

        assert _find_delivery_validation(result_str) is None
        assert _find_delivery_validation(result_list) is None

    def test_find_delivery_validation_empty_dict(self):
        """空 dict 输入返回 None。"""
        assert _find_delivery_validation({}) is None

    def test_find_delivery_validation_multiple_occurrences(self):
        """多个同质 delivery_validation 时返回更早发现的候选（稳定排序）。"""
        dv_first = {"commands": [{"exit_code": 1}], "marker": "first"}
        dv_second = {"commands": [{"exit_code": 2}], "marker": "second"}
        result = {
            "result": {
                "delivery_validation": dv_first,
                "nested": {"delivery_validation": dv_second},
            }
        }

        found = _find_delivery_validation(result)

        assert found is dv_first

    def test_find_delivery_validation_prefers_commands_over_stub(self):
        """无 commands 的 stub 不应盖过 para_result 里带 commands 的真 DV。"""
        stub = {"ok": True, "marker": "stub"}
        real = {"commands": [{"exit_code": 1, "command": "pytest"}], "marker": "real"}
        # Insertion order puts stub first; preferred key + commands score must win.
        result = {
            "zzz_stub": {"delivery_validation": stub},
            "para_result": {"delivery_validation": real},
        }

        found = _find_delivery_validation(result)

        assert found is real
        assert found["marker"] == "real"

    def test_find_delivery_validation_sorted_keys_are_deterministic(self):
        """非 preferred key 按字典序遍历，不依赖插入顺序。"""
        dv_a = {"commands": [{"exit_code": 1}], "marker": "a"}
        dv_b = {"commands": [{"exit_code": 1}], "marker": "b"}
        left_first = {"alpha": {"delivery_validation": dv_a}, "beta": {"delivery_validation": dv_b}}
        right_first = {
            "beta": {"delivery_validation": dv_b},
            "alpha": {"delivery_validation": dv_a},
        }

        assert _find_delivery_validation(left_first) is dv_a
        assert _find_delivery_validation(right_first) is dv_a

    def test_find_delivery_validation_in_list_items(self):
        """列表项中包含 delivery_validation 能被找到。"""
        dv = {"commands": [{"exit_code": 1}]}
        result = {"outputs": [{"name": "skip"}, {"delivery_validation": dv}]}

        found = _find_delivery_validation(result)

        assert found is dv

    def test_find_delivery_validation_commands_with_exit_code_none(self):
        """exit_code=None 的 command 不视为失败：_find_delivery_validation 仍能找到 dv，
        但 _extract_failure_reason 不会返回 delivery_validation_failed。"""
        dv = {"commands": [{"exit_code": None, "command": "pytest"}]}
        result = {"result": {"ok": False, "delivery_validation": dv}}

        # _find_delivery_validation 找到 dict
        found = _find_delivery_validation(result)
        assert found is dv

        # _extract_failure_reason 不把 exit_code=None 视为失败，落到 fallback
        reason = _extract_failure_reason(result, {})
        assert "delivery_validation_failed" not in reason

    def test_find_delivery_validation_commands_with_exit_code_zero(self):
        """exit_code=0 的 command 不视为失败。"""
        dv = {"commands": [{"exit_code": 0, "command": "pytest"}]}
        result = {"result": {"ok": False, "delivery_validation": dv}}

        found = _find_delivery_validation(result)
        assert found is dv

        reason = _extract_failure_reason(result, {})
        assert "delivery_validation_failed" not in reason

    def test_find_delivery_validation_commands_with_non_zero_exit(self):
        """exit_code≠0 的 command 视为失败：_extract_failure_reason 返回 delivery_validation_failed。"""
        dv = {
            "commands": [
                {"exit_code": 1, "command": "pytest tests/x.py"},
                {"exit_code": 0, "command": "ruff check"},
            ]
        }
        result = {"result": {"ok": False, "delivery_validation": dv}}

        found = _find_delivery_validation(result)
        assert found is dv

        reason = _extract_failure_reason(result, {})
        assert "delivery_validation_failed" in reason
        assert "exit=1" in reason

    def test_find_delivery_validation_returns_none_for_none_input(self):
        """None 输入返回 None。"""
        assert _find_delivery_validation(None) is None

    def test_find_delivery_validation_returns_none_for_string_input(self):
        """字符串输入返回 None。"""
        assert _find_delivery_validation("not a dict") is None


# ---------------------------------------------------------------------------
# _extract_failure_reason: 端到端优先级测试
# ---------------------------------------------------------------------------


class TestExtractFailureReasonEndToEnd:
    """验证 `_extract_failure_reason` 各分支优先级与 fallback 行为。"""

    def test_priority_handler_failed_message(self):
        """handler_failed + handler_failed_message 优先级最高。"""
        result = {
            "handler_failed": True,
            "handler_failed_message": "codex cli crashed",
            "result": {
                "ok": False,
                "delivery_validation": {"commands": [{"exit_code": 1}]},
            },
        }

        reason = _extract_failure_reason(result, {"error": "para error"})

        assert reason.startswith("handler_failed:")
        assert "codex cli crashed" in reason

    def test_priority_path_guard_violation(self):
        """path_guard.ok=False 提取 violations（无 handler_failed 时优先）。"""
        result = {
            "result": {
                "ok": False,
                "path_guard": {
                    "checked": True,
                    "ok": False,
                    "violations": [
                        {"path": "forbidden/x.py", "reason": "outside_scope"},
                    ],
                },
            }
        }

        reason = _extract_failure_reason(result, {})

        assert reason.startswith("path_guard_violation:")
        assert "forbidden/x.py" in reason
        assert "outside_scope" in reason

    def test_priority_inner_outputs_failure(self):
        """outputs[].ok=False 提取 handler/error（无 handler_failed/path_guard 时优先）。"""
        result = {
            "result": {
                "ok": False,
                "outputs": [
                    {
                        "handler": "code_writer",
                        "ok": False,
                        "error": "syntax error in generated file",
                        "detail": "line 42",
                    }
                ],
            }
        }

        reason = _extract_failure_reason(result, {})

        assert reason.startswith("output_failed:")
        assert "handler=code_writer" in reason
        assert "syntax error" in reason

    def test_priority_delivery_validation_failed(self):
        """delivery_validation.commands[].exit_code≠0 提取失败命令（2026-07-20 修复核心）。"""
        result = {
            "result": {
                "ok": False,
                "outputs": [
                    {
                        "handler": "para_delegate",
                        "ok": True,
                        "para_result": {
                            "delivery_validation": {
                                "commands": [
                                    {
                                        "command": "pytest tests/test_x.py",
                                        "exit_code": 1,
                                        "output_tail": "FAILED tests/test_x.py::test_a",
                                    }
                                ]
                            }
                        },
                    }
                ],
            }
        }

        reason = _extract_failure_reason(result, {})

        assert "delivery_validation_failed" in reason
        assert "exit=1" in reason
        assert "pytest tests/test_x.py" in reason

    def test_priority_para_error(self):
        """para_meta.error 提取（无 handler/path_guard/outputs/dv 时优先）。"""
        result = {"result": {"ok": False, "status": "completed"}}
        para_meta = {"error": "Para task timeout 900s"}

        reason = _extract_failure_reason(result, para_meta)

        assert reason.startswith("para_error:")
        assert "Para task timeout 900s" in reason

    def test_priority_para_status(self):
        """para_meta.para_status 非 completed/ok/success 提取。"""
        result = {"result": {"ok": False, "status": "completed"}}
        para_meta = {"para_status": "failed"}

        reason = _extract_failure_reason(result, para_meta)

        assert reason == "para_status=failed"

    def test_priority_inner_status_failed(self):
        """inner.status=failed 提取（无 para_meta 时优先）。"""
        result = {
            "result": {
                "ok": False,
                "status": "failed",
                "error": "agent gave up after max rounds",
            }
        }

        reason = _extract_failure_reason(result, {})

        assert reason.startswith("inner_status=failed:")
        assert "agent gave up" in reason

    def test_priority_report_marker_blocked_by_risk_middleware(self):
        """report 含 'blocked by risk middleware' 返回 blocked_by_risk_middleware。"""
        result = {
            "result": {
                "ok": False,
                "outputs": [{"message": "task blocked by risk middleware: forbidden path"}],
            }
        }

        reason = _extract_failure_reason(result, {})

        assert reason == "blocked_by_risk_middleware"

    def test_priority_report_marker_codex_cli_failed(self):
        """report 含 '[e2e-agent] codex cli 失败' 返回 codex_cli_failed。"""
        result = {
            "result": {
                "ok": False,
                "outputs": [{"message": "[e2e-agent] codex cli 失败: exit code 1"}],
            }
        }

        reason = _extract_failure_reason(result, {})

        assert reason == "codex_cli_failed"

    def test_fallback_ok_false_unknown_reason(self):
        """所有分支都不匹配时返回 'ok_false_unknown_reason'。"""
        result = {"result": {"ok": False, "status": "completed"}}

        reason = _extract_failure_reason(result, {})

        assert reason == "ok_false_unknown_reason"

    def test_delivery_validation_with_multiple_failed_commands(self):
        """多个失败命令拼接（最多 3 个）。"""
        dv = {
            "commands": [
                {"exit_code": 1, "command": "pytest a"},
                {"exit_code": 2, "command": "pytest b"},
                {"exit_code": 3, "command": "pytest c"},
                {"exit_code": 4, "command": "pytest d"},  # 超过 3 个，应被截断
            ]
        }
        result = {"result": {"ok": False, "delivery_validation": dv}}

        reason = _extract_failure_reason(result, {})

        assert "delivery_validation_failed" in reason
        assert "exit=1" in reason
        assert "exit=2" in reason
        assert "exit=3" in reason
        # 第 4 个不应出现
        assert "exit=4" not in reason

    def test_delivery_validation_truncates_long_output(self):
        """长 output_tail 截断到 120 字符。"""
        long_tail = "x" * 500
        dv = {"commands": [{"exit_code": 1, "command": "pytest", "output_tail": long_tail}]}
        result = {"result": {"ok": False, "delivery_validation": dv}}

        reason = _extract_failure_reason(result, {})

        assert "delivery_validation_failed" in reason
        # output_tail 被截断到 120 字符
        assert ("tail=" + "x" * 120) in reason
        # 不应包含完整的 500 字符
        assert "x" * 200 not in reason


# ---------------------------------------------------------------------------
# Task 5: KB schema auto-validate + retry on failure
# 验收：注入 KB schema 错误 → LOOP 自动评论 PR + 写 kb_schema_retry open_item；
#       retry_count >= 2 后标 needs-human；resume 触发 fresh code step。
# ---------------------------------------------------------------------------


def _kb_validation_failed_payload(file_name="FHD/XCAGI/kb/fixes/test.json"):
    """模拟 _validate_kb_json_changes_for_auto_merge 失败时的返回。"""
    return {
        "checked": [file_name],
        "errors": [
            {
                "error": "fix executable_template must be an object",
                "file": file_name,
                "kind": "fixes",
            }
        ],
        "ok": False,
        "reason": "kb_json_schema_validation_failed",
    }


def _seed_loop_memory_for_kb_retry(tmp_path, open_items):
    """把 open_items 写到 tmp_path 的 loop memory 文件中，返回 memory_path。"""
    memory_path = tmp_path / "loop_memory.json"
    memory_path.write_text(
        json.dumps(
            {
                "closed_items": [],
                "open_items": open_items,
                "recent_runs": [],
                "run_count": 0,
            }
        ),
        encoding="utf-8",
    )
    return memory_path


def test_resume_returns_none_when_kb_schema_retry_open_item_exists(monkeypatch, tmp_path):
    """非 escalated 的 kb_schema_retry open_item → resume 返 None 触发 fresh code step。"""
    _seed_loop_memory_for_kb_retry(
        tmp_path,
        [
            {
                "branch": "devfleet/codex/kb-bad-1",
                "created_at": "2026-07-20T12:00:00+00:00",
                "escalated": False,
                "kind": "kb_schema_retry",
                "para_task_id": "task-kb-1",
                "retry_count": 1,
                "run_id": "r-kb-1",
                "steps": ["code"],
            }
        ],
    )
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MEMORY", str(tmp_path / "loop_memory.json"))

    memory = _load_loop_memory()
    result = _resume_review_qa_candidate(memory)

    # 应该返回 None，让 loop 跑 fresh code step
    assert result is None


def test_resume_does_not_short_circuit_when_kb_schema_retry_escalated(monkeypatch, tmp_path):
    """escalated 的 kb_schema_retry open_item → resume 不短路，等人工。"""
    _seed_loop_memory_for_kb_retry(
        tmp_path,
        [
            {
                "branch": "devfleet/codex/kb-bad-1",
                "created_at": "2026-07-20T12:00:00+00:00",
                "escalated": True,
                "kind": "kb_schema_retry",
                "para_task_id": "task-kb-1",
                "retry_count": 2,
                "run_id": "r-kb-1",
                "steps": ["code"],
            }
        ],
    )
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MEMORY", str(tmp_path / "loop_memory.json"))

    memory = _load_loop_memory()
    result = _resume_review_qa_candidate(memory)

    # escalated 的项不应触发 fresh code step。result 可能是 None（因为没有其他
    # resume 候选）或其他 resume 候选；这里只验证它不是因为 kb_schema_retry 短路。
    # 由于没有其他 open_items，应该返回 None，但不是因为 kb_schema_retry。
    assert result is None


def test_existing_kb_schema_retry_item_matches_by_branch():
    """精确 branch 匹配优先。"""
    items = [
        {
            "branch": "devfleet/codex/kb-bad-1",
            "created_at": "2026-07-20T12:00:00+00:00",
            "escalated": False,
            "kind": "kb_schema_retry",
            "para_task_id": "task-kb-1",
            "retry_count": 1,
        },
        {
            "branch": "devfleet/codex/kb-bad-2",
            "created_at": "2026-07-20T13:00:00+00:00",
            "escalated": False,
            "kind": "kb_schema_retry",
            "para_task_id": "task-kb-2",
            "retry_count": 1,
        },
    ]
    found = _existing_kb_schema_retry_item(
        items, branch="devfleet/codex/kb-bad-2", para_task_id=None
    )
    assert found is not None
    assert found["branch"] == "devfleet/codex/kb-bad-2"


def test_existing_kb_schema_retry_item_matches_by_para_task_id():
    """para_task_id 精确匹配。"""
    items = [
        {
            "branch": "devfleet/codex/kb-bad-1",
            "created_at": "2026-07-20T12:00:00+00:00",
            "escalated": False,
            "kind": "kb_schema_retry",
            "para_task_id": "task-kb-1",
            "retry_count": 1,
        },
    ]
    found = _existing_kb_schema_retry_item(
        items, branch="different-branch", para_task_id="task-kb-1"
    )
    assert found is not None
    assert found["para_task_id"] == "task-kb-1"


def test_existing_kb_schema_retry_item_fallback_within_24h():
    """不同 branch/task 但 24h 内 → 返回最近项（避免 LLM 换 branch 重置 retry_count）。"""
    now = datetime.now(timezone.utc)
    items = [
        {
            "branch": "devfleet/codex/kb-bad-old",
            "created_at": (now - timedelta(hours=30)).isoformat(),  # >24h ago
            "escalated": False,
            "kind": "kb_schema_retry",
            "para_task_id": "task-kb-old",
            "retry_count": 1,
        },
        {
            "branch": "devfleet/codex/kb-bad-recent",
            "created_at": (now - timedelta(hours=2)).isoformat(),  # <24h ago
            "escalated": False,
            "kind": "kb_schema_retry",
            "para_task_id": "task-kb-recent",
            "retry_count": 1,
        },
    ]
    found = _existing_kb_schema_retry_item(
        items, branch="devfleet/codex/kb-new-branch", para_task_id="task-new"
    )
    assert found is not None
    assert found["branch"] == "devfleet/codex/kb-bad-recent"


def test_existing_kb_schema_retry_item_skips_escalated():
    """escalated 项被跳过。"""
    items = [
        {
            "branch": "devfleet/codex/kb-bad-1",
            "created_at": "2026-07-20T12:00:00+00:00",
            "escalated": True,
            "kind": "kb_schema_retry",
            "para_task_id": "task-kb-1",
            "retry_count": 2,
        },
    ]
    found = _existing_kb_schema_retry_item(
        items, branch="devfleet/codex/kb-bad-1", para_task_id="task-kb-1"
    )
    assert found is None


def test_reject_and_retry_kb_schema_first_failure_writes_open_item(monkeypatch, tmp_path):
    """第一次 schema 失败 → 写 kb_schema_retry open_item, retry_count=1, 未 escalated。"""
    memory_path = tmp_path / "loop_memory.json"
    _seed_loop_memory_for_kb_retry(tmp_path, [])
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MEMORY", str(memory_path))

    # Mock PR 操作（避免依赖 gh CLI）
    monkeypatch.setattr(loop_runner, "_find_pr_number_for_branch", lambda branch: 42)
    comment_calls = []
    monkeypatch.setattr(
        loop_runner,
        "_gh_pr_comment",
        lambda pr, body: comment_calls.append((pr, body)) or True,
    )
    label_calls = []
    monkeypatch.setattr(
        loop_runner,
        "_gh_pr_add_label",
        lambda pr, label: label_calls.append((pr, label)) or True,
    )
    monkeypatch.setattr(loop_runner, "_append_governance_audit", lambda record: None)
    monkeypatch.setattr(loop_runner, "_append_ledger", lambda record: None)

    final = _reject_and_retry_kb_schema_failure(
        run_id="run-kb-1",
        branch="devfleet/codex/kb-bad-1",
        para_task_id="task-kb-1",
        kb_validation=_kb_validation_failed_payload(),
        steps=[{"step": "code", "ok": True}],
        gate={},
    )

    # 验证 final 状态：必须是 kb_schema_failed，不能落成泛化 failed
    assert final["status"] == KB_SCHEMA_FAILED_STATUS
    assert final["status"] != "failed"
    assert final["failure_kind"] == KB_SCHEMA_FAILED_STATUS
    assert final["kb_schema_failed"] is True
    assert final["error"] == "kb_json_schema_validation_failed"
    assert final["failed_step"] == "code"
    assert final["kb_schema_retry"] is True
    assert final["policy_decision"]["action"] == "hold_for_automated_remediation"
    assert final["policy_decision"]["reason"] == "kb_json_schema_validation_failed"
    assert final["policy_decision"]["status"] == KB_SCHEMA_FAILED_STATUS
    assert (
        final["policy_decision"]["active_gates"]["kb_schema_gate"]["label"]
        == KB_SCHEMA_FAILED_LABEL
    )
    assert final["policy_decision"]["retry_count"] == 1
    assert final["policy_decision"]["escalated"] is False

    # 验证 PR 评论 + label
    assert comment_calls == [(42, comment_calls[0][1])]
    assert "KB JSON schema validation failed" in comment_calls[0][1]
    assert "executable_template must be an object" in comment_calls[0][1]
    assert (42, KB_SCHEMA_FAILED_LABEL) in label_calls
    # 第一次失败不应该标 needs-human
    assert (42, NEEDS_HUMAN_LABEL) not in label_calls

    # 验证 open_item 写入 loop memory
    memory = _load_loop_memory()
    kb_items = [i for i in memory["open_items"] if i.get("kind") == "kb_schema_retry"]
    assert len(kb_items) == 1
    assert kb_items[0]["retry_count"] == 1
    assert kb_items[0]["escalated"] is False
    assert kb_items[0]["branch"] == "devfleet/codex/kb-bad-1"
    assert kb_items[0]["para_task_id"] == "task-kb-1"


def test_reject_and_retry_kb_schema_second_failure_increments_retry_count(monkeypatch, tmp_path):
    """第二次 schema 失败（同 branch）→ retry_count=2, escalated=True, 标 needs-human。"""
    _seed_loop_memory_for_kb_retry(
        tmp_path,
        [
            {
                "branch": "devfleet/codex/kb-bad-1",
                "created_at": "2026-07-20T12:00:00+00:00",
                "escalated": False,
                "kind": "kb_schema_retry",
                "para_task_id": "task-kb-1",
                "retry_count": 1,
                "run_id": "run-kb-1",
                "steps": ["code"],
            }
        ],
    )
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MEMORY", str(tmp_path / "loop_memory.json"))

    monkeypatch.setattr(loop_runner, "_find_pr_number_for_branch", lambda branch: 42)
    label_calls = []
    monkeypatch.setattr(
        loop_runner,
        "_gh_pr_add_label",
        lambda pr, label: label_calls.append((pr, label)) or True,
    )
    monkeypatch.setattr(loop_runner, "_gh_pr_comment", lambda pr, body: True)
    monkeypatch.setattr(loop_runner, "_append_governance_audit", lambda record: None)
    monkeypatch.setattr(loop_runner, "_append_ledger", lambda record: None)

    final = _reject_and_retry_kb_schema_failure(
        run_id="run-kb-2",
        branch="devfleet/codex/kb-bad-1",
        para_task_id="task-kb-1",
        kb_validation=_kb_validation_failed_payload(),
        steps=[{"step": "code", "ok": True}],
        gate={},
    )

    # 第二次失败 → escalated
    assert final["policy_decision"]["retry_count"] == 2
    assert final["policy_decision"]["escalated"] is True
    assert final["status"] == "completed_waiting_human_strategy"
    assert (42, KB_SCHEMA_FAILED_LABEL) in label_calls
    assert (42, NEEDS_HUMAN_LABEL) in label_calls

    # open_item 应被刷新（不是新增）
    memory = _load_loop_memory()
    kb_items = [i for i in memory["open_items"] if i.get("kind") == "kb_schema_retry"]
    assert len(kb_items) == 1
    assert kb_items[0]["retry_count"] == 2
    assert kb_items[0]["escalated"] is True


def test_reject_and_retry_kb_schema_escalates_after_max_retries(monkeypatch, tmp_path):
    """retry_count >= KB_SCHEMA_RETRY_MAX (2) → 升级为 human review。"""
    # 验证 KB_SCHEMA_RETRY_MAX 常量是 2
    assert KB_SCHEMA_RETRY_MAX == 2

    _seed_loop_memory_for_kb_retry(
        tmp_path,
        [
            {
                "branch": "devfleet/codex/kb-bad-1",
                "created_at": "2026-07-20T12:00:00+00:00",
                "escalated": False,
                "kind": "kb_schema_retry",
                "para_task_id": "task-kb-1",
                "retry_count": 1,  # 已经失败过 1 次
                "run_id": "run-kb-1",
                "steps": ["code"],
            }
        ],
    )
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MEMORY", str(tmp_path / "loop_memory.json"))

    monkeypatch.setattr(loop_runner, "_find_pr_number_for_branch", lambda branch: 99)
    label_calls = []
    monkeypatch.setattr(
        loop_runner,
        "_gh_pr_add_label",
        lambda pr, label: label_calls.append((pr, label)) or True,
    )
    monkeypatch.setattr(loop_runner, "_gh_pr_comment", lambda pr, body: True)
    monkeypatch.setattr(loop_runner, "_append_governance_audit", lambda record: None)
    monkeypatch.setattr(loop_runner, "_append_ledger", lambda record: None)

    final = _reject_and_retry_kb_schema_failure(
        run_id="run-kb-2",
        branch="devfleet/codex/kb-bad-1",
        para_task_id="task-kb-1",
        kb_validation=_kb_validation_failed_payload(),
        steps=[{"step": "code", "ok": True}],
        gate={},
    )

    # 第二次失败 → escalated
    assert final["policy_decision"]["retry_count"] == 2
    assert final["policy_decision"]["escalated"] is True
    assert final["status"] == "completed_waiting_human_strategy"
    # needs-human label 被添加
    assert (99, NEEDS_HUMAN_LABEL) in label_calls


def test_reject_and_retry_kb_schema_uses_24h_fallback_for_new_branch(monkeypatch, tmp_path):
    """LLM 创建新 branch，但 24h 内有旧 kb_schema_retry → 增量 retry_count 而非重置。"""
    recent = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    _seed_loop_memory_for_kb_retry(
        tmp_path,
        [
            {
                "branch": "devfleet/codex/kb-bad-old",  # 旧 branch
                "created_at": recent,  # 相对「现在」仍在 24h 内
                "escalated": False,
                "kind": "kb_schema_retry",
                "para_task_id": "task-kb-old",
                "retry_count": 1,
                "run_id": "run-kb-old",
                "steps": ["code"],
            }
        ],
    )
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MEMORY", str(tmp_path / "loop_memory.json"))

    monkeypatch.setattr(loop_runner, "_find_pr_number_for_branch", lambda branch: None)
    monkeypatch.setattr(loop_runner, "_gh_pr_comment", lambda pr, body: True)
    monkeypatch.setattr(loop_runner, "_gh_pr_add_label", lambda pr, label: True)
    monkeypatch.setattr(loop_runner, "_append_governance_audit", lambda record: None)
    monkeypatch.setattr(loop_runner, "_append_ledger", lambda record: None)

    # 新 branch，不同 para_task_id
    final = _reject_and_retry_kb_schema_failure(
        run_id="run-kb-new",
        branch="devfleet/codex/kb-bad-new-branch",
        para_task_id="task-kb-new",
        kb_validation=_kb_validation_failed_payload(),
        steps=[{"step": "code", "ok": True}],
        gate={},
    )

    # 应该匹配到 24h 内的旧 item，retry_count 从 1 → 2，escalated
    assert final["policy_decision"]["retry_count"] == 2
    assert final["policy_decision"]["escalated"] is True


def test_reject_and_retry_kb_schema_handles_missing_pr_gracefully(monkeypatch, tmp_path):
    """没有 PR（gh 不可用）→ 跳过 PR 操作，仍然写 open_item。"""
    _seed_loop_memory_for_kb_retry(tmp_path, [])
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MEMORY", str(tmp_path / "loop_memory.json"))

    # _find_pr_number_for_branch 返 None
    monkeypatch.setattr(loop_runner, "_find_pr_number_for_branch", lambda branch: None)
    comment_calls = []
    label_calls = []
    monkeypatch.setattr(
        loop_runner,
        "_gh_pr_comment",
        lambda pr, body: comment_calls.append((pr, body)) or True,
    )
    monkeypatch.setattr(
        loop_runner,
        "_gh_pr_add_label",
        lambda pr, label: label_calls.append((pr, label)) or True,
    )
    monkeypatch.setattr(loop_runner, "_append_governance_audit", lambda record: None)
    monkeypatch.setattr(loop_runner, "_append_ledger", lambda record: None)

    _reject_and_retry_kb_schema_failure(
        run_id="run-kb-no-pr",
        branch="devfleet/codex/kb-no-pr",
        para_task_id=None,
        kb_validation=_kb_validation_failed_payload(),
        steps=[{"step": "code", "ok": True}],
        gate={},
    )

    # 不应该调用 PR 评论/label
    assert comment_calls == []
    assert label_calls == []
    # open_item 仍然写入
    memory = _load_loop_memory()
    kb_items = [i for i in memory["open_items"] if i.get("kind") == "kb_schema_retry"]
    assert len(kb_items) == 1
    assert kb_items[0]["retry_count"] == 1


def test_code_task_text_includes_strict_kb_schema_example_and_validate_instruction():
    """员工 prompt 必须包含：完整 KB JSON schema 示例 + pre-push validate 强制指令 + kb-schema-failed 警告。"""
    text = _code_task_text(
        "run-prompt-test",
        {"gaps": ["test_gap"]},
        {"open_items": [], "recent_runs": []},
    )

    # 1. 包含完整 schema 示例（executable_template 嵌套结构）
    assert '"schema_version": 1' in text
    assert '"kind": "fix"' in text
    assert '"executable_template":' in text
    assert '"applicability_check":' in text
    assert '"patch_strategy":' in text
    assert '"rollback_plan":' in text
    assert '"required_tests":' in text

    # 2. 包含 pre-push validate 强制指令
    assert "validate_kb_payload" in text
    assert "MANDATORY PRE-PUSH VALIDATION" in text

    # 3. 警告 kb-schema-failed label 和重试机制
    assert "kb-schema-failed" in text
    assert "needs-human" in text or "human review" in text

    # 4. 强调 executable_template 必须是 object（cedde773 的失败原因）
    assert "executable_template MUST be an object" in text

    # 5. 质量门必须显式出现在真正派发给 code 员工的 prompt 中
    assert "OUTPUT QUALITY REQUIREMENTS" in text
    assert "safety_score_v2 target of at least 90" in text
    assert "smallest production change" in text
    assert "independent report-only employees" in text


def test_score_remediation_prompt_keeps_employee_on_isolated_work_branch():
    text = _code_task_text(
        "run-prompt-remediation",
        {"gaps": ["missing focused test"]},
        {"open_items": [], "recent_runs": []},
        {
            "branch": "devfleet/codex/immutable-candidate",
            "failed_run_id": "failed-run",
            "reason": "resume_safety_score_remediation",
        },
    )

    assert "newly created isolated remediation work branch" in text
    assert "immutable base is `devfleet/codex/immutable-candidate`" in text
    assert "Do not checkout, switch to, reset, commit, or push directly" in text
    assert "push HEAD to that same work-branch name" in text


def test_gh_pr_add_label_is_best_effort_and_returns_false_on_failure(monkeypatch):
    """gh 命令失败时返回 False，不抛异常。"""
    import subprocess as _sp

    def fake_run(*args, **kwargs):
        return _sp.CompletedProcess(
            args=args[0] if args else kwargs.get("args"),
            returncode=1,
            stdout="",
            stderr="label not found",
        )

    monkeypatch.setattr(_sp, "run", fake_run)
    monkeypatch.setenv("GITHUB_REPO", "test/repo")

    result = _gh_pr_add_label(42, "nonexistent-label")
    assert result is False


def test_find_pr_number_for_branch_returns_none_on_gh_failure(monkeypatch):
    """gh CLI 不可用时返 None。"""
    import subprocess as _sp

    def fake_run(*args, **kwargs):
        return _sp.CompletedProcess(
            args=args[0] if args else kwargs.get("args"),
            returncode=127,
            stdout="",
            stderr="gh: command not found",
        )

    monkeypatch.setattr(_sp, "run", fake_run)
    monkeypatch.setenv("GITHUB_REPO", "test/repo")

    result = _find_pr_number_for_branch("any-branch")
    assert result is None


def test_over_retry_non_code_duplicate_enqueue_removes_item(monkeypatch):
    """人工队列返回 duplicate 时视为已升级，应从 open_items 移除。"""
    from modstore_server import self_maintenance_loop_runner as loop_runner

    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MAX_RETRIES", "3")

    item = {
        "branch": "devfleet/codex/review-dup",
        "created_at": "2026-07-24T00:00:00+00:00",
        "kind": "failed_steps",
        "para_task_id": "task-dup",
        "retry_count": 3,
        "run_id": "run-dup",
        "steps": ["review"],
    }
    memory = {"open_items": [item], "recent_runs": []}

    def fake_enqueue(**kwargs):
        return {"queued": False, "reason": "duplicate", "fingerprint": "abc"}

    monkeypatch.setattr(
        "modstore_server.human_uncertainty_queue.enqueue_uncertain_item",
        fake_enqueue,
    )

    result = loop_runner._resume_review_qa_candidate(memory)

    assert result is None
    assert memory["open_items"] == []
    assert item.get("escalated") is True


def test_over_retry_non_code_items_not_marked_escalated_on_enqueue_failure(monkeypatch, caplog):
    """入队失败的非code项不应被标记为escalated，应留在open_items等待下次重试。"""
    from modstore_server import self_maintenance_loop_runner as loop_runner

    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MAX_RETRIES", "3")

    # Mock enqueue to fail
    def fake_enqueue(*args, **kwargs):
        return {"queued": False}

    monkeypatch.setattr(
        "modstore_server.human_uncertainty_queue.enqueue_uncertain_item",
        fake_enqueue,
    )

    memory = {
        "open_items": [
            {
                "kind": "failed_steps",
                "steps": ["review"],
                "retry_count": 3,
                "run_id": "failed-enqueue-run",
                "branch": "devfleet/test/branch",
                "para_task_id": "task-1",
            }
        ],
        "recent_runs": [],
    }

    with caplog.at_level("WARNING"):
        result = loop_runner._resume_review_qa_candidate(memory)

    # 入队失败的项不应被标记为escalated
    item = memory["open_items"][0]
    assert item.get("escalated") is not True
    # 项应保留在open_items中
    assert len(memory["open_items"]) == 1
    # 应打印重试日志
    assert "will retry next loop" in caplog.text
    # 没有成功入队的项，应返回None（hold）
    assert result is None


def test_enqueue_success_matching_uses_composite_key_not_only_run_id(monkeypatch):
    """使用复合键（run_id+branch+task_id+steps）匹配成功入队项，run_id为None时也能正确删除。"""
    from modstore_server import self_maintenance_loop_runner as loop_runner

    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MAX_RETRIES", "3")

    enqueue_calls = []

    def fake_enqueue(context, **kwargs):
        enqueue_calls.append(context)
        return {"queued": True}

    monkeypatch.setattr(
        "modstore_server.human_uncertainty_queue.enqueue_uncertain_item",
        fake_enqueue,
    )

    # 两个项有相同的run_id=None，其他字段不同
    memory = {
        "open_items": [
            {
                "kind": "failed_steps",
                "steps": ["qa"],
                "retry_count": 3,
                "run_id": None,
                "branch": "devfleet/test/branch-1",
                "para_task_id": "task-1",
            },
            {
                "kind": "failed_steps",
                "steps": ["qa"],
                "retry_count": 3,
                "run_id": None,
                "branch": "devfleet/test/branch-2",
                "para_task_id": "task-2",
            },
        ],
        "recent_runs": [],
    }

    result = loop_runner._resume_review_qa_candidate(memory)

    # 两个项都成功入队，应从open_items中移除
    assert len(memory["open_items"]) == 0
    assert len(enqueue_calls) == 2
    assert result is None


def test_escalated_failed_steps_do_not_block_other_branch_remediation(monkeypatch):
    """Exhausted QA on one branch must not prevent code resume on another hold."""
    from modstore_server import self_maintenance_loop_runner as loop_runner

    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MAX_RETRIES", "3")
    monkeypatch.setattr(
        "modstore_server.human_uncertainty_queue.enqueue_uncertain_item",
        lambda *args, **kwargs: {"queued": True},
    )

    memory = {
        "open_items": [
            {
                "branch": "devfleet/cursor/sub-1-29b56e",
                "kind": "failed_steps",
                "para_task_id": "b3fd2376-34fd-4c14-91da-0e773229b56e",
                "retry_count": 3,
                "run_id": "f3e7bd4a-87df-4ed6-a95f-b8beaf747c32",
                "steps": ["qa"],
            },
            {
                "branch": "devfleet/cursor/sub-1-latest",
                "kind": "automated_remediation",
                "reason": "structured_review_blocking_findings",
                "run_id": "run-latest-hold",
                "task_id": "task-latest",
            },
        ],
        "recent_runs": [],
    }

    result = loop_runner._resume_review_qa_candidate(memory)

    assert result == {
        "branch": "devfleet/cursor/sub-1-latest",
        "failed_run_id": "run-latest-hold",
        "failed_steps": ["code"],
        "para_task_id": "task-latest",
        "reason": "resume_automated_remediation_candidate",
    }
    assert len(memory["open_items"]) == 1
    assert memory["open_items"][0]["reason"] == "structured_review_blocking_findings"


def test_para_ai_review_veto_not_starved_by_stale_review_failed_steps():
    """A newer Para merge-review veto must resume code before stale review holds."""
    from modstore_server import self_maintenance_loop_runner as loop_runner

    memory = {
        "open_items": [
            {
                "branch": "devfleet/cursor/sub-1-stale",
                "kind": "failed_steps",
                "para_task_id": "task-stale",
                "retry_count": 1,
                "run_id": "run-stale",
                "steps": ["review"],
            },
            {
                "branch": "devfleet/cursor/sub-1-veto",
                "detail": "devfleet/cursor/sub-1-veto: indeterminate-review",
                "kind": "automated_remediation",
                "para_task_id": "task-veto",
                "reason": "para_ai_review_rejected",
                "run_id": "run-veto",
                "review_feedback": "devfleet/cursor/sub-1-veto: indeterminate-review",
            },
        ],
        "recent_runs": [
            {
                "branch": "devfleet/cursor/sub-1-stale",
                "para_task_id": "task-stale",
                "run_id": "run-stale",
            }
        ],
    }

    result = loop_runner._resume_review_qa_candidate(memory)

    assert result is not None
    assert result["reason"] == "resume_para_ai_review_rejection"
    assert result["branch"] == "devfleet/cursor/sub-1-veto"
    assert result["para_task_id"] == "task-veto"
    assert result["failed_steps"] == ["code"]
    assert result["review_veto_code"] == "indeterminate-review"


def test_code_failure_items_log_correct_message_not_escalating_to_human(monkeypatch, caplog):
    """code类失败项应打印代码重试日志，而不是escalating to human review。"""
    from modstore_server import self_maintenance_loop_runner as loop_runner

    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MAX_RETRIES", "3")

    memory = {
        "open_items": [
            {
                "kind": "failed_steps",
                "steps": ["code"],
                "retry_count": 3,
                "run_id": "code-failure-run",
                "branch": "devfleet/test/branch",
                "para_task_id": "task-code",
            }
        ],
        "recent_runs": [],
    }

    with caplog.at_level("WARNING"):
        result = loop_runner._resume_review_qa_candidate(memory)

    # code项不应被escalated，也不应入队人工队列
    item = memory["open_items"][0]
    assert item.get("escalated") is not True
    assert len(memory["open_items"]) == 1
    # 应打印代码重试日志，而不是人工评审日志
    assert "will retry code remediation" in caplog.text
    assert "escalating to human review" not in caplog.text
    assert result is None


def test_run_cmd_excerpt_truncates_and_terminates_large_output_quickly():
    import sys
    import time

    from modstore_server.self_maintenance_subprocess import run_cmd_excerpt

    args = [
        sys.executable,
        "-c",
        "import sys; sys.stdout.write('a' * 100000); sys.stdout.flush()",
    ]
    started = time.monotonic()
    out = run_cmd_excerpt(args, max_chars=200, timeout=180)
    elapsed = time.monotonic() - started
    assert len(out) == 200
    assert elapsed < 15


def test_run_cmd_excerpt_raises_on_nonzero_when_fully_read():
    import sys

    from modstore_server.self_maintenance_subprocess import run_cmd_excerpt

    with pytest.raises(RuntimeError, match="command failed"):
        run_cmd_excerpt(
            [sys.executable, "-c", "import sys; sys.exit(2)"],
            max_chars=10_000,
        )


def test_run_cmd_excerpt_accepts_truncated_success_despite_late_exit():
    import sys

    from modstore_server.self_maintenance_subprocess import run_cmd_excerpt

    script = "import sys\n" "sys.stdout.write('z' * 50000)\n" "sys.stdout.flush()\n" "sys.exit(0)\n"
    out = run_cmd_excerpt(
        [sys.executable, "-c", script],
        max_chars=128,
    )
    assert out == "z" * 128


def test_run_cmd_excerpt_raises_on_nonzero_when_truncated():
    import sys

    from modstore_server.self_maintenance_subprocess import run_cmd_excerpt

    script = "import sys\n" "sys.stdout.write('x' * 50000)\n" "sys.stdout.flush()\n" "sys.exit(2)\n"
    with pytest.raises(RuntimeError, match="command failed"):
        run_cmd_excerpt(
            [sys.executable, "-c", script],
            max_chars=128,
        )
