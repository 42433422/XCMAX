"""工厂员工 SSOT 守卫：内部工厂角色与客户面 super_employees 分离，且绝不进任何选人器。

这条门若红，说明工厂版超级员工有泄漏进客户/管理联系人的风险——即权限边界破口。
"""

from __future__ import annotations

from app.application import surface_contacts
from app.mod_sdk import assistant_ssot


def test_super_employee_ids_contract_unchanged():
    # 既有契约：客户面超级员工恰好两个，不被工厂角色污染。
    assert assistant_ssot.super_employee_ids() == {
        "claude-super-employee",
        "codex-super-employee",
    }


def test_factory_ids_disjoint_from_super():
    fac = assistant_ssot.factory_employee_ids()
    assert fac == {"claude-factory-employee", "codex-factory-employee"}
    assert fac.isdisjoint(assistant_ssot.super_employee_ids())


def test_factory_employees_marked_internal_and_factory_scope():
    for meta in assistant_ssot.factory_employees().values():
        assert meta.get("visibility") == "internal"
        assert meta.get("scope") == "factory"


def test_is_factory_employee_classification():
    assert assistant_ssot.is_factory_employee("claude-factory-employee") is True
    assert assistant_ssot.is_factory_employee("codex-factory-employee") is True
    assert assistant_ssot.is_factory_employee("claude-super-employee") is False
    assert assistant_ssot.is_factory_employee("") is False


def test_factory_roles_never_appear_in_any_surface_contacts():
    factory = assistant_ssot.factory_employee_ids()
    for device in ("desktop", "mobile"):
        for side in ("enterprise", "admin"):
            contacts = surface_contacts.fixed_contacts(device, side)
            ids = {c.get("id") for c in contacts["top"] + contacts["bottom"]}
            assert ids.isdisjoint(factory), (
                f"factory role leaked into {device}/{side}: {ids & factory}"
            )
