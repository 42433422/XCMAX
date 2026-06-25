"""安全回归：MOD 商店「执行型」路由必须有授权门。

历史漏洞：``POST /api/mod-store/install`` 等路由零鉴权，而安装一个 MOD =
在宿主进程内 ``exec_module`` 执行任意 Python；CSRF 中间件又对任何带
``Authorization: Bearer`` 前缀的请求直接放行，等于任意网络可达者即可 RCE。

本测试钉死：
  * 匿名请求落在执行型路由上 → 401/403（被拦在 handler 之前）。
  * 沙盒实例（``XCAGI_SANDBOX_INSTANCE=1``）→ 放行机器推送（设计内）。
  * 只读浏览路由（catalog）不受影响。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.fastapi_routes.mod_store_routes import require_mod_admin
from app.fastapi_routes.mod_store_routes import router as mod_store_router

# 所有应被授权门保护的执行/变更型路由。
_GATED_POSTS = [
    "/api/mod-store/install",
    "/api/mod-store/upload",
    "/api/mod-store/update",
    "/api/mod-store/uninstall",
    "/api/mod-store/reload-employees",
    "/api/mod-store/install-industry-seed",
    "/api/mod-store/install-customer-delivery-seed",
    "/api/mod-store/index/rebuild",
    "/api/mod-store/install-host-foundation",
    "/api/mod-store/bootstrap-edition-pack",
    "/api/mod-store/sync-modstore-library",
]


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(mod_store_router, prefix="/api/mod-store")
    return TestClient(app)


def _bare_request() -> Request:
    return Request({"type": "http", "method": "POST", "headers": [], "path": "/x"})


@pytest.mark.parametrize("path", _GATED_POSTS)
def test_anonymous_blocked_on_execution_routes(
    client: TestClient, path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("XCAGI_SANDBOX_INSTANCE", raising=False)
    r = client.post(path, json={"pkg_id": "x", "mod_id": "x"})
    assert r.status_code in (401, 403), f"{path} 未被授权门拦截 -> {r.status_code}: {r.text[:200]}"


def test_require_mod_admin_blocks_anonymous(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XCAGI_SANDBOX_INSTANCE", raising=False)
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        require_mod_admin(_bare_request())
    assert exc.value.status_code in (401, 403)


def test_require_mod_admin_allows_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_SANDBOX_INSTANCE", "1")
    out = require_mod_admin(_bare_request())
    assert out == {"sandbox": True}


def test_readonly_catalog_not_gated(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """只读浏览路由不应被授权门误伤（不为 401/403）。"""
    monkeypatch.delenv("XCAGI_SANDBOX_INSTANCE", raising=False)
    r = client.get("/api/mod-store/updates")
    assert r.status_code not in (401, 403), f"只读路由被误拦 -> {r.status_code}"
