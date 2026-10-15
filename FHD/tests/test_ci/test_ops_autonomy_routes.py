"""ops_autonomy 路由单测。

覆盖：
- POST /api/ops/autonomy/actions/{action_id}/reject：成功 / 空 approver / ApprovalStateError
- POST /api/ops/autonomy/actions/request：透传 body.source 字段（含 / 缺省）
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.autonomy.approval_resume import ApprovalStateError
from app.fastapi_routes import ops_autonomy, ops_autonomy_work_orders


@pytest.fixture
def autonomy_app(monkeypatch: pytest.MonkeyPatch, tmp_path) -> FastAPI:
    """隔离 ledger / audit 路径并装好 ops_autonomy router 的最小 FastAPI 应用。"""
    monkeypatch.setenv("AUTONOMY_WEBHOOK_TOKEN", "test-token")
    monkeypatch.setenv("XCAGI_AUTONOMY_APPROVAL_LEDGER_PATH", str(tmp_path / "approval.jsonl"))
    monkeypatch.setenv("XCAGI_AUTONOMY_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("XCAGI_AUTONOMY_AUDIT_DB_PATH", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setenv("XCAGI_AUTONOMY_METRICS_LOG_PATH", str(tmp_path / "metrics.jsonl"))
    app = FastAPI()
    app.include_router(ops_autonomy.router)
    return app


@pytest.fixture
def autonomy_client(autonomy_app: FastAPI) -> TestClient:
    return TestClient(autonomy_app)


_AUTH_HEADERS = {"X-Autonomy-Token": "test-token"}


class TestRejectEndpoint:
    def test_reject_success_returns_200_with_action(self, autonomy_client: TestClient) -> None:
        """reject 端点成功调用 reject_action，返回 200 + {ok: true, action: ...}。"""
        fake_action = {
            "action_id": "act-1",
            "state": "rejected",
            "approver": "alice",
        }
        with patch.object(ops_autonomy, "reject_action", return_value=fake_action) as mock_reject:
            response = autonomy_client.post(
                "/api/ops/autonomy/actions/act-1/reject",
                headers=_AUTH_HEADERS,
                json={
                    "approver": "alice",
                    "reason": "bad change",
                    "approval_id": "dep-42",
                },
            )
        assert response.status_code == 200
        assert response.json() == {"ok": True, "action": fake_action}
        mock_reject.assert_called_once_with(
            "act-1",
            approver="alice",
            reason="bad change",
            approval_id="dep-42",
        )

    def test_reject_empty_approver_returns_400(self, autonomy_client: TestClient) -> None:
        """reject 端点 approver 为空 → 400，且不调用 reject_action。"""
        with patch.object(ops_autonomy, "reject_action") as mock_reject:
            response = autonomy_client.post(
                "/api/ops/autonomy/actions/act-1/reject",
                headers=_AUTH_HEADERS,
                json={"approver": ""},
            )
        assert response.status_code == 400
        assert "approver" in response.json()["detail"]
        mock_reject.assert_not_called()

    def test_reject_approval_state_error_returns_409(self, autonomy_client: TestClient) -> None:
        """reject_action 抛 ApprovalStateError → 409。"""
        with patch.object(
            ops_autonomy,
            "reject_action",
            side_effect=ApprovalStateError("action act-1 is not pending"),
        ):
            response = autonomy_client.post(
                "/api/ops/autonomy/actions/act-1/reject",
                headers=_AUTH_HEADERS,
                json={"approver": "alice"},
            )
        assert response.status_code == 409
        assert "not pending" in response.json()["detail"]


class TestRequestSourcePassthrough:
    def test_request_with_source_uses_body_source(self, autonomy_client: TestClient) -> None:
        """body 含 source: 'ci_self_heal' 时，request_action 被调用时 source='ci_self_heal'。"""
        fake_decision = MagicMock()
        fake_decision.to_dict.return_value = {"decision": "block"}
        fake_pending = {"state": "pending_approval", "action_id": "wf-1"}
        with patch.object(
            ops_autonomy,
            "request_action",
            return_value=(fake_decision, fake_pending),
        ) as mock_req:
            response = autonomy_client.post(
                "/api/ops/autonomy/actions/request",
                headers=_AUTH_HEADERS,
                json={
                    "action": "freeze_manifest",
                    "action_id": "wf-1",
                    "source": "ci_self_heal",
                },
            )
        assert response.status_code == 200
        assert response.json()["state"] == "pending_approval"
        _, kwargs = mock_req.call_args
        assert kwargs["source"] == "ci_self_heal"

    def test_request_without_source_uses_default(self, autonomy_client: TestClient) -> None:
        """不传 source 时，request_action 的 source 参数为默认 'ops_autonomy.request'。"""
        fake_decision = MagicMock()
        fake_decision.to_dict.return_value = {"decision": "block"}
        fake_pending = {"state": "pending_approval", "action_id": "wf-2"}
        with patch.object(
            ops_autonomy,
            "request_action",
            return_value=(fake_decision, fake_pending),
        ) as mock_req:
            response = autonomy_client.post(
                "/api/ops/autonomy/actions/request",
                headers=_AUTH_HEADERS,
                json={
                    "action": "freeze_manifest",
                    "action_id": "wf-2",
                },
            )
        assert response.status_code == 200
        _, kwargs = mock_req.call_args
        assert kwargs["source"] == "ops_autonomy.request"


def test_owner_work_order_review_requires_all_gates_and_records_session_actor(monkeypatch):
    monkeypatch.setenv("FHD_BOSS_USER_ID", "17")
    monkeypatch.setattr(
        "app.fastapi_routes.xcmax_admin_auth.require_market_admin_session", lambda request: None
    )
    monkeypatch.setattr(
        ops_autonomy_work_orders, "_owner_meta", lambda request: {"local_user_id": 17}
    )
    history = [
        {"event": "gate", "gate": gate, "gate_status": status}
        for gate, status in (
            ("repro", "RED"),
            ("fix", "FIX_VALIDATED_IN_DEV"),
            ("owner_instance", "OWNER_INSTANCE_VERIFIED"),
        )
    ]
    view = {"wo_id": "WO-abcdef123456", "status": "in_dev", "history": history}
    monkeypatch.setattr("app.services.work_order_ssot.list_work_orders", lambda limit: [view])
    monkeypatch.setattr("app.services.work_order_ssot.get_work_order", lambda wo_id: view)
    monkeypatch.setattr(
        "app.services.work_order_gate.record_gate",
        lambda *args, **kwargs: {"ok": True, "gate": args[1], "status": args[2]},
    )
    monkeypatch.setattr(
        "app.fastapi_routes.xcmax_admin_auth.admin_approver_from_session", lambda request: "Owner"
    )
    app = FastAPI()
    app.include_router(ops_autonomy.router)
    client = TestClient(app)

    listing = client.get("/api/ops/autonomy/work-orders")
    assert listing.json()["items"][0]["can_decide"] is True
    assert listing.json()["items"][0]["owner_instance_verified"] is True
    approved = client.post(
        "/api/ops/autonomy/work-orders/WO-abcdef123456/owner-decision",
        json={"decision": "approved", "actor": "forged"},
    )
    assert approved.status_code == 200
    assert approved.json()["actor"] == "Owner"
    view["history"] = [row for row in history if row["gate"] != "owner_instance"]
    blocked = client.post(
        "/api/ops/autonomy/work-orders/WO-abcdef123456/owner-decision",
        json={"decision": "approved"},
    )
    assert blocked.status_code == 409


def test_owner_session_denies_impersonated_admin(monkeypatch):
    monkeypatch.setenv("FHD_BOSS_USER_ID", "17")
    monkeypatch.setattr(
        "app.fastapi_routes.domains.misc.helpers._session_id_from_request", lambda request: "sid"
    )
    meta = {"local_user_id": 17, "impersonating_market_user_id": None}
    monkeypatch.setattr(
        "app.application.session_account_meta.load_session_account_meta", lambda sid: meta
    )
    assert ops_autonomy_work_orders._owner_meta(object()) == meta
    meta["impersonating_market_user_id"] = 18
    assert ops_autonomy_work_orders._owner_meta(object()) is None


class TestCsSsotRetrieve:
    def test_cs_ssot_retrieve_requires_query(self, autonomy_client: TestClient) -> None:
        response = autonomy_client.post(
            "/api/ops/autonomy/cs-ssot/retrieve",
            headers=_AUTH_HEADERS,
            json={},
        )
        assert response.status_code == 400

    def test_cs_ssot_retrieve_ok(self, autonomy_client: TestClient) -> None:
        fake_svc = MagicMock()
        fake_svc.query.return_value = {
            "success": True,
            "chunks": [{"text": "会员年付", "source": "faq"}],
        }
        with patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
            return_value=fake_svc,
        ):
            response = autonomy_client.post(
                "/api/ops/autonomy/cs-ssot/retrieve",
                headers=_AUTH_HEADERS,
                json={"query": "会员怎么买", "top_k": 3},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["dataset_id"] == "persy-knowledge"
        assert data["ssot"] == "admin_persy_knowledge"
        assert data["chunks"][0]["text"] == "会员年付"
        fake_svc.query.assert_called_once()
