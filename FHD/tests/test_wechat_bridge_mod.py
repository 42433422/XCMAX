from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.infrastructure.mods.mod_manager import import_mod_backend_py

FHD_ROOT = Path(__file__).resolve().parents[1]
WECHAT_MOD = FHD_ROOT / "mods" / "xcagi-wechat-bridge"
ERP_MOD = FHD_ROOT / "mods" / "xcagi-erp-domain-bridge"


def _load_blueprints():
    return import_mod_backend_py(str(WECHAT_MOD), "xcagi-wechat-bridge", "blueprints")


def test_wechat_bridge_manifest_is_independent_from_erp() -> None:
    wechat = json.loads((WECHAT_MOD / "manifest.json").read_text(encoding="utf-8"))
    erp = json.loads((ERP_MOD / "manifest.json").read_text(encoding="utf-8"))

    assert wechat["id"] == "xcagi-wechat-bridge"
    assert wechat["config"]["wechat_contacts_via_facade"] is True
    assert "wechat" not in erp["config"]["mod_domain_handlers"]
    assert "/api/wechat_contacts" not in erp["config"]["legacy_host_prefixes"]
    assert "/wechat-contacts" not in erp["config"]["legacy_host_page_paths"]


def test_wechat_bridge_registers_complete_mod_surface() -> None:
    app = FastAPI()
    _load_blueprints().register_fastapi_routes(app, "xcagi-wechat-bridge")

    response = TestClient(app).get("/api/mod/xcagi-wechat-bridge/status")
    included = next(route for route in app.routes if hasattr(route, "original_router"))
    paths = {route.path for route in included.original_router.routes}

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert "/api/mod/xcagi-wechat-bridge/wechat/contacts" in paths
    assert "/api/mod/xcagi-wechat-bridge/wechat_contacts" in paths
    assert "/api/mod/xcagi-wechat-bridge/wechat/decrypt/auto_configure" in paths


def test_wechat_bridge_contacts_handler_does_not_call_erp_dispatch(monkeypatch) -> None:
    import app.mod_sdk.wechat_bridge as bridge_sdk

    monkeypatch.setattr(
        bridge_sdk,
        "list_contacts",
        lambda **_kwargs: [{"id": 7, "contact_name": "测试联系人"}],
    )
    out = _load_blueprints()._invoke("wechat", "contacts_list", limit=20)

    assert out["success"] is True
    assert out["total"] == 1
    assert out["source"] == "mod:xcagi-wechat-bridge"
    assert out["execution_path"] == "mod_domain_handler"


def test_wechat_bridge_task_handler_does_not_call_erp_dispatch(monkeypatch) -> None:
    import app.mod_sdk.wechat_bridge as bridge_sdk

    monkeypatch.setattr(
        bridge_sdk,
        "list_tasks",
        lambda **_kwargs: [{"id": 9, "status": "pending"}],
    )
    out = _load_blueprints()._invoke("wechat", "tasks", status="pending")

    assert out["success"] is True
    assert out["total"] == 1
    assert out["source"] == "mod:xcagi-wechat-bridge"


def test_wechat_bridge_owns_local_decrypt_configuration(monkeypatch) -> None:
    import app.mod_sdk.wechat_bridge as bridge_sdk

    monkeypatch.setattr(
        bridge_sdk,
        "auto_configure",
        lambda body: {"success": True, "force_key_scan": body["force_key_scan"]},
    )

    out = _load_blueprints()._auto_configure({"force_key_scan": False})

    assert out == {"success": True, "force_key_scan": False}
