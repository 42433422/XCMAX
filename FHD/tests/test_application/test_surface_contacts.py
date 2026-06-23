"""surface_contacts 解析器守卫:手机端固定联系人按端组成。"""

from __future__ import annotations

from app.application import surface_contacts


def _kinds(entries):
    return [e["kind"] for e in entries]


def test_mobile_enterprise_composition():
    r = surface_contacts.mobile_fixed_contacts("enterprise")
    assert r["side"] == "enterprise"
    # 平台员工之前: 小C助理 + 专属客服
    assert _kinds(r["top"]) == ["assistant", "dedicated_cs"]
    # 平台员工之后: 两个超级员工
    assert _kinds(r["bottom"]) == ["super", "super"]


def test_mobile_admin_has_no_dedicated_cs():
    r = surface_contacts.mobile_fixed_contacts("admin")
    assert r["side"] == "admin"
    assert _kinds(r["top"]) == ["assistant"]  # 管理端无专属客服
    assert _kinds(r["bottom"]) == ["super", "super"]
    all_kinds = _kinds(r["top"]) + _kinds(r["bottom"])
    assert "dedicated_cs" not in all_kinds


def test_xiaoc_not_conflated_with_dedicated_cs():
    """小C助理(智能对话) 与 专属客服 路由/后端必须不同。"""
    r = surface_contacts.mobile_fixed_contacts("enterprise")
    by_kind = {e["kind"]: e for e in r["top"]}
    assert by_kind["assistant"]["name"] == "小C助理"
    assert by_kind["assistant"]["route"] == "assistant_chat"
    assert by_kind["dedicated_cs"]["route"] == "cs"
    assert by_kind["assistant"]["route"] != by_kind["dedicated_cs"]["route"]
    assert by_kind["assistant"]["backend"] != by_kind["dedicated_cs"]["backend"]


def test_super_employees_present_both_sides():
    for side in ("enterprise", "admin"):
        r = surface_contacts.mobile_fixed_contacts(side)
        super_ids = {e["id"] for e in r["bottom"] if e["kind"] == "super"}
        assert super_ids == {"claude-super-employee", "codex-super-employee"}


def test_unknown_side_defaults_enterprise():
    r = surface_contacts.mobile_fixed_contacts("garbage")
    assert r["side"] == "enterprise"
