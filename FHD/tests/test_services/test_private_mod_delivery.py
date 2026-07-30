"""客户私有 Mod 双轨交付状态与版本比较测试。"""

from __future__ import annotations

from app.services import private_mod_delivery as delivery


def _use_temp_state(monkeypatch, tmp_path):
    state_path = tmp_path / "private-mod-state.json"
    monkeypatch.setattr(delivery, "_state_path", lambda: state_path)
    return state_path


def test_private_mod_tracks_are_independent(monkeypatch, tmp_path):
    _use_temp_state(monkeypatch, tmp_path)

    project = delivery.project_state("market:7", "customer-mod", name="客户 Mod")
    assert project["tracks"]["business"]["status"] == "production"
    assert project["tracks"]["employees"]["status"] == "production"
    assert delivery.overall_status(project) == "production"

    project = delivery.set_track_status(
        "market:7", "customer-mod", "business", "delivered", note="侧栏验收通过"
    )
    assert project["tracks"]["business"]["status"] == "delivered"
    assert project["tracks"]["employees"]["status"] == "production"
    assert delivery.overall_status(project) == "partial"

    project = delivery.set_track_status("market:7", "customer-mod", "employees", "acceptance")
    assert project["tracks"]["employees"]["status"] == "acceptance"
    assert delivery.overall_status(project) == "acceptance"
    assert delivery.stage_label("employees", "delivered") == "已上岗"


def test_private_mod_state_is_account_scoped(monkeypatch, tmp_path):
    _use_temp_state(monkeypatch, tmp_path)

    delivery.set_track_status("market:7", "customer-mod", "business", "testing")
    other_account = delivery.project_state("market:8", "customer-mod")

    assert other_account["tracks"]["business"]["status"] == "production"
    assert delivery.project_state("market:7", "customer-mod")["tracks"]["business"]["status"] == "testing"


def test_private_mod_delivery_snapshot_round_trips_for_management_view(monkeypatch, tmp_path):
    _use_temp_state(monkeypatch, tmp_path)

    delivery.set_track_status("market:7", "customer-mod", "employees", "rework", note="补充回归用例")
    snapshot = delivery.export_account_state("market:7")
    delivery.apply_account_state("market:8", snapshot)

    projects = delivery.account_projects("market:8", ["customer-mod"])
    assert projects[0]["tracks"]["employees"]["status"] == "rework"
    assert projects[0]["tracks"]["employees"]["timeline"][-1]["note"] == "补充回归用例"


def test_private_mod_version_comparison_handles_common_versions():
    assert delivery.is_newer_version("v1.10.0", "1.9.9") is True
    assert delivery.is_newer_version("1.2.0", "v1.2.0") is False
    assert delivery.version_key("1.2.0") < delivery.version_key("1.2.0-beta")
