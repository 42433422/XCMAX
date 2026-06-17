"""COVERAGE_RAMP Phase 1 (p0-core) batch 2: market, compat chat helpers, approval, mobile ext."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

import app.fastapi_routes.mobile_api_extensions as mobile_ext
from app.application import aibiz_web_terminal_service as aibiz_mod
from app.application.approval_workspace_app_service import (
    _generate_request_no,
    _next_node,
    _node_query_for_user,
    _normalize_statuses,
)
from app.application.file_analysis_app_service import FileAnalysisService
from app.application.product_app_service import ProductApplicationService
from app.fastapi_routes import market_account as market_mod
from app.fastapi_routes import mobile_api as mobile_api_mod
from app.fastapi_routes import xcagi_compat_chat_helpers as chat_helpers

# ---------------------------------------------------------------------------
# market_account pure helpers
# ---------------------------------------------------------------------------


def test_market_auth_header_bearer() -> None:
    assert market_mod._auth_header("tok").startswith("Bearer ")
    assert market_mod._auth_header("Bearer x") == "Bearer x"
    assert market_mod._auth_header("Authorization: abc") == "Bearer abc"


def test_market_session_id_from_cookie() -> None:
    scope = {
        "type": "http",
        "headers": [],
        "method": "GET",
        "path": "/",
    }
    req = Request(scope)
    req._cookies = {"session_id": "abc123"}  # type: ignore[attr-defined]
    assert market_mod.session_id_from_request(req) == "abc123"


def test_market_save_and_clear_session_token() -> None:
    market_mod._MARKET_SESSION_TOKENS.clear()
    market_mod.save_session_market_token("sid1", "jwt-token", "refresh")
    assert market_mod._MARKET_SESSION_TOKENS["sid1"] == "jwt-token"
    market_mod.clear_session_market_token("sid1")
    assert "sid1" not in market_mod._MARKET_SESSION_TOKENS


def test_market_base_url_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XCAGI_MARKET_BASE_URL", raising=False)
    assert market_mod._market_base_url().startswith("http")


def test_bootstrap_overview_needs_live_merge() -> None:
    complete = {
        "user": {"id": 1},
        "wallet": {"balance": 0},
        "membership": {"tier": "free"},
    }
    assert market_mod._bootstrap_overview_needs_live_merge(complete) is False
    assert market_mod._bootstrap_overview_needs_live_merge({"user": {"id": 1}}) is True
    assert (
        market_mod._bootstrap_overview_needs_live_merge(
            {"user": {"id": 1}, "wallet": {"balance": 0}}
        )
        is True
    )


@pytest.mark.asyncio
async def test_market_account_overview_skips_legacy_when_bootstrap_complete(
    market_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _auth(req, body):
        return "Bearer tok"

    calls: list[str] = []

    async def _proxy(method, path, **kwargs):
        calls.append(path)
        if path == "/api/account/bootstrap":
            return {
                "data": {
                    "user": {"id": 1},
                    "wallet": {"balance": 10},
                    "membership": {"tier": "vip"},
                }
            }
        return {"__proxy_error__": True, "status_code": 500, "payload": {}}

    monkeypatch.setattr(market_mod, "_authorization_from_request_resolved", _auth)
    monkeypatch.setattr(market_mod, "_proxy_json", _proxy)
    market_mod._ACCOUNT_OVERVIEW_CACHE.clear()
    r = market_client.post("/api/market/account-overview", json={"refresh": True})
    assert r.status_code == 200
    assert calls == ["/api/account/bootstrap"]


@pytest.mark.asyncio
async def test_market_account_overview_uses_server_cache(
    market_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _auth(req, body):
        return "Bearer cached-tok"

    calls: list[str] = []

    async def _proxy(method, path, **kwargs):
        calls.append(path)
        return {
            "data": {
                "user": {"id": 2},
                "wallet": {"balance": 5},
                "membership": {"tier": "free"},
            }
        }

    monkeypatch.setattr(market_mod, "_authorization_from_request_resolved", _auth)
    monkeypatch.setattr(market_mod, "_proxy_json", _proxy)
    market_mod._ACCOUNT_OVERVIEW_CACHE.clear()
    r1 = market_client.post("/api/market/account-overview", json={})
    r2 = market_client.post("/api/market/account-overview", json={})
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert calls == ["/api/account/bootstrap"]


# ---------------------------------------------------------------------------
# market routes (mock httpx)
# ---------------------------------------------------------------------------


@pytest.fixture
def market_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(market_mod, "_authorization_from_request", lambda req, body: "Bearer test")
    app = FastAPI()
    app.include_router(market_mod.router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.asyncio
async def test_market_status_route_reachable(
    market_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _ok(method, path, **k):
        return {"status": "ok"}

    monkeypatch.setattr(market_mod, "_proxy_json", _ok)
    r = market_client.get("/api/market/status")
    assert r.status_code == 200
    assert r.json()["success"] is True


@pytest.mark.asyncio
async def test_market_llm_catalog_get(
    market_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _catalog(method, path, **k):
        return {"models": []}

    monkeypatch.setattr(market_mod, "_proxy_json", _catalog)
    r = market_client.get("/api/market/llm-catalog")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_market_payment_plans(
    market_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _plans(method, path, **k):
        return {"plans": []}

    monkeypatch.setattr(market_mod, "_proxy_json", _plans)
    r = market_client.get("/api/market/payment/plans")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_market_payment_direct_checkout_signed(
    market_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, str]] = []

    async def _proxy(method, path, **k):
        calls.append((method, path))
        if path == "/api/payment/sign-checkout":
            return {
                "request_id": "rid-1",
                "timestamp": 1700000000,
                "signature": "sig-1",
                "subject": "钱包充值",
                "total_amount": 10.0,
                "plan_id": "",
                "item_id": 0,
                "wallet_recharge": True,
            }
        if path == "/api/payment/checkout":
            return {
                "ok": True,
                "type": "page",
                "redirect_url": "https://openapi.alipay.com/gateway.do?demo=1",
                "order_id": "MOD123",
            }
        if path == "/api/auth/me":
            return {"user": {"id": 33, "username": "xcagi-enterprise-demo"}}
        return {}

    monkeypatch.setattr(market_mod, "_proxy_json", _proxy)

    async def _auth(request, body):
        return "Bearer tok", None

    monkeypatch.setattr(market_mod, "_resolve_market_authorization_for_checkout", _auth)
    r = market_client.post(
        "/api/market/payment/direct-checkout",
        json={"wallet_recharge": True, "total_amount": 10, "subject": "钱包充值"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["redirect_url"].startswith("https://openapi.alipay.com")
    assert calls[0] == ("POST", "/api/payment/sign-checkout")
    assert calls[1] == ("POST", "/api/payment/checkout")


# ---------------------------------------------------------------------------
# xcagi_compat_chat_helpers
# ---------------------------------------------------------------------------


def _make_request(
    *,
    ip: str = "127.0.0.1",
    ua: str = "pytest",
    headers: dict | None = None,
) -> Request:
    hdrs = [(b"user-agent", ua.encode())]
    if headers:
        for k, v in headers.items():
            hdrs.append((k.lower().encode(), v.encode()))
    scope = {
        "type": "http",
        "headers": hdrs,
        "method": "GET",
        "path": "/",
        "client": (ip, 12345),
    }
    return Request(scope)


def test_chat_request_subject_stable() -> None:
    req = _make_request()
    s1 = chat_helpers._chat_request_subject(req)
    s2 = chat_helpers._chat_request_subject(req)
    assert s1 == s2
    assert "127.0.0.1" in s1


def test_chat_db_read_grace_lifecycle() -> None:
    chat_helpers._chat_db_read_grace_until.clear()
    req = _make_request()
    secs = chat_helpers._touch_chat_db_read_grace(req)
    assert secs == chat_helpers._CHAT_DB_READ_GRACE_SEC
    left = chat_helpers._chat_db_read_grace_seconds_left(req)
    assert left > 0


def test_chat_db_read_intent_pattern() -> None:
    assert chat_helpers._CHAT_DB_READ_INTENT_RE.search("查看数据库产品库")
    assert not chat_helpers._CHAT_DB_READ_INTENT_RE.search("你好")


# ---------------------------------------------------------------------------
# approval_workspace helpers
# ---------------------------------------------------------------------------


def test_approval_normalize_statuses_defaults() -> None:
    out = _normalize_statuses(None)
    assert "approved" in out or "APPROVED" in [s.upper() for s in out]


def test_approval_normalize_statuses_csv() -> None:
    from app.db.models.approval import ApprovalStatus

    raw = f"{ApprovalStatus.APPROVED.value},{ApprovalStatus.REJECTED.value}"
    out = _normalize_statuses(raw)
    assert ApprovalStatus.APPROVED.value in out


def test_approval_generate_request_no_format() -> None:
    no = _generate_request_no()
    assert no.startswith("APR")


def test_approval_node_query_for_user() -> None:
    node = SimpleNamespace(approver_ids=json.dumps([1, 2, 3]))
    assert _node_query_for_user(node, 2) is True
    assert _node_query_for_user(node, 9) is False
    assert _node_query_for_user(SimpleNamespace(approver_ids="bad"), 1) is False


def test_approval_next_node() -> None:
    nodes = [
        SimpleNamespace(node_order=1),
        SimpleNamespace(node_order=3),
        SimpleNamespace(node_order=5),
    ]
    nxt = _next_node(nodes, 1)
    assert nxt is not None
    assert nxt.node_order == 3
    assert _next_node(nodes, 5) is None


# ---------------------------------------------------------------------------
# file_analysis + product services
# ---------------------------------------------------------------------------


def test_file_analysis_missing_file() -> None:
    svc = FileAnalysisService()
    out = svc.analyze_file(None)
    assert out["success"] is False


def test_product_app_service_search_and_names() -> None:
    products = MagicMock()
    products.get_product_names.return_value = {"success": True, "data": ["A"]}
    products.get_products.return_value = {"success": True, "data": []}
    svc = ProductApplicationService(products_service=products)
    assert svc.get_product_names("a")["success"] is True
    assert svc.search_products(keyword="x")["success"] is True


def test_aibiz_lane_mapping() -> None:
    assert aibiz_mod._LANE_BY_TERMINAL["web"][0] == "P-W"


# ---------------------------------------------------------------------------
# mobile extension routes (more endpoints)
# ---------------------------------------------------------------------------


@pytest.fixture
def mobile_client() -> TestClient:
    app = FastAPI()
    app.include_router(mobile_ext.extension_router)
    app.dependency_overrides[mobile_api_mod.get_mobile_user] = lambda: SimpleNamespace(
        id=1, username="m"
    )
    return TestClient(app, raise_server_exceptions=False)


@patch("app.db.session.get_db")
def test_mobile_customers_list(mock_get_db: MagicMock, mobile_client: TestClient) -> None:
    mock_db = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = mock_db
    cm.__exit__.return_value = None
    mock_get_db.return_value = cm
    q = MagicMock()
    q.count.return_value = 0
    q.order_by.return_value = q
    q.offset.return_value = q
    q.limit.return_value = q
    q.all.return_value = []
    mock_db.query.return_value = q
    r = mobile_client.get("/customers")
    assert r.status_code == 200


@patch("app.db.session.get_db")
def test_mobile_shipments_list(mock_get_db: MagicMock, mobile_client: TestClient) -> None:
    mock_db = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = mock_db
    cm.__exit__.return_value = None
    mock_get_db.return_value = cm
    q = MagicMock()
    q.filter.return_value = q
    q.count.return_value = 0
    q.order_by.return_value = q
    q.offset.return_value = q
    q.limit.return_value = q
    q.all.return_value = []
    mock_db.query.return_value = q
    r = mobile_client.get("/shipments")
    assert r.status_code == 200


def test_mobile_mods_list(mobile_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mobile_ext, "_mobile_mod_items", lambda: [{"id": "demo"}])
    r = mobile_client.get("/mods")
    assert r.status_code == 200


def test_mobile_home(mobile_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mobile_ext, "_mobile_mod_items", lambda: [{"id": "demo"}])
    r = mobile_client.get("/home")
    assert r.status_code == 200


def test_mobile_sync_status(mobile_client: TestClient) -> None:
    r = mobile_client.get("/sync/status")
    assert r.status_code == 200


def test_mobile_platform_shell(mobile_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mobile_ext, "_mobile_mod_items", lambda: [{"id": "demo"}])
    r = mobile_client.get("/platform-shell")
    assert r.status_code == 200
