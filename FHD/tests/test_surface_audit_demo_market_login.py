"""演示企业号 · 市场登录路径（官网 vs 本地 shim）。"""

from __future__ import annotations

import pytest
from fastapi.responses import JSONResponse


@pytest.mark.asyncio
async def test_远端市场演示号走真实_api_不用本地_shim(monkeypatch):
    monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://xiu-ci.com")

    from app.application.surface_audit_demo_account import demo_account_config

    demo_account_config.cache_clear()
    from app.fastapi_routes import market_account as mod

    login_calls: list[str] = []

    async def proxy_router(method, path, **kwargs):
        login_calls.append(path)
        if path == "/api/auth/me":
            return {
                "id": 33,
                "username": "xcagi-enterprise-demo",
                "is_enterprise": True,
                "is_admin": False,
            }
        return {
            "success": True,
            "access_token": "remote-token",
            "refresh_token": "remote-refresh",
            "user": {
                "id": 33,
                "username": "xcagi-enterprise-demo",
                "is_enterprise": True,
                "is_admin": False,
            },
        }

    monkeypatch.setattr(mod, "_proxy_json", proxy_router)

    result = await mod.login_market_with_password("xcagi-enterprise-demo", "Demo@2026")

    assert result["success"] is True
    assert result["token"] == "remote-token"
    assert result["is_enterprise"] is True
    assert result["market_base_url"] == "https://xiu-ci.com"
    assert "/api/auth/login" in login_calls


@pytest.mark.asyncio
async def test_本地市场优先_demo_shim(monkeypatch):
    monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://127.0.0.1:8788")

    from app.application.surface_audit_demo_account import demo_account_config

    demo_account_config.cache_clear()
    from app.fastapi_routes import market_account as mod

    async def fail_proxy(*args, **kwargs):
        raise AssertionError("remote proxy should not run when local shim matches")

    monkeypatch.setattr(mod, "_proxy_json", fail_proxy)

    result = await mod.login_market_with_password("xcagi-enterprise-demo", "Demo@2026")

    assert result["success"] is True
    assert result["is_enterprise"] is True
    assert result["is_market_admin"] is False
    assert result["market_base_url"] == "http://127.0.0.1:8788"


@pytest.mark.asyncio
async def test_本地市场不可达时_demo_shim_兜底(monkeypatch):
    monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "http://127.0.0.1:8788")

    from app.application.surface_audit_demo_account import demo_account_config

    demo_account_config.cache_clear()
    from app.fastapi_routes import market_account as mod

    async def unreachable(*args, **kwargs):
        return JSONResponse(
            {"success": False, "message": "无法连接修茈市场服务器：ConnectError"},
            status_code=502,
        )

    monkeypatch.setattr(mod, "_proxy_json", unreachable)

    result = await mod.login_market_with_password("xcagi-enterprise-demo", "Demo@2026")

    assert result["success"] is True
    assert str(result["token"]).startswith("xcagi-local-surface-audit-demo")
