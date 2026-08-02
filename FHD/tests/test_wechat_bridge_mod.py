"""Release contract for the standalone enterprise WeChat integration MOD."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODS = ROOT / "mods"


def _manifest(mod_id: str) -> dict[str, object]:
    return json.loads((MODS / mod_id / "manifest.json").read_text(encoding="utf-8"))


def test_enterprise_bundles_the_standalone_wechat_bridge() -> None:
    profile = json.loads(
        (ROOT / "config" / "host_profiles" / "enterprise.json").read_text(encoding="utf-8")
    )
    staged = set(profile["package_stage_ids"])
    bundled = set(profile["sku_bundled_mod_ids"])
    assert "xcagi-wechat-bridge" in staged
    assert "xcagi-wechat-bridge" in bundled

    manifest = _manifest("xcagi-wechat-bridge")
    assert manifest["id"] == "xcagi-wechat-bridge"
    assert manifest["version"] == "1.0.0.1"
    assert manifest["config"]["legacy_host_prefixes"] == [
        "/api/wechat",
        "/api/wechat_contacts",
    ]


def test_erp_bridge_manifest_remains_valid_after_wechat_extraction() -> None:
    manifest = _manifest("xcagi-erp-domain-bridge")
    config = manifest["config"]
    assert config["wechat_contacts_via_facade"] is False
    assert "wechat" not in config["mod_domain_handlers"]
    assert "/api/wechat_contacts" not in config["legacy_host_prefixes"]
    assert "/wechat-contacts" not in config["legacy_host_page_paths"]


def test_wechat_extraction_does_not_break_erp_handler_import() -> None:
    from app.infrastructure.mods.mod_manager import import_mod_backend_py

    erp = import_mod_backend_py(
        str(MODS / "xcagi-erp-domain-bridge"),
        "xcagi-erp-domain-bridge",
        "domain_handlers",
    )
    assert "wechat.contacts_list" not in erp.list_registered_actions()
    assert erp.run_domain_handler("wechat", "contacts_list") is None


def test_standalone_wechat_bridge_owns_contact_handler(monkeypatch) -> None:
    from app.infrastructure.mods.mod_manager import import_mod_backend_py

    bridge = import_mod_backend_py(
        str(MODS / "xcagi-wechat-bridge"),
        "xcagi-wechat-bridge",
        "blueprints",
    )

    class FakeWechatContacts:
        def get_contacts(self, **_kwargs):
            return [{"id": 3, "contact_name": "张三"}]

    monkeypatch.setattr(
        "app.application.get_wechat_contact_app_service",
        lambda: FakeWechatContacts(),
    )
    output = bridge._contacts_list(limit=20)
    assert output["success"] is True
    assert output["data"][0]["id"] == 3
    assert output["source"] == "mod:xcagi-wechat-bridge"
