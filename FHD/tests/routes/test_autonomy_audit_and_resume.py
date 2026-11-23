from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.autonomy.approval_resume import (
    ApprovalStateError,
    complete_action,
    get_action_state,
    mark_approval_requested,
    request_action,
    resume_action,
)
from app.domain.autonomy.autonomy_guard import reload_autonomy_guard
from app.fastapi_routes import ops_autonomy, xcmax_admin


def _isolate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XCAGI_AUTONOMY_AUDIT_DB_PATH", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setenv("XCAGI_AUTONOMY_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("XCAGI_AUTONOMY_METRICS_LOG_PATH", str(tmp_path / "metrics.jsonl"))
    monkeypatch.setenv("XCAGI_AUTONOMY_APPROVAL_LEDGER_PATH", str(tmp_path / "approval.jsonl"))
    monkeypatch.delenv("XCAGI_AUTONOMY_MEDIUM_RISK_POLICY", raising=False)
    reload_autonomy_guard()


def test_self_maintenance_resume_keeps_original_approval_and_real_merge_evidence_gate(
    tmp_path, monkeypatch
) -> None:
    _isolate(tmp_path, monkeypatch)
    repository = Path(__file__).resolve().parents[3]
    monkeypatch.syspath_prepend(str(repository / "成都修茈科技有限公司/MODstore_deploy"))
    from modstore_server.maintenance_loop import para_client, workspace

    monkeypatch.setenv("MODSTORE_PARA_REPO_URL", "https://github.com/example/repo.git")
    monkeypatch.setenv("MODSTORE_PARA_BRANCH", "main")
    monkeypatch.setenv("MODSTORE_PARA_API_BASE", "http://127.0.0.1:3001")
    monkeypatch.setenv("MODSTORE_AUTO_MERGE_ALLOW_REMOTE", "1")

    def must_not_request_merge(*_args, **_kwargs):
        pytest.fail("human approval bypassed the original merge evidence gate")

    monkeypatch.setattr(workspace, "_remote_branch_head", must_not_request_merge)
    monkeypatch.setattr(para_client, "_request_para_task_merge", must_not_request_merge)
    action_id = "original-maintenance-approval"
    decision, pending = request_action(
        "self_maintenance_merge",
        action_id=action_id,
        executor_name="self_maintenance_merge",
        payload={
            "run_id": "original-loop",
            "task_id": "original-task",
            "branch": "original-candidate",
            "steps": [{"step": "review", "report_excerpt": "review evidence is unavailable"}],
            "_approval": {"approver": "spoofed-payload-actor"},
        },
    )
    assert decision.risk_level.name == "HIGH" and decision.allowed is False
    assert pending is not None and pending["state"] == "pending_approval"
    with pytest.raises(ApprovalStateError, match="approver is required"):
        resume_action(action_id, approver="")
    assert get_action_state(action_id)["state"] == "pending_approval"

    result = resume_action(action_id, approver="human-reviewer", approval_id="204")
    assert result["state"] == "execution_failed"
    assert result["approver"] == "human-reviewer" and result["approval_id"] == "204"
    assert result["outcome"]["ok"] is False
    assert result["outcome"]["reason"] == "missing_structured_review_object"
    assert result["outcome"]["structured_report_gate"]["ok"] is False
    assert not result["outcome"].get("merge_requested")
    with pytest.raises(ApprovalStateError, match="not pending"):
        resume_action(action_id, approver="human-reviewer", approval_id="204")
    states = [
        json.loads(line)["state"] for line in (tmp_path / "approval.jsonl").read_text().splitlines()
    ]
    assert states == ["pending_approval", "approved", "execution_failed"]


def test_self_maintenance_resume_retains_original_remote_request_receipt(tmp_path, monkeypatch):
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    _isolate(tmp_path, monkeypatch)
    repository = Path(__file__).resolve().parents[3]
    monkeypatch.syspath_prepend(str(repository / "成都修茈科技有限公司/MODstore_deploy"))
    from modstore_server import autonomy_decision_audit
    from modstore_server.db.autonomy_decisions import AutonomyDecisionAudit
    from modstore_server.maintenance_loop import para_client, workspace

    focused = "python3 -m pytest focused.py -q"
    for key, value in {
        "XCAGI_FHD_RUNTIME_ROOT": str(repository / "FHD"),
        "XCAGI_AUTONOMY_DATA_DIR": str(tmp_path / "autonomy"),
        "MODSTORE_PARA_REPO_URL": "https://github.com/example/repo.git",
        "MODSTORE_PARA_BRANCH": "main",
        "MODSTORE_PARA_API_BASE": "http://127.0.0.1:3001",
        "MODSTORE_AUTO_MERGE_ALLOW_REMOTE": "1",
        "MODSTORE_SELF_MAINTENANCE_FOCUSED_TEST_COMMAND": focused,
        "MODSTORE_SELF_MAINTENANCE_LEDGER": str(tmp_path / "merge.jsonl"),
        "MODSTORE_SELF_MAINTENANCE_GOVERNANCE_AUDIT": str(tmp_path / "governance.jsonl"),
    }.items():
        monkeypatch.setenv(key, value)
    reports = {
        "review": {
            "max_severity": "low",
            "risk_class": "low",
            "dimensions": {
                key: {"status": "pass", "findings": []}
                for key in ("security", "business_logic", "performance")
            },
        },
        "qa": {
            "verdict": "PASS",
            "quality_checks": {
                key: {"command": command, "exit_code": 0, "status": "passed"}
                for key, command in {
                    "black": "python3 -m black --check modman/ modstore_server/ tests/",
                    "isort": "python3 -m isort --check-only --diff modman/ modstore_server/ tests/",
                    "source_governance": "python3 scripts/dev/source_governance.py --top 10",
                }.items()
            },
        },
    }
    steps = [
        {
            "step": name,
            "report_excerpt": json.dumps(
                {
                    "target_branch_available": True,
                    "blocking_findings": [],
                    "tested_commands": [{"command": focused, "exit_code": 0, "status": "passed"}],
                    **report,
                }
            ),
        }
        for name, report in reports.items()
    ]
    requests = []
    monkeypatch.setattr(
        workspace,
        "_remote_branch_head",
        lambda _repo, branch: "a" * 40 if branch == "main" else "b" * 40,
    )
    receipt = {"accepted": True, "task_id": "original-task"}
    monkeypatch.setattr(
        para_client, "_request_para_task_merge", lambda **kwargs: requests.append(kwargs) or receipt
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'merge-audit.sqlite'}")
    AutonomyDecisionAudit.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(autonomy_decision_audit, "get_session_factory", lambda: factory)
    try:
        request_action(
            "self_maintenance_merge",
            action_id="original-merge-request",
            executor_name="self_maintenance_merge",
            payload={
                "run_id": "original-loop",
                "task_id": "original-task",
                "branch": "candidate",
                "steps": steps,
            },
        )
        result = resume_action(
            "original-merge-request", approver="human-reviewer", approval_id="205"
        )
        assert result["state"] == "executed" and result["approver"] == "human-reviewer"
        assert result["outcome"]["merge_requested"] is True
        assert result["outcome"]["para_request"] == receipt
        rows = [json.loads(line) for line in (tmp_path / "merge.jsonl").read_text().splitlines()]
        assert len(rows) == 1 and rows[0]["status"] == "pending"
        assert rows[0]["run_id"] == "original-loop" and rows[0]["para_task_id"] == "original-task"
        assert rows[0]["branch"] == "candidate" and rows[0]["branch_head_sha"] == "b" * 40
        assert rows[0]["base_head_sha"] == "a" * 40
        with factory() as db:
            decision = db.scalar(select(AutonomyDecisionAudit))
            assert decision.action == "self_maintenance_l1_merge" and decision.decision == "allow"
        with pytest.raises(ApprovalStateError, match="not pending"):
            resume_action("original-merge-request", approver="human-reviewer", approval_id="205")
        assert requests == [{"api_base": "http://127.0.0.1:3001", "task_id": "original-task"}]
    finally:
        engine.dispose()


def test_request_route_requires_explicit_fresh_retry(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    action_id = "release:" + "d" * 40
    request_action("apply_release_to_cvm", action_id=action_id)
    resume_action(action_id, approver="reviewer", approval_id="200", defer_execution=True)
    complete_action(action_id, success=False, approval_id="200")
    monkeypatch.setattr(ops_autonomy, "_auth", lambda *args, **kwargs: None)
    app = FastAPI()
    app.include_router(ops_autonomy.router)
    payload = {"action": "apply_release_to_cvm", "action_id": action_id}
    with TestClient(app) as client:
        route = "/api/ops/autonomy/actions/request"
        assert client.post(route, json=payload).json()["state"] == "execution_failed"
        assert client.post(route, json={**payload, "retry_failed": "true"}).status_code == 400
        assert client.post(route, json={**payload, "retry_failed": True}).status_code == 409
        response = client.post(
            route, json={**payload, "retry_failed": True, "retry_approval_id": "201"}
        )
        assert response.status_code == 200
        assert response.json()["state"] == "pending_approval"


def test_admin_audit_log_endpoint_returns_highlighted_veto(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("XCAGI_AUTONOMY_MEDIUM_RISK_POLICY", "require_human")
    reload_autonomy_guard()
    request_action("rollback_release", action_id="audit-route", source="route-test")
    monkeypatch.setattr(xcmax_admin, "_require_market_admin_session", lambda request: None)
    app = FastAPI()
    app.include_router(xcmax_admin.router)
    client = TestClient(app)
    client.__enter__()
    response = client.get("/api/xcmax/admin/autonomy/audit-log?veto_only=true&days=30")
    assert response.status_code == 200
    body = response.json()
    assert body["append_only"] is True
    assert body["items"]
    assert all(item["highlighted"] for item in body["items"])
    assert body["summary"]["veto_count"] >= 1
    assert body["evaluation"]["status"] == "collecting"
    assert body["evaluation"]["window_days"] == 30
    client.__exit__(None, None, None)


def test_github_approval_callback_resumes_and_rejects(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("XCAGI_AUTONOMY_MEDIUM_RISK_POLICY", "require_human")
    reload_autonomy_guard()
    outcomes: list[str] = []
    request_action(
        "rollback_release",
        action_id="github-approve",
        source="route-test",
        executor=lambda payload: outcomes.append("executed") or {"ok": True},
    )
    request_action(
        "rollback_release",
        action_id="github-reject",
        source="route-test",
        executor=lambda payload: outcomes.append("must-not-run") or {"ok": True},
    )
    monkeypatch.setattr(ops_autonomy, "_auth", lambda *args, **kwargs: None)
    app = FastAPI()
    app.include_router(ops_autonomy.router)
    client = TestClient(app)
    client.__enter__()

    approved = client.post(
        "/api/ops/autonomy/github-approval",
        headers={"X-GitHub-Actor": "42433422"},
        json={
            "action_id": "github-approve",
            "decision": "approved",
            "approval_id": "deployment-42",
        },
    )
    assert approved.status_code == 200
    assert approved.json()["action"]["state"] == "executed"
    assert outcomes == ["executed"]

    rejected = client.post(
        "/api/ops/autonomy/github-approval",
        headers={"X-GitHub-Actor": "42433422"},
        json={"action_id": "github-reject", "decision": "rejected"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["action"]["state"] == "rejected"
    retry = client.post(
        "/api/ops/autonomy/github-approval",
        headers={"X-GitHub-Actor": "42433422"},
        json={"action_id": "github-reject", "decision": "approved"},
    )
    assert retry.status_code == 409
    assert outcomes == ["executed"]
    client.__exit__(None, None, None)


def test_workflow_dispatch_state_machine_and_prohibited_probe(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("XCAGI_AUTONOMY_MEDIUM_RISK_POLICY", "require_human")
    reload_autonomy_guard()
    monkeypatch.setattr(ops_autonomy, "_auth", lambda *args, **kwargs: None)
    app = FastAPI()
    app.include_router(ops_autonomy.router)
    client = TestClient(app)
    client.__enter__()

    prohibited = client.post(
        "/api/ops/autonomy/actions/evaluate",
        json={"action": "db_migration", "action_id": "blocked-real-probe"},
    )
    assert prohibited.status_code == 403

    requested = client.post(
        "/api/ops/autonomy/actions/request",
        json={"action": "freeze_manifest", "action_id": "workflow-freeze"},
    )
    assert requested.status_code == 200
    assert requested.json()["state"] == "pending_approval"
    dispatched = client.post(
        "/api/ops/autonomy/github-approval",
        json={
            "action_id": "workflow-freeze",
            "decision": "approval_requested",
            "approval_id": "dispatcher-1",
            "approver": "github-actions",
        },
    )
    assert dispatched.status_code == 200
    assert dispatched.json()["action"]["state"] == "approval_requested"
    approved = client.post(
        "/api/ops/autonomy/github-approval",
        json={
            "action_id": "workflow-freeze",
            "decision": "approved",
            "approval_id": "deployment-1",
            "approver": "42433422",
            "workflow_action": "freeze-manifest",
            "defer_execution": True,
        },
    )
    assert approved.status_code == 200
    assert approved.json()["action"]["state"] == "approved"
    executed = client.post(
        "/api/ops/autonomy/github-approval",
        json={
            "action_id": "workflow-freeze",
            "decision": "executed",
            "approval_id": "deployment-1",
            "approver": "42433422",
            "workflow_action": "freeze-manifest",
            "outcome": {"marker": "created"},
        },
    )
    assert executed.status_code == 200
    assert executed.json()["action"]["state"] == "executed"

    invalid = client.post(
        "/api/ops/autonomy/actions/request",
        json={"action": "freeze_manifest", "action_id": "bad id\nworkflow"},
    )
    assert invalid.status_code == 400
    client.__exit__(None, None, None)


def test_admin_approver_identity_comes_from_authenticated_session(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
        lambda request: "private-session-token",
    )
    monkeypatch.setattr(
        "app.application.session_account_meta.load_session_account_meta",
        lambda session_id: {
            "account_kind": "admin",
            "market_is_admin": True,
            "market_user_id": 42,
        },
    )

    assert xcmax_admin._admin_approver_from_session(object()) == "market-admin:42"


def test_admin_pending_resume_reject_use_session_not_webhook(tmp_path, monkeypatch) -> None:
    """管理端审批中心走 /api/xcmax/admin/autonomy/*，管理员会话即可，无需 webhook token。"""
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("XCAGI_AUTONOMY_MEDIUM_RISK_POLICY", "require_human")
    reload_autonomy_guard()
    executed_by_admin: list[str] = []
    request_action(
        "rollback_release",
        action_id="admin-pending-1",
        source="route-test",
        executor=lambda payload: (
            executed_by_admin.append(str((payload.get("_approval") or {}).get("approver") or ""))
            or {"ok": True}
        ),
    )
    request_action("rollback_release", action_id="admin-pending-2", source="route-test")
    request_action("rollback_release", action_id="admin-no-executor", source="route-test")
    request_action(
        "rollback_release",
        action_id="admin-external-callback",
        source="route-test",
        executor=lambda payload: {"ok": True},
    )
    mark_approval_requested(
        "admin-external-callback",
        approval_id="github-environment-7",
    )
    monkeypatch.setattr(xcmax_admin, "_require_market_admin_session", lambda request: None)
    monkeypatch.setattr(
        xcmax_admin,
        "_admin_approver_from_session",
        lambda request: "console-admin",
    )
    app = FastAPI()
    app.include_router(xcmax_admin.router)
    client = TestClient(app)
    client.__enter__()

    pending = client.get("/api/xcmax/admin/autonomy/actions/pending")
    assert pending.status_code == 200
    body = pending.json()
    assert body["ok"] is True
    assert body["count"] >= 2
    assert body["summary"]["waiting"] >= 2
    assert body["summary"]["actionable"] == 1
    ids = {item["action_id"] for item in body["items"]}
    assert "admin-pending-1" in ids
    assert "admin-pending-2" in ids

    resumed = client.post(
        "/api/xcmax/admin/autonomy/actions/admin-pending-1/resume",
        json={"approver": "spoofed-browser-actor"},
    )
    assert resumed.status_code == 200
    assert resumed.json()["execution_dispatched"] is True
    assert resumed.json()["action"]["state"] == "executed"
    assert resumed.json()["action"]["approver"] == "console-admin"
    assert executed_by_admin == ["console-admin"]

    unavailable = client.post(
        "/api/xcmax/admin/autonomy/actions/admin-no-executor/resume",
        json={"approver": "spoofed-browser-actor", "defer_execution": True},
    )
    assert unavailable.status_code == 409
    assert unavailable.json()["code"] == "executor_unavailable"
    still_pending = client.get("/api/xcmax/admin/autonomy/actions/pending").json()["items"]
    assert any(item["action_id"] == "admin-no-executor" for item in still_pending)

    external = client.post(
        "/api/xcmax/admin/autonomy/actions/admin-external-callback/resume",
        json={"approver": "spoofed-browser-actor", "defer_execution": True},
    )
    assert external.status_code == 409
    assert external.json()["code"] == "external_callback"
    still_pending = client.get("/api/xcmax/admin/autonomy/actions/pending").json()["items"]
    assert any(
        item["action_id"] == "admin-external-callback" and item["state"] == "approval_requested"
        for item in still_pending
    )

    rejected = client.post(
        "/api/xcmax/admin/autonomy/actions/admin-pending-2/reject",
        json={"approver": "spoofed-browser-actor", "reason": "nope"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["action"]["state"] == "rejected"
    assert rejected.json()["action"]["approver"] == "console-admin"
    client.__exit__(None, None, None)
