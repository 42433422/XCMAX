"""登录后客户定制 Mod API 挂载（太阳鸟治根）。"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.fastapi_routes.spa_fallback import ensure_spa_fallback_last, register_spa_history_fallback
from app.infrastructure.mods.mod_manager import (
    _entitled_client_mod_ids_for_api_mount,
    ensure_mod_api_ready,
    mount_entitled_client_mod_api_routes,
)


def test_ensure_mod_api_ready_reorders_spa_fallback_after_dynamic_mount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()
    register_spa_history_fallback(app)

    def _fake_register(target_app, mod_manager, mod_id, *, force=False) -> bool:
        @target_app.get(f"/api/mod/{mod_id}/hello")
        def _hello():
            return {"success": True, "mod": mod_id}

        mod_manager._http_routes_registered.add(mod_id)
        return True

    class _Mgr:
        _loaded_mods: list[str] = []
        _http_routes_registered: set[str] = set()

        def load_mod(self, mod_id: str) -> bool:
            self._loaded_mods.append(mod_id)
            return True

        def resolve_mod_directory(self, mod_id: str) -> str:
            return f"/mods/{mod_id}"

    mgr = _Mgr()

    monkeypatch.setattr(
        "app.infrastructure.mods.mod_manager.is_mods_disabled",
        lambda: False,
    )
    monkeypatch.setattr(
        "app.infrastructure.mods.mod_manager._restore_entitlements_from_session_id",
        lambda session_id=None: None,
    )
    monkeypatch.setattr(
        "app.infrastructure.mods.mod_manager._mod_allowed_for_api_load",
        lambda mod_id, session_id=None: True,
    )
    monkeypatch.setattr(
        "app.infrastructure.mods.mod_manager.get_mod_manager",
        lambda: mgr,
    )
    monkeypatch.setattr(
        "app.infrastructure.mods.mod_manager._register_single_mod_http_routes",
        _fake_register,
    )
    monkeypatch.setattr(
        "app.fastapi_app.get_fastapi_app",
        lambda: app,
    )

    assert ensure_mod_api_ready("taiyangniao-pro", session_id="sess-1") is True

    api_paths = [r.path for r in app.router.routes if isinstance(r, APIRoute)]
    assert "/api/mod/taiyangniao-pro/hello" in api_paths
    assert api_paths.index("/api/mod/taiyangniao-pro/hello") < api_paths.index("/{fallback:path}")

    with TestClient(app) as client:
        resp = client.get("/api/mod/taiyangniao-pro/hello")
    assert resp.status_code == 200
    assert resp.json()["mod"] == "taiyangniao-pro"


def test_mount_entitled_client_mod_api_routes_uses_entitlement_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()
    calls: list[str] = []

    monkeypatch.setattr(
        "app.infrastructure.mods.mod_manager.is_mods_disabled",
        lambda: False,
    )
    monkeypatch.setattr(
        "app.infrastructure.mods.mod_manager._entitled_client_mod_ids_for_api_mount",
        lambda session_id=None: ["taiyangniao-pro"],
    )

    def _ensure(mid: str, session_id: str | None = None) -> bool:
        calls.append(mid)
        return True

    monkeypatch.setattr(
        "app.infrastructure.mods.mod_manager.ensure_mod_api_ready",
        _ensure,
    )
    monkeypatch.setattr(
        "app.fastapi_routes.spa_fallback.ensure_spa_fallback_last",
        lambda target_app: None,
    )

    mounted = mount_entitled_client_mod_api_routes(app, session_id="sess-2")
    assert mounted == ["taiyangniao-pro"]
    assert calls == ["taiyangniao-pro"]


def test_api_mount_candidates_skip_unselected_open_industry_seed(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selected = tmp_path / "attendance-industry"
    selected.mkdir()

    class _Mgr:
        mods_root = str(tmp_path)

    monkeypatch.setattr(
        "app.infrastructure.mods.mod_manager._restore_entitlements_from_session_id",
        lambda session_id=None: None,
    )
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.get_cached_entitled_client_mod_ids",
        lambda: {"attendance-industry", "coating-industry", "taiyangniao-pro"},
    )
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.is_client_mod_id",
        lambda mod_id: True,
    )
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
        lambda mod_id: True,
    )
    monkeypatch.setattr(
        "app.mod_sdk.platform_shell.PROTECTED_CLIENT_MOD_IDS",
        set(),
    )
    monkeypatch.setattr(
        "app.mod_sdk.industry_seed.open_industry_seed_mod_ids",
        lambda: ["attendance-industry", "coating-industry"],
    )
    monkeypatch.setattr(
        "app.infrastructure.mods.mod_manager.get_mod_manager",
        lambda: _Mgr(),
    )

    assert _entitled_client_mod_ids_for_api_mount("sess-3") == [
        "attendance-industry",
        "taiyangniao-pro",
    ]
