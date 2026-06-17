# -*- coding: utf-8 -*-
"""合同生命周期 + 电子签 webhook 路由冒烟（FastAPI 版）。

覆盖 ``app.fastapi_routes.contract_lifecycle_api`` 全部 7 条路由：
- GET  /api/contract-lifecycle/esign-channel
- GET  /api/contract-lifecycle/status
- POST /api/contract-lifecycle/transition
- POST /api/contract-lifecycle/esign/start
- GET  /api/contract-lifecycle/esign/sign/{task_id}
- POST /api/contract-lifecycle/esign/sign/{task_id}/complete
- POST /api/contract-lifecycle/esign/webhook

注意：
- 路由函数内部使用延迟导入，monkeypatch 必须打在源模块上
- ``app.services.esign_adapter`` / ``app.services.stub_esign_store`` /
  ``app.services.fadada_fasc_client`` 尚未实现，需要在 sys.modules 中注入 mock 模块
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes import contract_lifecycle_api as cl_module

# Short aliases for sys.modules access
_EA = "app.services.esign_adapter"
_SES = "app.services.stub_esign_store"
_FFC = "app.services.fadada_fasc_client"


def _install_mock_module(name: str) -> types.ModuleType:
    """在 sys.modules 中注入一个 mock 模块（如果不存在）。"""
    if name not in sys.modules:
        mod = types.ModuleType(name)
        sys.modules[name] = mod
    return sys.modules[name]


@pytest.fixture(autouse=True)
def _ensure_esign_mock_modules():
    """确保 esign 相关的三个模块在 sys.modules 中存在，并设置默认函数。"""
    ea = _install_mock_module(_EA)
    ea.esign_channel_status = lambda: {"provider": "stub", "needs_fadada": False}
    ea.esign_provider_name = lambda: "stub"
    fake_adapter = MagicMock()
    fake_adapter.parse_webhook.return_value = {"signed": True, "market_user_id": 1}
    ea.get_esign_adapter = lambda: fake_adapter

    ses = _install_mock_module(_SES)
    ses.verify_sign_token = lambda task_id, token: True
    ses.get_task = lambda task_id: {
        "task_id": task_id,
        "status": "pending",
        "party_b": "乙方公司",
        "market_user_id": 1,
        "subject": "合同签署",
        "party_a": "甲方",
        "amount_cents": 10000,
        "signed_at": None,
        "signer_name": None,
    }
    ses.task_ttl_exceeded = lambda task: False
    ses.complete_task = lambda task_id, signer_name="": None

    ffc = _install_mock_module(_FFC)
    ffc.verify_fadada_callback_signature = lambda headers, biz_content: False
    ffc.parse_fadada_callback_biz = lambda biz_content: {}

    yield


@pytest.fixture
def app_with_router() -> FastAPI:
    app = FastAPI()
    app.include_router(cl_module.router)
    return app


@pytest.fixture
def client(app_with_router: FastAPI) -> TestClient:
    with TestClient(app_with_router, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# Helper: mock _require_admin_session
# ---------------------------------------------------------------------------


def _mock_admin_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.fastapi_routes.contract_lifecycle_api._require_admin_session",
        lambda request: None,
    )


def _mock_no_session(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.responses import JSONResponse

    monkeypatch.setattr(
        "app.fastapi_routes.contract_lifecycle_api._require_admin_session",
        lambda request: JSONResponse({"success": False, "message": "请先登录"}, status_code=401),
    )


def _mock_non_admin_session(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.responses import JSONResponse

    monkeypatch.setattr(
        "app.fastapi_routes.contract_lifecycle_api._require_admin_session",
        lambda request: JSONResponse(
            {"success": False, "message": "需要管理员账号登录后访问"}, status_code=403
        ),
    )


# ---------------------------------------------------------------------------
# GET /api/contract-lifecycle/esign-channel
# ---------------------------------------------------------------------------


def test_esign_channel_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_admin_session(monkeypatch)
    sys.modules[_EA].esign_channel_status = lambda: {"provider": "stub", "needs_fadada": False}
    r = client.get("/api/contract-lifecycle/esign-channel")
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "stub"


def test_esign_channel_unauthorized(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_no_session(monkeypatch)
    r = client.get("/api/contract-lifecycle/esign-channel")
    assert r.status_code == 401
    body = r.json()
    assert body["success"] is False


def test_esign_channel_forbidden(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_non_admin_session(monkeypatch)
    r = client.get("/api/contract-lifecycle/esign-channel")
    assert r.status_code == 403
    body = r.json()
    assert body["success"] is False


# ---------------------------------------------------------------------------
# GET /api/contract-lifecycle/status
# ---------------------------------------------------------------------------


def test_contract_status_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_pipeline = {
        "stage": "contract_pending",
        "username": "张三",
        "erp_customer_name": "测试公司",
        "contract_lifecycle": {
            "status": "esign_pending",
            "esign_task": {"sign_url": "https://sign.example.com/t/abc", "status": "pending"},
        },
        "contract_fields": {"party_a_name": "甲方公司"},
    }
    monkeypatch.setattr(
        "app.services.user_cs_pipeline.load_pipeline", lambda uid, username="": fake_pipeline
    )
    r = client.get(
        "/api/contract-lifecycle/status", params={"market_user_id": 1, "username": "张三"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["market_user_id"] == 1
    assert body["data"]["sign_url"] == "https://sign.example.com/t/abc"
    assert body["data"]["party_a_default"] == "甲方公司"


def test_contract_status_no_contract_lifecycle(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_pipeline = {"stage": "idle", "username": "李四", "erp_customer_name": "公司B"}
    monkeypatch.setattr(
        "app.services.user_cs_pipeline.load_pipeline", lambda uid, username="": fake_pipeline
    )
    r = client.get("/api/contract-lifecycle/status", params={"market_user_id": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["sign_url"] == ""
    assert body["data"]["party_a_default"] == "公司B"


def test_contract_status_no_esign_task(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_pipeline = {"stage": "idle", "username": "王五", "contract_lifecycle": {"status": "draft"}}
    monkeypatch.setattr(
        "app.services.user_cs_pipeline.load_pipeline", lambda uid, username="": fake_pipeline
    )
    r = client.get("/api/contract-lifecycle/status", params={"market_user_id": 3})
    assert r.status_code == 200
    assert r.json()["data"]["sign_url"] == ""


def test_contract_status_esign_task_not_dict(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_pipeline = {
        "stage": "idle",
        "username": "赵六",
        "contract_lifecycle": {"status": "draft", "esign_task": "not-a-dict"},
    }
    monkeypatch.setattr(
        "app.services.user_cs_pipeline.load_pipeline", lambda uid, username="": fake_pipeline
    )
    r = client.get("/api/contract-lifecycle/status", params={"market_user_id": 4})
    assert r.status_code == 200
    assert r.json()["data"]["sign_url"] == ""


def test_contract_status_contract_fields_not_dict(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_pipeline = {
        "stage": "idle",
        "username": "钱七",
        "erp_customer_name": "公司C",
        "contract_lifecycle": {"status": "draft"},
        "contract_fields": "not-a-dict",
    }
    monkeypatch.setattr(
        "app.services.user_cs_pipeline.load_pipeline", lambda uid, username="": fake_pipeline
    )
    r = client.get("/api/contract-lifecycle/status", params={"market_user_id": 5})
    assert r.status_code == 200
    assert r.json()["data"]["party_a_default"] == "公司C"


def test_contract_status_missing_market_user_id_returns_422(client: TestClient) -> None:
    r = client.get("/api/contract-lifecycle/status")
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/contract-lifecycle/transition
# ---------------------------------------------------------------------------


def test_transition_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_pipeline = {"stage": "contract_pending", "contract_lifecycle": {"status": "draft"}}
    monkeypatch.setattr(
        "app.services.user_cs_pipeline.load_pipeline", lambda uid, username="": fake_pipeline
    )
    monkeypatch.setattr(
        "app.services.contract_lifecycle.transition_contract",
        lambda doc, status, source="", note="": {**doc, "contract_lifecycle": {"status": status}},
    )
    monkeypatch.setattr(
        "app.services.contract_lifecycle.apply_contract_to_crm_meta", lambda doc: doc
    )
    monkeypatch.setattr("app.services.user_cs_pipeline.save_pipeline", lambda doc: doc)
    r = client.post(
        "/api/contract-lifecycle/transition",
        json={"market_user_id": 1, "status": "signed", "username": "张三", "note": "签署完成"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["pipeline"]["contract_lifecycle"]["status"] == "signed"


def test_transition_missing_status_returns_422(client: TestClient) -> None:
    r = client.post("/api/contract-lifecycle/transition", json={"market_user_id": 1})
    assert r.status_code == 422


def test_transition_missing_market_user_id_returns_422(client: TestClient) -> None:
    r = client.post("/api/contract-lifecycle/transition", json={"status": "signed"})
    assert r.status_code == 422


def test_transition_empty_status_returns_422(client: TestClient) -> None:
    r = client.post("/api/contract-lifecycle/transition", json={"market_user_id": 1, "status": ""})
    assert r.status_code == 422


def test_transition_with_note(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_pipeline = {"stage": "idle", "contract_lifecycle": {"status": "draft"}}

    def fake_transition(doc, status, *, source="", note=""):
        return {**doc, "contract_lifecycle": {"status": status, "note": note}}

    monkeypatch.setattr(
        "app.services.user_cs_pipeline.load_pipeline", lambda uid, username="": fake_pipeline
    )
    monkeypatch.setattr("app.services.contract_lifecycle.transition_contract", fake_transition)
    monkeypatch.setattr(
        "app.services.contract_lifecycle.apply_contract_to_crm_meta", lambda doc: doc
    )
    monkeypatch.setattr("app.services.user_cs_pipeline.save_pipeline", lambda doc: doc)
    r = client.post(
        "/api/contract-lifecycle/transition",
        json={"market_user_id": 1, "status": "signed", "note": "审批通过"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["pipeline"]["contract_lifecycle"]["note"] == "审批通过"


# ---------------------------------------------------------------------------
# POST /api/contract-lifecycle/esign/start
# ---------------------------------------------------------------------------


def test_esign_start_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_pipeline = {
        "stage": "contract_pending",
        "erp_customer_name": "乙方公司",
        "payment": {"contract_amount_cents": 50000},
        "contract_lifecycle": {"status": "draft"},
    }

    def fake_start_esign(doc, *, party_a, party_b, amount_cents):
        return {
            **doc,
            "contract_lifecycle": {
                **doc.get("contract_lifecycle", {}),
                "esign_task": {
                    "party_a": party_a,
                    "party_b": party_b,
                    "amount_cents": amount_cents,
                    "status": "pending",
                },
                "status": "esign_pending",
            },
        }

    monkeypatch.setattr(
        "app.services.user_cs_pipeline.load_pipeline", lambda uid, username="": fake_pipeline
    )
    monkeypatch.setattr("app.services.contract_lifecycle.start_esign_flow", fake_start_esign)
    monkeypatch.setattr(
        "app.services.contract_lifecycle.apply_contract_to_crm_meta", lambda doc: doc
    )
    monkeypatch.setattr("app.services.user_cs_pipeline.save_pipeline", lambda doc: doc)
    r = client.post(
        "/api/contract-lifecycle/esign/start",
        json={"market_user_id": 1, "party_a": "甲方公司", "party_b": "乙方公司"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["pipeline"]["contract_lifecycle"]["esign_task"]["party_a"] == "甲方公司"
    assert body["data"]["pipeline"]["contract_lifecycle"]["esign_task"]["amount_cents"] == 50000


def test_esign_start_no_payment_defaults_amount_to_none(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_pipeline = {
        "stage": "contract_pending",
        "erp_customer_name": "乙方公司",
        "contract_lifecycle": {"status": "draft"},
    }

    def fake_start_esign(doc, *, party_a, party_b, amount_cents):
        return {**doc, "esign_task": {"amount_cents": amount_cents}}

    monkeypatch.setattr(
        "app.services.user_cs_pipeline.load_pipeline", lambda uid, username="": fake_pipeline
    )
    monkeypatch.setattr("app.services.contract_lifecycle.start_esign_flow", fake_start_esign)
    monkeypatch.setattr(
        "app.services.contract_lifecycle.apply_contract_to_crm_meta", lambda doc: doc
    )
    monkeypatch.setattr("app.services.user_cs_pipeline.save_pipeline", lambda doc: doc)
    r = client.post(
        "/api/contract-lifecycle/esign/start", json={"market_user_id": 1, "party_a": "甲方公司"}
    )
    assert r.status_code == 200
    assert r.json()["success"] is True


def test_esign_start_no_party_b_uses_erp_customer_name(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_pipeline = {
        "stage": "contract_pending",
        "erp_customer_name": "默认乙方",
        "contract_lifecycle": {"status": "draft"},
    }
    captured = {}

    def fake_start_esign(doc, *, party_a, party_b, amount_cents):
        captured["party_b"] = party_b
        return {**doc, "esign_task": {}}

    monkeypatch.setattr(
        "app.services.user_cs_pipeline.load_pipeline", lambda uid, username="": fake_pipeline
    )
    monkeypatch.setattr("app.services.contract_lifecycle.start_esign_flow", fake_start_esign)
    monkeypatch.setattr(
        "app.services.contract_lifecycle.apply_contract_to_crm_meta", lambda doc: doc
    )
    monkeypatch.setattr("app.services.user_cs_pipeline.save_pipeline", lambda doc: doc)
    r = client.post(
        "/api/contract-lifecycle/esign/start", json={"market_user_id": 1, "party_a": "甲方公司"}
    )
    assert r.status_code == 200
    assert captured["party_b"] == "默认乙方"


def test_esign_start_missing_party_a_returns_422(client: TestClient) -> None:
    r = client.post("/api/contract-lifecycle/esign/start", json={"market_user_id": 1})
    assert r.status_code == 422


def test_esign_start_missing_market_user_id_returns_422(client: TestClient) -> None:
    r = client.post("/api/contract-lifecycle/esign/start", json={"party_a": "甲方公司"})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/contract-lifecycle/esign/sign/{task_id}
# ---------------------------------------------------------------------------


def test_esign_sign_task_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    sys.modules[_EA].esign_provider_name = lambda: "stub"
    sys.modules[_SES].verify_sign_token = lambda task_id, token: True
    sys.modules[_SES].get_task = lambda task_id: {
        "task_id": task_id,
        "subject": "合同签署",
        "party_a": "甲方",
        "party_b": "乙方",
        "amount_cents": 10000,
        "status": "pending",
        "signed_at": None,
        "signer_name": None,
    }
    sys.modules[_SES].task_ttl_exceeded = lambda task: False
    r = client.get("/api/contract-lifecycle/esign/sign/task1", params={"token": "tok123"})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["task_id"] == "task1"
    assert body["data"]["party_a"] == "甲方"


def test_esign_sign_task_non_stub_provider_returns_400(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sys.modules[_EA].esign_provider_name = lambda: "fadada"
    r = client.get("/api/contract-lifecycle/esign/sign/task1", params={"token": "tok123"})
    assert r.status_code == 400
    assert "非自建电子签" in r.json()["error"]


def test_esign_sign_task_invalid_token_returns_403(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sys.modules[_EA].esign_provider_name = lambda: "stub"
    sys.modules[_SES].verify_sign_token = lambda task_id, token: False
    r = client.get("/api/contract-lifecycle/esign/sign/task1", params={"token": "bad-token"})
    assert r.status_code == 403
    assert "链接无效或已过期" in r.json()["error"]


def test_esign_sign_task_not_found_returns_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sys.modules[_EA].esign_provider_name = lambda: "stub"
    sys.modules[_SES].verify_sign_token = lambda task_id, token: True
    sys.modules[_SES].get_task = lambda task_id: None
    r = client.get("/api/contract-lifecycle/esign/sign/nonexistent", params={"token": "tok"})
    assert r.status_code == 404
    assert "签署任务不存在" in r.json()["error"]


def test_esign_sign_task_expired_returns_410(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sys.modules[_EA].esign_provider_name = lambda: "stub"
    sys.modules[_SES].verify_sign_token = lambda task_id, token: True
    sys.modules[_SES].get_task = lambda task_id: {"task_id": task_id, "status": "pending"}
    sys.modules[_SES].task_ttl_exceeded = lambda task: True
    r = client.get("/api/contract-lifecycle/esign/sign/task1", params={"token": "tok"})
    assert r.status_code == 410
    assert "已过期" in r.json()["error"]


# ---------------------------------------------------------------------------
# POST /api/contract-lifecycle/esign/sign/{task_id}/complete
# ---------------------------------------------------------------------------


def test_esign_sign_complete_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    sys.modules[_EA].esign_provider_name = lambda: "stub"
    sys.modules[_SES].verify_sign_token = lambda task_id, token: True
    sys.modules[_SES].get_task = lambda task_id: {
        "task_id": task_id,
        "status": "pending",
        "party_b": "乙方公司",
        "market_user_id": 1,
    }
    sys.modules[_SES].task_ttl_exceeded = lambda task: False
    sys.modules[_SES].complete_task = lambda task_id, signer_name="": None
    monkeypatch.setattr(
        "app.services.contract_lifecycle.handle_esign_webhook", lambda payload: {"success": True}
    )
    r = client.post(
        "/api/contract-lifecycle/esign/sign/task1/complete",
        json={"token": "tok123", "agree": True, "signer_name": "张三"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["signed"] is True
    assert body["data"]["signer_name"] == "张三"


def test_esign_sign_complete_non_stub_returns_400(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sys.modules[_EA].esign_provider_name = lambda: "fadada"
    r = client.post(
        "/api/contract-lifecycle/esign/sign/task1/complete", json={"token": "tok", "agree": True}
    )
    assert r.status_code == 400
    assert "非自建电子签" in r.json()["error"]


def test_esign_sign_complete_not_agreed_returns_400(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sys.modules[_EA].esign_provider_name = lambda: "stub"
    r = client.post(
        "/api/contract-lifecycle/esign/sign/task1/complete", json={"token": "tok", "agree": False}
    )
    assert r.status_code == 400
    assert "同意条款" in r.json()["error"]


def test_esign_sign_complete_invalid_token_returns_403(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sys.modules[_EA].esign_provider_name = lambda: "stub"
    sys.modules[_SES].verify_sign_token = lambda task_id, token: False
    r = client.post(
        "/api/contract-lifecycle/esign/sign/task1/complete", json={"token": "bad", "agree": True}
    )
    assert r.status_code == 403
    assert "链接无效或已过期" in r.json()["error"]


def test_esign_sign_complete_task_not_found_returns_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sys.modules[_EA].esign_provider_name = lambda: "stub"
    sys.modules[_SES].verify_sign_token = lambda task_id, token: True
    sys.modules[_SES].get_task = lambda task_id: None
    r = client.post(
        "/api/contract-lifecycle/esign/sign/task1/complete", json={"token": "tok", "agree": True}
    )
    assert r.status_code == 404
    assert "签署任务不存在" in r.json()["error"]


def test_esign_sign_complete_task_expired_returns_410(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sys.modules[_EA].esign_provider_name = lambda: "stub"
    sys.modules[_SES].verify_sign_token = lambda task_id, token: True
    sys.modules[_SES].get_task = lambda task_id: {"task_id": task_id, "status": "pending"}
    sys.modules[_SES].task_ttl_exceeded = lambda task: True
    r = client.post(
        "/api/contract-lifecycle/esign/sign/task1/complete", json={"token": "tok", "agree": True}
    )
    assert r.status_code == 410
    assert "已过期" in r.json()["error"]


def test_esign_sign_complete_already_signed_returns_200(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sys.modules[_EA].esign_provider_name = lambda: "stub"
    sys.modules[_SES].verify_sign_token = lambda task_id, token: True
    sys.modules[_SES].get_task = lambda task_id: {"task_id": task_id, "status": "signed"}
    sys.modules[_SES].task_ttl_exceeded = lambda task: False
    r = client.post(
        "/api/contract-lifecycle/esign/sign/task1/complete", json={"token": "tok", "agree": True}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["already_signed"] is True


def test_esign_sign_complete_no_signer_name_uses_party_b(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sys.modules[_EA].esign_provider_name = lambda: "stub"
    sys.modules[_SES].verify_sign_token = lambda task_id, token: True
    sys.modules[_SES].get_task = lambda task_id: {
        "task_id": task_id,
        "status": "pending",
        "party_b": "乙方公司",
        "market_user_id": 1,
    }
    sys.modules[_SES].task_ttl_exceeded = lambda task: False
    sys.modules[_SES].complete_task = lambda task_id, signer_name="": None
    monkeypatch.setattr(
        "app.services.contract_lifecycle.handle_esign_webhook", lambda payload: {"success": True}
    )
    r = client.post(
        "/api/contract-lifecycle/esign/sign/task1/complete", json={"token": "tok", "agree": True}
    )
    assert r.status_code == 200
    assert r.json()["data"]["signer_name"] == "乙方公司"


def test_esign_sign_complete_no_signer_name_no_party_b_returns_400(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sys.modules[_EA].esign_provider_name = lambda: "stub"
    sys.modules[_SES].verify_sign_token = lambda task_id, token: True
    sys.modules[_SES].get_task = lambda task_id: {
        "task_id": task_id,
        "status": "pending",
        "market_user_id": 1,
    }
    sys.modules[_SES].task_ttl_exceeded = lambda task: False
    r = client.post(
        "/api/contract-lifecycle/esign/sign/task1/complete", json={"token": "tok", "agree": True}
    )
    assert r.status_code == 400
    assert "签署人姓名" in r.json()["error"]


def test_esign_sign_complete_webhook_failure_returns_400(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sys.modules[_EA].esign_provider_name = lambda: "stub"
    sys.modules[_SES].verify_sign_token = lambda task_id, token: True
    sys.modules[_SES].get_task = lambda task_id: {
        "task_id": task_id,
        "status": "pending",
        "party_b": "乙方",
        "market_user_id": 1,
    }
    sys.modules[_SES].task_ttl_exceeded = lambda task: False
    sys.modules[_SES].complete_task = lambda task_id, signer_name="": None
    monkeypatch.setattr(
        "app.services.contract_lifecycle.handle_esign_webhook",
        lambda payload: {"success": False, "error": "保存失败"},
    )
    r = client.post(
        "/api/contract-lifecycle/esign/sign/task1/complete",
        json={"token": "tok", "agree": True, "signer_name": "张三"},
    )
    assert r.status_code == 400
    assert r.json()["success"] is False


def test_esign_sign_complete_missing_token_returns_422(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sys.modules[_EA].esign_provider_name = lambda: "stub"
    r = client.post("/api/contract-lifecycle/esign/sign/task1/complete", json={"agree": True})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/contract-lifecycle/esign/webhook
# ---------------------------------------------------------------------------


def test_esign_webhook_json_body_success(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.services.contract_lifecycle.handle_esign_webhook",
        lambda payload: {"success": True, "data": {"market_user_id": 1}},
    )
    r = client.post(
        "/api/contract-lifecycle/esign/webhook",
        json={"signed": True, "market_user_id": 1, "task_id": "t1"},
    )
    assert r.status_code == 200
    assert r.json()["success"] is True


def test_esign_webhook_json_body_unsigned(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.services.contract_lifecycle.handle_esign_webhook",
        lambda payload: {"success": False, "error": "unsigned"},
    )
    r = client.post("/api/contract-lifecycle/esign/webhook", json={"signed": False})
    assert r.status_code == 200
    assert r.json()["success"] is False


def test_esign_webhook_empty_json(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.contract_lifecycle.handle_esign_webhook",
        lambda payload: {"success": False, "error": "missing market_user_id"},
    )
    r = client.post("/api/contract-lifecycle/esign/webhook", json={})
    assert r.status_code == 200


def test_esign_webhook_fadada_header_routes_to_fadada_handler(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sys.modules[_FFC].verify_fadada_callback_signature = lambda headers, biz_content: False
    r = client.post(
        "/api/contract-lifecycle/esign/webhook",
        content=b"bizContent=test",
        headers={"Content-Type": "application/x-www-form-urlencoded", "X-FASC-App-Id": "app123"},
    )
    assert r.status_code == 200


def test_esign_webhook_form_urlencoded_routes_to_fadada(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sys.modules[_FFC].verify_fadada_callback_signature = lambda headers, biz_content: False
    r = client.post(
        "/api/contract-lifecycle/esign/webhook",
        data={"bizContent": "test"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 200


def test_esign_webhook_fadada_valid_signature(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sys.modules[_FFC].verify_fadada_callback_signature = lambda headers, biz_content: True
    sys.modules[_FFC].parse_fadada_callback_biz = lambda biz_content: {"action": "sign_complete"}
    fake_adapter = MagicMock()
    fake_adapter.parse_webhook.return_value = {"signed": True, "market_user_id": 1}
    sys.modules[_EA].get_esign_adapter = lambda: fake_adapter
    monkeypatch.setattr(
        "app.services.contract_lifecycle.handle_esign_webhook", lambda payload: {"success": True}
    )
    r = client.post(
        "/api/contract-lifecycle/esign/webhook",
        data={"bizContent": "test-biz"},
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-FASC-App-Id": "app123",
            "X-FASC-Event": "SIGN_EVENT",
        },
    )
    assert r.status_code == 200
    assert "success" in r.text


def test_esign_webhook_fadada_handle_failure_returns_400(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sys.modules[_FFC].verify_fadada_callback_signature = lambda headers, biz_content: True
    sys.modules[_FFC].parse_fadada_callback_biz = lambda biz_content: {}
    fake_adapter = MagicMock()
    fake_adapter.parse_webhook.return_value = {"signed": False}
    sys.modules[_EA].get_esign_adapter = lambda: fake_adapter
    monkeypatch.setattr(
        "app.services.contract_lifecycle.handle_esign_webhook",
        lambda payload: {"success": False, "error": "处理失败"},
    )
    r = client.post(
        "/api/contract-lifecycle/esign/webhook",
        data={"bizContent": "test"},
        headers={"Content-Type": "application/x-www-form-urlencoded", "X-FASC-App-Id": "app123"},
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# _require_admin_session unit tests (via esign-channel endpoint)
# ---------------------------------------------------------------------------


def test_require_admin_session_no_session_id(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.fastapi_routes.domains.misc.helpers._session_id_from_request", lambda request: ""
    )
    r = client.get("/api/contract-lifecycle/esign-channel")
    assert r.status_code == 401


def test_require_admin_session_non_admin(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.fastapi_routes.domains.misc.helpers._session_id_from_request", lambda request: "sid123"
    )
    monkeypatch.setattr(
        "app.application.session_account_meta.load_session_account_meta",
        lambda sid: {"account_kind": "personal"},
    )
    r = client.get("/api/contract-lifecycle/esign-channel")
    assert r.status_code == 403


def test_require_admin_session_admin_passes(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
        lambda request: "sid-admin",
    )
    monkeypatch.setattr(
        "app.application.session_account_meta.load_session_account_meta",
        lambda sid: {"account_kind": "admin"},
    )
    sys.modules[_EA].esign_channel_status = lambda: {"provider": "stub"}
    r = client.get("/api/contract-lifecycle/esign-channel")
    assert r.status_code == 200


def test_require_admin_session_meta_returns_none(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
        lambda request: "sid-unknown",
    )
    monkeypatch.setattr(
        "app.application.session_account_meta.load_session_account_meta", lambda sid: None
    )
    r = client.get("/api/contract-lifecycle/esign-channel")
    assert r.status_code == 403
