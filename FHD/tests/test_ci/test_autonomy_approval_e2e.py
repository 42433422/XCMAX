"""端到端集成测试：CI ingest → 管理端 pending → resume/reject → audit。

验证 spec「自治 escalate 打通管理端审批中心」的完整链路：
1. CI 侧调 /actions/ingest 写入待办（非白名单 action，如 self_maintenance_merge）
2. 管理端 GET /actions/pending 看到待办
3. 管理端 POST /actions/{id}/resume 通过（defer_execution）→ state=approved
4. 管理端 POST /actions/{id}/reject 拒绝 → state=rejected
5. audit jsonl 含对应事件

手动验证（无法自动化）：
- 真实 CI 自愈触发：push 故意失败 commit 触发 ai-self-heal workflow
- 浏览器打开 approval-hub 查看待办 + 点击通过/拒绝
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes import ops_autonomy


@pytest.fixture
def e2e_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FastAPI:
    """隔离 ledger/audit 路径的最小 FastAPI 应用。"""
    monkeypatch.setenv("AUTONOMY_WEBHOOK_TOKEN", "e2e-token")
    monkeypatch.setenv("XCAGI_AUTONOMY_APPROVAL_LEDGER_PATH", str(tmp_path / "approval.jsonl"))
    monkeypatch.setenv("XCAGI_AUTONOMY_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("XCAGI_AUTONOMY_AUDIT_DB_PATH", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setenv("XCAGI_AUTONOMY_METRICS_LOG_PATH", str(tmp_path / "metrics.jsonl"))
    # 强制 medium risk 需要 human 审批
    monkeypatch.setenv("XCAGI_AUTONOMY_MEDIUM_RISK_POLICY", "require_human")
    app = FastAPI()
    app.include_router(ops_autonomy.router)
    return app


@pytest.fixture
def e2e_client(e2e_app: FastAPI) -> TestClient:
    return TestClient(e2e_app)


_AUTH = {"X-Autonomy-Token": "e2e-token"}


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except (ValueError, json.JSONDecodeError):
            continue
    return rows


class TestIngestToApproveE2E:
    """CI ingest → pending → resume(approve) → audit。"""

    def test_ci_ingest_then_admin_approve(self, e2e_client: TestClient, tmp_path: Path) -> None:
        # 1. CI ingest 写入待办（非白名单 action）
        resp = e2e_client.post(
            "/api/ops/autonomy/actions/ingest",
            headers=_AUTH,
            json={
                "action": "freeze_manifest",
                "payload": {"reason": "e2e test"},
                "source": "ci_self_heal",
            },
        )
        assert resp.status_code == 200, resp.text
        action_id = resp.json()["action_id"]
        assert resp.json()["state"] == "pending_approval"

        # 2. 管理端拉取 pending
        resp = e2e_client.get("/api/ops/autonomy/actions/pending", headers=_AUTH)
        assert resp.status_code == 200
        pending = resp.json()
        assert pending["count"] >= 1
        assert any(item["action_id"] == action_id for item in pending["items"])

        # 3. 管理端通过（defer_execution 避免 real executor）
        resp = e2e_client.post(
            f"/api/ops/autonomy/actions/{action_id}/resume",
            headers=_AUTH,
            json={"approver": "admin-e2e", "defer_execution": True},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["action"]["state"] == "approved"

        # 4. pending 不再含该 action
        resp = e2e_client.get("/api/ops/autonomy/actions/pending", headers=_AUTH)
        assert not any(item["action_id"] == action_id for item in resp.json()["items"])

        # 5. audit 含 pending_approval + approved
        audit_path = tmp_path / "audit.jsonl"
        events = _read_jsonl(audit_path)
        decisions = [e.get("decision") for e in events if e.get("action_id") == action_id]
        assert "pending_approval" in decisions
        assert "approved" in decisions


class TestIngestToRejectE2E:
    """CI ingest → pending → reject → audit。"""

    def test_ci_ingest_then_admin_reject(self, e2e_client: TestClient, tmp_path: Path) -> None:
        # 1. ingest
        resp = e2e_client.post(
            "/api/ops/autonomy/actions/ingest",
            headers=_AUTH,
            json={
                "action": "freeze_manifest",
                "payload": {"reason": "reject test"},
                "source": "cvm_watcher",
            },
        )
        assert resp.status_code == 200
        action_id = resp.json()["action_id"]

        # 2. reject
        resp = e2e_client.post(
            f"/api/ops/autonomy/actions/{action_id}/reject",
            headers=_AUTH,
            json={"approver": "admin-e2e", "reason": "测试拒绝"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["action"]["state"] == "rejected"

        # 3. pending 不含
        resp = e2e_client.get("/api/ops/autonomy/actions/pending", headers=_AUTH)
        assert not any(item["action_id"] == action_id for item in resp.json()["items"])

        # 4. audit 含 rejected
        audit_path = tmp_path / "audit.jsonl"
        events = _read_jsonl(audit_path)
        decisions = [e.get("decision") for e in events if e.get("action_id") == action_id]
        assert "rejected" in decisions


class TestIngestNonWhitelistAction:
    """验证 ingest 接受非 _WORKFLOW_ACTIONS 白名单的 action。"""

    def test_ingest_accepts_self_maintenance_merge(self, e2e_client: TestClient) -> None:
        """self_maintenance_merge 不在 /actions/request 白名单，但 /actions/ingest 应接受。"""
        resp = e2e_client.post(
            "/api/ops/autonomy/actions/ingest",
            headers=_AUTH,
            json={"action": "self_maintenance_merge", "source": "ci_self_heal"},
        )
        # 无论 pending 还是 no_approval_needed，都不应是 400
        assert resp.status_code == 200, resp.text
        assert resp.json()["ok"] is True
