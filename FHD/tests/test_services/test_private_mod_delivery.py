"""客户私有 Mod 双轨交付状态与版本比较测试。"""

from __future__ import annotations

from app.services import private_mod_delivery as delivery


def _use_temp_state(monkeypatch, tmp_path):
    state_path = tmp_path / "private-mod-state.json"
    monkeypatch.setattr(delivery, "_state_path", lambda: state_path)
    return state_path


def _advance(scope, mod_id, track, *statuses, note=""):
    project = None
    for status in statuses:
        project = delivery.set_track_status(
            scope, mod_id, track, status, note=note if status == statuses[-1] else ""
        )
    return project


def test_private_mod_tracks_are_independent(monkeypatch, tmp_path):
    _use_temp_state(monkeypatch, tmp_path)

    project = delivery.project_state("market:7", "customer-mod", name="客户 Mod")
    assert project["tracks"]["modules"]["status"] == "production"
    assert project["tracks"]["employees"]["status"] == "production"
    assert delivery.overall_status(project) == "production"

    project = _advance(
        "market:7",
        "customer-mod",
        "modules",
        "testing",
        "acceptance",
        "delivered",
        note="侧栏验收通过",
    )
    assert project["tracks"]["modules"]["status"] == "delivered"
    assert project["tracks"]["employees"]["status"] == "production"
    assert delivery.overall_status(project) == "partial"

    project = _advance("market:7", "customer-mod", "employees", "testing", "acceptance")
    assert project["tracks"]["employees"]["status"] == "acceptance"
    assert delivery.overall_status(project) == "acceptance"
    assert delivery.stage_label("employees", "delivered") == "已上岗"


def test_private_mod_business_alias_maps_to_modules(monkeypatch, tmp_path):
    _use_temp_state(monkeypatch, tmp_path)
    project = delivery.set_track_status("market:7", "customer-mod", "business", "testing")
    assert "business" not in project["tracks"]
    assert project["tracks"]["modules"]["status"] == "testing"


def test_private_mod_node_progress_rolls_up_track(monkeypatch, tmp_path):
    _use_temp_state(monkeypatch, tmp_path)
    delivery.set_node_status(
        "market:7",
        "taiyangniao-pro",
        "modules",
        "attendance-convert",
        "testing",
        note="进入测试",
    )
    delivery.set_node_status(
        "market:7",
        "taiyangniao-pro",
        "modules",
        "attendance-convert",
        "acceptance",
    )
    delivery.set_node_status(
        "market:7",
        "taiyangniao-pro",
        "modules",
        "attendance-convert",
        "delivered",
        note="考勤表转化完成",
    )
    delivery.set_node_status(
        "market:7",
        "taiyangniao-pro",
        "modules",
        "personnel",
        "testing",
    )
    project = delivery.project_state("market:7", "taiyangniao-pro")
    assert project["tracks"]["modules"]["nodes"]["attendance-convert"]["status"] == "delivered"
    assert project["tracks"]["modules"]["status"] == "testing"

    attached = delivery.attach_track_nodes(
        project,
        {
            "modules": [
                {"id": "attendance-convert", "label": "考勤表转化"},
                {"id": "personnel", "label": "人员管理"},
            ],
            "employees": [{"id": "attendance_ai", "label": "考勤ai助手"}],
        },
    )
    assert attached["modules"][0]["status"] == "delivered"
    assert attached["modules"][0]["next_stages"] == []
    assert attached["modules"][1]["next_stages"] == ["acceptance", "rework"]
    assert attached["employees"][0]["status"] == "production"


def test_private_mod_stage_transition_rejects_skip(monkeypatch, tmp_path):
    _use_temp_state(monkeypatch, tmp_path)
    try:
        delivery.set_node_status(
            "market:7",
            "taiyangniao-pro",
            "modules",
            "attendance-convert",
            "delivered",
        )
        raise AssertionError("should reject skip")
    except ValueError as exc:
        assert "不可从" in str(exc)



def test_private_mod_state_is_account_scoped(monkeypatch, tmp_path):
    _use_temp_state(monkeypatch, tmp_path)

    delivery.set_track_status("market:7", "customer-mod", "modules", "testing")
    other_account = delivery.project_state("market:8", "customer-mod")

    assert other_account["tracks"]["modules"]["status"] == "production"
    assert delivery.project_state("market:7", "customer-mod")["tracks"]["modules"]["status"] == "testing"


def test_private_mod_delivery_snapshot_round_trips_for_management_view(monkeypatch, tmp_path):
    _use_temp_state(monkeypatch, tmp_path)

    _advance("market:7", "customer-mod", "employees", "testing", "rework", note="补充回归用例")
    snapshot = delivery.export_account_state("market:7")
    delivery.apply_account_state("market:8", snapshot)

    projects = delivery.account_projects("market:8", ["customer-mod"])
    assert projects[0]["tracks"]["employees"]["status"] == "rework"
    assert projects[0]["tracks"]["employees"]["timeline"][-1]["note"] == "补充回归用例"


def test_merge_orphan_local_delivery_into_market_scope(monkeypatch, tmp_path):
    _use_temp_state(monkeypatch, tmp_path)
    # 模拟企业端曾误写入 local:default
    delivery.set_node_status(
        "local:default",
        "taiyangniao-pro",
        "modules",
        "attendance-convert",
        "testing",
    )
    delivery.merge_orphan_local_delivery_into_market("market:29", {"taiyangniao-pro"})
    market = delivery.project_state("market:29", "taiyangniao-pro")
    assert market["tracks"]["modules"]["nodes"]["attendance-convert"]["status"] == "testing"
    orphan = delivery.account_projects("local:default", ["taiyangniao-pro"])
    assert orphan[0]["tracks"]["modules"].get("nodes", {}) == {} or "attendance-convert" not in (
        orphan[0]["tracks"]["modules"].get("nodes") or {}
    )


def test_private_mod_version_comparison_handles_common_versions():
    assert delivery.is_newer_version("v1.10.0", "1.9.9") is True
    assert delivery.is_newer_version("1.2.0", "v1.2.0") is False
    assert delivery.version_key("1.2.0") < delivery.version_key("1.2.0-beta")
