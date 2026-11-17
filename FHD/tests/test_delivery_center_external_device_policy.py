from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[1]
ADMIN_CONSOLE = FHD_ROOT / "admin-console" / "src"


def test_delivery_center_exposes_internal_mac_exclusion_policy() -> None:
    view = (ADMIN_CONSOLE / "views" / "DeliveryCenterView.vue").read_text(encoding="utf-8")
    roster = (ADMIN_CONSOLE / "components" / "admin" / "EnterpriseDeliveryRoster.vue").read_text(
        encoding="utf-8"
    )

    assert "<EnterpriseDeliveryRoster" in view
    assert "policy.internal_device_exclusion_enabled" in roster
    assert "policy.internal_device_ids_configured" in roster
    assert "内部本机尚未登记" in roster
    assert ':policy="standardPolicy"' in view
    assert "installed_devices" in roster
    assert "台内部本机已排除" in roster
    assert "台客户设备已安装" in roster
    assert "当前版本" in roster
    assert "latest_installed_receipt" in roster
    assert "安装版本" in roster
