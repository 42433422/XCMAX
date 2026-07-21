from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.autonomy.approval_resume import request_action
from app.domain.autonomy.autonomy_guard import reload_autonomy_guard
from app.fastapi_routes import ops_autonomy, xcmax_admin


def _isolate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XCAGI_AUTONOMY_AUDIT_DB_PATH", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setenv("XCAGI_AUTONOMY_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("XCAGI_AUTONOMY_METRICS_LOG_PATH", str(tmp_path / "metrics.jsonl"))
    monkeypatch.setenv("XCAGI_AUTONOMY_APPROVAL_LEDGER_PATH", str(tmp_path / "approval.jsonl"))
    monkeypatch.delenv("XCAGI_AUTONOMY_MEDIUM_RISK_POLICY", raising=False)
    reload_autonomy_guard()


def test_admin_audit_log_endpoint_returns_highlighted_veto(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("XCAGI_AUTONOMY_MEDIUM_RISK_POLICY", "require_human")
    reload_autonomy_guard()
    request_action("rollback_release", action_id="audit-route", source="route-test")
    monkeypatch.setattr(xcmax_admin, "_require_market_admin_session", lambda request: None)
    app = FastAPI()
    app.include_router(xcmax_admin.router)
    response = TestClient(app).get("/api/xcmax/admin/autonomy/audit-log?veto_only=true&days=30")
    assert response.status_code == 200
    body = response.json()
    assert body["append_only"] is True
    assert body["items"]
    assert all(item["highlighted"] for item in body["items"])
    assert body["summary"]["veto_count"] >= 1
    assert body["evaluation"]["status"] == "collecting"
    assert body["evaluation"]["window_days"] == 30


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


def test_workflow_dispatch_state_machine_and_prohibited_probe(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("XCAGI_AUTONOMY_MEDIUM_RISK_POLICY", "require_human")
    reload_autonomy_guard()
    monkeypatch.setattr(ops_autonomy, "_auth", lambda *args, **kwargs: None)
    app = FastAPI()
    app.include_router(ops_autonomy.router)
    client = TestClient(app)

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


def test_admin_pending_resume_reject_use_session_not_webhook(tmp_path, monkeypatch) -> None:
    """管理端审批中心走 /api/xcmax/admin/autonomy/*，管理员会话即可，无需 webhook token。"""
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("XCAGI_AUTONOMY_MEDIUM_RISK_POLICY", "require_human")
    reload_autonomy_guard()
    request_action("rollback_release", action_id="admin-pending-1", source="route-test")
    request_action("rollback_release", action_id="admin-pending-2", source="route-test")
    monkeypatch.setattr(xcmax_admin, "_require_market_admin_session", lambda request: None)
    monkeypatch.setattr(
        xcmax_admin,
        "_admin_approver_from_session",
        lambda request, body_approver="": str(body_approver or "console-admin"),
    )
    app = FastAPI()
    app.include_router(xcmax_admin.router)
    client = TestClient(app)

    pending = client.get("/api/xcmax/admin/autonomy/actions/pending")
    assert pending.status_code == 200
    body = pending.json()
    assert body["ok"] is True
    assert body["count"] >= 2
    ids = {item["action_id"] for item in body["items"]}
    assert "admin-pending-1" in ids
    assert "admin-pending-2" in ids

    resumed = client.post(
        "/api/xcmax/admin/autonomy/actions/admin-pending-1/resume",
        json={"approver": "alice"},
    )
    assert resumed.status_code == 200
    assert resumed.json()["action"]["state"] == "approved"

    rejected = client.post(
        "/api/xcmax/admin/autonomy/actions/admin-pending-2/reject",
        json={"approver": "bob", "reason": "nope"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["action"]["state"] == "rejected"
