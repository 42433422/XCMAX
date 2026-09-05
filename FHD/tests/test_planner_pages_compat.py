from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MOD_DIR = REPO / "mods" / "xcagi-planner-bridge"


def test_planner_manifest_pages():
    from tests.mod_presence import skip_if_bridge_mod_absent

    skip_if_bridge_mod_absent("xcagi-planner-bridge")
    data = json.loads((MOD_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert data.get("config", {}).get("planner_pages_via_mod") is True
    assert (MOD_DIR / "frontend" / "routes.js").is_file()


def test_list_planner_pages_registry():
    from app.mod_sdk.planner_pages_compat import list_planner_pages_registry

    reg = list_planner_pages_registry()
    assert reg.get("page_count") >= 3
    assert reg.get("chat_mod_path") == "/mod/xcagi-planner-bridge/chat"


def test_retired_developer_page_is_not_advertised_or_packaged():
    from app.mod_sdk.host_profile_defaults import LEGACY_BRIDGE_MOD_HOST_APIS
    from app.mod_sdk.mod_views_compat import list_mod_physical_views_registry
    from app.mod_sdk.planner_pages_compat import list_planner_pages_registry

    registry = list_planner_pages_registry()
    assert registry["host_pages"] == ["/", "/ai-ecosystem", "/chat-debug"]
    assert registry["page_count"] == 3
    views = {
        item["mod_id"]: item["view_files"] for item in list_mod_physical_views_registry()["mods"]
    }
    assert views["xcagi-planner-bridge"] == [
        "ChatView.vue",
        "AIEcosystemView.vue",
        "ChatDebugView.vue",
    ]
    assert (
        "/mod/xcagi-planner-bridge/brain" not in LEGACY_BRIDGE_MOD_HOST_APIS["xcagi-planner-bridge"]
    )
    for root in (REPO / "mods", REPO / "XCAGI/mods"):
        mod_dir = root / "xcagi-planner-bridge"
        manifest = json.loads((mod_dir / "manifest.json").read_text(encoding="utf-8"))
        assert "BrainView.vue" not in manifest["config"]["physical_views"]
        assert "/brain" not in manifest["config"]["legacy_host_page_paths"]
        assert not (mod_dir / "frontend/views/BrainView.vue").exists()
        assert not (mod_dir / "frontend/views/brain").exists()


def test_host_profile_api_preserves_planner_apis_without_retired_page(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.fastapi_routes.system_routes import router

    monkeypatch.setenv("XCAGI_FHD_ROOT", str(REPO))
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get("/api/system/host-profile")
    assert response.status_code == 200
    entries = response.json()["data"]["profile"]["bridge_api_map"]["xcagi-planner-bridge"]
    assert "/mod/xcagi-planner-bridge/brain" not in entries
    assert "/mod/xcagi-planner-bridge/ai-ecosystem" in entries
    assert "/api/ai/chat" in entries
    assert "/api/ai/intent" in entries


def test_planner_pages_registry_physical():
    from app.mod_sdk.planner_pages_compat import list_planner_pages_registry
    from tests.mod_presence import skip_if_bridge_mod_absent

    skip_if_bridge_mod_absent("xcagi-planner-bridge")
    reg = list_planner_pages_registry()
    manifest = json.loads((MOD_DIR / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("config", {}).get("views_physical"):
        assert reg.get("component_source") == "mod.frontend.views (P physical)"
        assert reg.get("views_physical") is True
