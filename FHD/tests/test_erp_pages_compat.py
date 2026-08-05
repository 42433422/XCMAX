from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_erp_duplicate_capabilities_stay_out_of_primary_sidebar():
    retired = {
        "mod-erp-materials-list",
        "mod-erp-business-docking",
        "mod-erp-wechat-contacts",
    }
    for mod_dir in (
        REPO / "mods" / "xcagi-erp-domain-bridge",
        REPO / "XCAGI" / "mods" / "xcagi-erp-domain-bridge",
    ):
        data = json.loads((mod_dir / "manifest.json").read_text(encoding="utf-8"))
        menu_ids = {str(row.get("id") or "") for row in data.get("frontend", {}).get("menu", [])}
        assert menu_ids.isdisjoint(retired)


def test_erp_pages_registry_physical():
    from app.mod_sdk.erp_pages_compat import list_erp_pages_registry

    reg = list_erp_pages_registry()
    manifest = json.loads(
        (REPO / "mods" / "xcagi-erp-domain-bridge" / "manifest.json").read_text(encoding="utf-8")
    )
    if manifest.get("config", {}).get("views_physical"):
        assert reg.get("component_source") == "mod.frontend.views (O+ physical)"
        assert reg.get("views_physical") is True
        assert reg.get("page_count") == len(reg.get("host_pages") or [])
        assert reg.get("page_count") >= 16
