"""AIOPEN P1 执行层测试：operation_call 的组包、分级闸门与 scope 鉴权。"""

from __future__ import annotations

import pytest
from fastapi import APIRouter, FastAPI, Query
from fastapi.testclient import TestClient

from app.application.aiopen.catalog_builder import get_catalog
from app.application.aiopen.service import AIOPEN_STATE, generate_api_key
from app.fastapi_routes.ai_open import router as ai_open_router

_KEY = "fixture-operation-key"


def _operation_id(app, method: str, path: str) -> str:
    for entry in get_catalog(app)["operations"]:
        if entry["method"] == method and entry["path"] == path:
            return entry["operation_id"]
    raise AssertionError(f"operation not found: {method} {path}")


@pytest.fixture()
def state():
    return {"created": None, "deleted": False}


@pytest.fixture()
def app(monkeypatch, state):
    monkeypatch.setenv("AIOPEN_API_KEY", _KEY)
    monkeypatch.delenv("AIOPEN_ENABLE_WRITES", raising=False)
    monkeypatch.setitem(
        AIOPEN_STATE,
        "whitelist",
        {"/api/products": True, "/api/orders": True},
    )
    app = FastAPI()
    business = APIRouter()

    @business.get("/api/products", summary="商品列表")
    def list_products(page: int = Query(default=1)):
        return {"page": page, "items": []}

    @business.get("/api/products/{product_id}", summary="商品详情")
    def product_detail(product_id: str):
        return {"product_id": product_id}

    @business.post("/api/products", summary="创建商品")
    def create_product(payload: dict):
        state["created"] = payload
        return {"success": True, "payload": payload}

    @business.delete("/api/products/{product_id}", summary="删除商品")
    def delete_product(product_id: str):
        state["deleted"] = True
        return {"success": True}

    @business.get("/api/orders", summary="订单列表")
    def list_orders():
        return {"items": []}

    app.include_router(business)
    app.include_router(ai_open_router)
    return app


@pytest.fixture()
def client(app):
    return TestClient(app, headers={"X-AIOPEN-Key": _KEY})


def _call(
    client,
    operation_id: str,
    *,
    params=None,
    body=None,
    key: str | None = None,
    approval_id: int | None = None,
):
    payload = {"operation_id": operation_id}
    if params is not None:
        payload["params"] = params
    if body is not None:
        payload["body"] = body
    if approval_id is not None:
        payload["approval_id"] = approval_id
    headers = {"X-AIOPEN-Key": key} if key else None
    return client.post(
        "/api/aiopen/invoke",
        json={"tool": "operation_call", "args": payload},
        headers=headers,
    )


def test_manifest_exposes_operation_call(client):
    tools = client.get("/api/aiopen/manifest").json()["tools"]
    assert "operation_call" in {tool["name"] for tool in tools}


def test_operation_call_reads_with_query_params(client, app):
    operation_id = _operation_id(app, "GET", "/api/products")
    response = _call(client, operation_id, params={"page": 2})
    body = response.json()
    assert body["success"] is True
    assert body["data"]["page"] == 2
    assert body["risk"] == "read"


def test_operation_call_interpolates_path_params(client, app):
    operation_id = _operation_id(app, "GET", "/api/products/{product_id}")
    response = _call(client, operation_id, params={"product_id": "P-42"})
    body = response.json()
    assert body["success"] is True
    assert body["data"]["product_id"] == "P-42"


def test_write_is_disabled_by_default(client, app, state):
    operation_id = _operation_id(app, "POST", "/api/products")
    body = _call(client, operation_id, body={"name": "螺丝"})
    assert body.json()["code"] == "WRITE_DISABLED"
    assert state["created"] is None


def test_write_executes_when_enabled(client, app, state, monkeypatch):
    monkeypatch.setenv("AIOPEN_ENABLE_WRITES", "1")
    operation_id = _operation_id(app, "POST", "/api/products")
    body = _call(client, operation_id, body={"name": "螺丝"})
    assert body.json()["success"] is True
    assert state["created"]["name"] == "螺丝"


def test_danger_requires_approval_and_never_executes(client, app, state, monkeypatch):
    from app.application.aiopen import approval_bridge

    monkeypatch.setattr(
        approval_bridge,
        "submit",
        lambda entry, args, principal: {
            "status": "pending",
            "code": "APPROVAL_REQUIRED",
            "approval_id": 91,
            "request_no": "APR20261117-TEST",
            "message": "已提交审批",
        },
    )
    operation_id = _operation_id(app, "DELETE", "/api/products/{product_id}")
    body = _call(client, operation_id, params={"product_id": "P-1"}).json()
    assert body["code"] == "APPROVAL_REQUIRED"
    assert body["approval_id"] == 91
    assert state["deleted"] is False


def test_danger_executes_with_approved_ticket(client, app, state, monkeypatch):
    from app.application.aiopen import approval_bridge

    monkeypatch.setattr(
        approval_bridge,
        "consume",
        lambda approval_id, entry, args, principal: {
            "status": "approved",
            "approval_id": approval_id,
            "request_no": "APR20261117-TEST",
        },
    )
    operation_id = _operation_id(app, "DELETE", "/api/products/{product_id}")
    body = _call(
        client, operation_id, params={"product_id": "P-1"}, approval_id=91
    ).json()
    assert body["success"] is True
    assert state["deleted"] is True


def test_danger_rejects_rejected_ticket(client, app, state, monkeypatch):
    from app.application.aiopen import approval_bridge

    monkeypatch.setattr(
        approval_bridge,
        "consume",
        lambda approval_id, entry, args, principal: {
            "status": "pending",
            "code": "APPROVAL_PENDING",
            "message": "审批尚未通过",
        },
    )
    operation_id = _operation_id(app, "DELETE", "/api/products/{product_id}")
    body = _call(
        client, operation_id, params={"product_id": "P-1"}, approval_id=91
    ).json()
    assert body["code"] == "APPROVAL_PENDING"
    assert state["deleted"] is False


def test_danger_auto_approves_when_both_switches_on(client, app, state, monkeypatch):
    from app.application.aiopen import approval_bridge

    monkeypatch.setenv("AIOPEN_ENABLE_WRITES", "1")
    monkeypatch.setenv(approval_bridge.AUTO_APPROVE_ENV, "1")
    calls: list[int] = []
    monkeypatch.setattr(
        approval_bridge,
        "submit",
        lambda entry, args, principal: {
            "status": "pending",
            "code": "APPROVAL_REQUIRED",
            "approval_id": 93,
            "request_no": "APR20261117-AUTO",
            "message": "已提交审批",
        },
    )
    monkeypatch.setattr(
        approval_bridge,
        "auto_approve",
        lambda approval_id, principal: calls.append(approval_id) or True,
    )
    monkeypatch.setattr(
        approval_bridge,
        "consume",
        lambda approval_id, entry, args, principal: {
            "status": "approved",
            "approval_id": approval_id,
            "request_no": "APR20261117-AUTO",
        },
    )
    operation_id = _operation_id(app, "DELETE", "/api/products/{product_id}")
    body = _call(client, operation_id, params={"product_id": "P-1"}).json()
    assert body["success"] is True
    assert state["deleted"] is True
    assert calls == [93]


def test_danger_auto_approve_still_requires_writes(client, app, state, monkeypatch):
    from app.application.aiopen import approval_bridge

    monkeypatch.delenv("AIOPEN_ENABLE_WRITES", raising=False)
    monkeypatch.setenv(approval_bridge.AUTO_APPROVE_ENV, "1")
    monkeypatch.setattr(
        approval_bridge,
        "submit",
        lambda entry, args, principal: {
            "status": "pending",
            "code": "APPROVAL_REQUIRED",
            "approval_id": 94,
            "request_no": "APR20261117-AUTO2",
            "message": "已提交审批",
        },
    )
    monkeypatch.setattr(
        approval_bridge,
        "auto_approve",
        lambda approval_id, principal: True,
    )
    operation_id = _operation_id(app, "DELETE", "/api/products/{product_id}")
    body = _call(client, operation_id, params={"product_id": "P-1"}).json()
    assert body["code"] == "APPROVAL_REQUIRED"
    assert state["deleted"] is False


def test_api_call_write_is_gated(client, app, state):
    body = client.post(
        "/api/aiopen/invoke",
        json={
            "tool": "api_call",
            "args": {"path": "/api/products", "method": "POST", "body": {"name": "x"}},
        },
    ).json()
    assert body["code"] == "WRITE_DISABLED"
    assert state["created"] is None


def test_api_call_danger_requires_approval(client, app, state, monkeypatch):
    from app.application.aiopen import approval_bridge

    monkeypatch.setattr(
        approval_bridge,
        "submit",
        lambda entry, args, principal: {
            "status": "pending",
            "code": "APPROVAL_REQUIRED",
            "approval_id": 92,
            "request_no": "APR20261117-TEST2",
            "message": "已提交审批",
        },
    )
    body = client.post(
        "/api/aiopen/invoke",
        json={
            "tool": "api_call",
            "args": {"path": "/api/products/P-1", "method": "DELETE"},
        },
    ).json()
    assert body["code"] == "APPROVAL_REQUIRED"
    assert state["deleted"] is False


def test_unknown_operation_is_rejected(client):
    body = _call(client, "ghost.none").json()
    assert body["code"] == "OPERATION_NOT_FOUND"


def test_missing_path_param_is_rejected(client, app):
    operation_id = _operation_id(app, "GET", "/api/products/{product_id}")
    body = _call(client, operation_id).json()
    assert body["code"] == "INVALID_ARGUMENT"


def test_scope_limits_operation_call(client, app):
    created = generate_api_key(
        "scoped", scopes=["read:products"], expires_at=None
    )
    key = created["key"]
    products = _operation_id(app, "GET", "/api/products")
    orders = _operation_id(app, "GET", "/api/orders")
    assert _call(client, products, key=key).status_code == 200
    denied = _call(client, orders, key=key)
    assert denied.status_code == 403
    assert denied.json()["code"] == "AIOPEN_SCOPE_DENIED"


def test_mcp_operation_call_returns_readable_text(client, app):
    operation_id = _operation_id(app, "GET", "/api/products")
    response = client.post(
        "/api/aiopen/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "operation_call",
                "arguments": {"operation_id": operation_id, "params": {"page": 3}},
            },
        },
    )
    text = response.json()["result"]["content"][0]["text"]
    assert operation_id in text
    assert "HTTP 200" in text
