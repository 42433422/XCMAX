"""桌面 fast-start：deferred API 注册后须把 SPA catch-all 挪回末尾。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from starlette.testclient import TestClient

from app.fastapi_routes.spa_fallback import ensure_spa_fallback_last, register_spa_history_fallback


def test_ensure_spa_fallback_last_unmasks_deferred_get_api() -> None:
    app = FastAPI()
    register_spa_history_fallback(app)

    @app.get("/api/memory/v2")
    def memory_v2_list():
        return {"success": True, "memories": []}

    # 模拟 deferred 挂载后 catch-all 仍在前面：GET 被 SPA 吃掉
    client = TestClient(app)
    blocked = client.get("/api/memory/v2")
    assert blocked.status_code == 404
    assert "资源不存在" in blocked.text

    ensure_spa_fallback_last(app)
    ok = client.get("/api/memory/v2")
    assert ok.status_code == 200
    assert ok.json()["success"] is True


def test_register_deferred_routes_reorders_spa_fallback() -> None:
    app = FastAPI()
    register_spa_history_fallback(app)

    with (
        patch("app.fastapi_routes.register_business_routes"),
        patch("app.fastapi_routes.RouteRegistry") as registry_cls,
        patch("app.fastapi_routes.register_neuro_routes"),
        patch("app.fastapi_routes.register_neuro_migration_routes"),
        patch("app.fastapi_routes.register_lan_routes"),
        patch("app.fastapi_routes.register_legacy_compat_routes"),
        patch.dict("os.environ", {"XCAGI_SKIP_LEGACY_COMPAT_ROUTES": ""}, clear=False),
    ):
        registry = MagicMock()
        registry.detect_conflicts.return_value = []
        registry_cls.return_value = registry

        from app.fastapi_routes import register_deferred_routes

        register_deferred_routes(app)

    paths = [getattr(r, "path", None) for r in app.router.routes]
    assert paths[-1] == "/{fallback:path}"
