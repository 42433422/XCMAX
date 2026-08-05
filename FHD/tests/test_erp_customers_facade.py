from __future__ import annotations

import json
from pathlib import Path

import pytest

MOD_DIR = Path(__file__).resolve().parents[1] / "mods" / "xcagi-erp-domain-bridge"


def test_manifest_customers_via_service():
    data = json.loads((MOD_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert data.get("config", {}).get("customers_via_service") is True
    assert data.get("config", {}).get("wechat_contacts_via_facade") is True


def test_customers_list_via_service(monkeypatch):
    from app.mod_sdk import erp_customers_facade as cf

    monkeypatch.setattr(cf, "is_erp_customers_via_service_enabled", lambda: True)

    class FakeSvc:
        def get_all(self, keyword=None, page=1, per_page=20):
            return {"success": True, "data": [{"id": 2, "customer_name": "ACME"}], "total": 1}

    monkeypatch.setattr(cf, "_service", lambda: FakeSvc())
    monkeypatch.setattr(
        "app.infrastructure.auth.db_token.verify_db_read_token_header",
        lambda request: None,
    )
    out = cf.customers_list(None, page=1, per_page=20)
    assert out["success"] is True
    assert out["total"] == 1
    assert out.get("execution_path") == "customers_service"


def test_blueprints_wechat_contacts_proxy():
    text = (MOD_DIR / "backend" / "blueprints.py").read_text(encoding="utf-8")
    assert "mount_wechat_contacts_routes" in text
    wc = (MOD_DIR / "backend" / "wechat_contacts_routes.py").read_text(encoding="utf-8")
    assert "/wechat_contacts" in wc
    assert "/wechat_contacts/work_mode_feed" in wc


def test_work_mode_feed_facade_adapts_legacy_items():
    from app.infrastructure.mods.mod_manager import import_mod_backend_py

    mod = import_mod_backend_py(
        str(MOD_DIR),
        "xcagi-erp-domain-bridge",
        "wechat_contacts_routes",
    )
    payload = mod._to_work_mode_feed_payload(
        {
            "items": [
                {
                    "username": "wxid-1",
                    "display_name": "测试联系人",
                    "summary": "下午三点开会",
                    "timestamp": 123,
                    "unread_count": 2,
                }
            ]
        },
        per_contact=1,
    )

    assert payload["success"] is True
    assert payload["feed"][0]["contact_id"] == "wxid-1"
    assert payload["feed"][0]["messages"][0]["text"] == "下午三点开会"


def test_work_mode_feed_facade_treats_unconfigured_source_as_empty_feed():
    from app.infrastructure.mods.mod_manager import import_mod_backend_py

    mod = import_mod_backend_py(
        str(MOD_DIR),
        "xcagi-erp-domain-bridge",
        "wechat_contacts_routes",
    )
    payload = mod._to_work_mode_feed_payload(
        {"items": [], "error": "wechat-decrypt not configured"},
        per_contact=1,
    )

    assert payload["success"] is True
    assert payload["feed"] == []
    assert payload["unavailable_reason"] == "wechat-decrypt not configured"
