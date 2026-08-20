from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MOD_DIR = REPO / "mods" / "xcagi-model-payment-bridge"


def test_model_payment_manifest_facade_flag():
    from tests.mod_presence import skip_if_bridge_mod_absent

    skip_if_bridge_mod_absent("xcagi-model-payment-bridge")
    data = json.loads((MOD_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert data.get("config", {}).get("model_payment_facade") is True


def test_model_payment_stays_out_of_primary_sidebar():
    """模型服务保留设置页能力，但不能再次注册为主导航菜单。"""
    for mod_dir in (
        REPO / "mods" / "xcagi-model-payment-bridge",
        REPO / "XCAGI" / "mods" / "xcagi-model-payment-bridge",
    ):
        data = json.loads((mod_dir / "manifest.json").read_text(encoding="utf-8"))
        menu_ids = {str(row.get("id") or "") for row in data.get("frontend", {}).get("menu", [])}
        assert "mod-model-payment" not in menu_ids


def test_model_payment_blueprints_delegate_routes():
    from tests.mod_presence import skip_if_bridge_mod_absent

    skip_if_bridge_mod_absent("xcagi-model-payment-bridge")
    text = (MOD_DIR / "backend" / "blueprints.py").read_text(encoding="utf-8")
    assert "/model-payment/plans" in text
    assert "/model-payment/checkout" in text
    assert "app.mod_sdk.host_services" in text


def test_list_model_payment_facade_registry_mod(monkeypatch):
    from app.mod_sdk import model_payment_compat as mpc

    monkeypatch.setattr(mpc, "is_model_payment_via_mod_enabled", lambda: True)
    data = mpc.list_model_payment_facade_registry()
    from tests.mod_sdk_expectations import MOD_FACADE_EXECUTION_PATHS

    assert data.get("execution_path") in MOD_FACADE_EXECUTION_PATHS
    assert data.get("endpoint_count", 0) >= 5


def test_platform_shell_lists_model_payment_facade():
    from app.mod_sdk.platform_shell import BRIDGE_MOD_HOST_APIS

    prefixes = BRIDGE_MOD_HOST_APIS.get("xcagi-model-payment-bridge") or []
    assert any("xcagi-model-payment-bridge" in p for p in prefixes)
