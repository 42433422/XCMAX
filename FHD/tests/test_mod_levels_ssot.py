"""Mod 分层 SSOT、依赖顺序与市场准入边界。"""

from __future__ import annotations

from types import SimpleNamespace

from app.infrastructure.mods.mod_levels import (
    KIND_CUSTOM_MOD,
    KIND_EMPLOYEE_PACK,
    KIND_INDUSTRY_MOD,
    KIND_SYSTEM_MOD,
    descriptor_for_manifest,
    market_catalog_row_allowed,
    market_install_block_reason,
    sort_mods_for_loading,
    validate_layer_manifest,
)
from app.infrastructure.mods.mod_manager import ModManager


def test_legacy_bridge_and_domain_ids_are_classified_from_ssot() -> None:
    assert descriptor_for_manifest({"id": "xcagi-erp-domain-bridge"}).kind == KIND_SYSTEM_MOD
    assert (
        descriptor_for_manifest({"id": "attendance-industry", "industry": {"id": "考勤"}}).kind
        == KIND_INDUSTRY_MOD
    )
    assert descriptor_for_manifest({"id": "taiyangniao-pro"}).kind == KIND_CUSTOM_MOD


def test_system_manifest_workflow_employees_are_fixed_employees() -> None:
    descriptor = descriptor_for_manifest(
        {
            "id": "xcagi-core-workflow-employees",
            "workflow_employees": [{"id": "shipment_mgmt"}, {"id": "receipt_confirm"}],
        }
    )
    assert descriptor.kind == KIND_SYSTEM_MOD
    assert descriptor.fixed_employees == ("shipment_mgmt", "receipt_confirm")


def test_explicit_employee_parent_is_required_in_strict_mode() -> None:
    manifest = {
        "id": "sales-assistant",
        "artifact": "employee_pack",
        "mod_level": 4,
        "mod_kind": "employee_pack",
        "employee_mode": "pluggable",
    }
    errors = validate_layer_manifest(manifest, strict=True)
    assert "可插拔员工必须声明 parent_mod_id 或 parent_mod_ids" in errors


def test_loading_uses_dependency_order_even_when_primary_is_true() -> None:
    industry = SimpleNamespace(
        id="attendance-industry",
        mod_level=3,
        mod_kind=KIND_INDUSTRY_MOD,
        dependencies={"xcagi": ">=1.0.0"},
        parent_mod_ids=(),
    )
    custom = SimpleNamespace(
        id="taiyangniao-pro",
        mod_level=3,
        mod_kind=KIND_CUSTOM_MOD,
        dependencies={"attendance-industry": ">=1.0.0"},
        parent_mod_ids=(),
    )
    ordered = [item.id for item in sort_mods_for_loading([custom, industry])]
    assert ordered == ["attendance-industry", "taiyangniao-pro"]


def test_market_only_allows_non_fixed_employee_pack() -> None:
    employee = {
        "id": "sales-assistant",
        "artifact": "employee_pack",
        "employee": {"id": "sales-assistant"},
        "mod_level": 4,
        "mod_kind": "employee_pack",
        "employee_mode": "pluggable",
        "parent_mod_id": "attendance-industry",
    }
    system = {"id": "xcagi-erp", "artifact": "mod", "mod_kind": "system_mod", "mod_level": 2}
    assert market_install_block_reason(employee) is None
    assert market_install_block_reason(system)
    assert market_catalog_row_allowed({"artifact": "employee_pack"}) is True
    assert market_catalog_row_allowed({"artifact": "mod"}) is False


def test_market_rejects_employee_pack_without_domain_parent() -> None:
    blocked = market_install_block_reason(
        {
            "id": "orphan-assistant",
            "artifact": "employee_pack",
            "mod_level": 4,
            "mod_kind": "employee_pack",
            "employee_mode": "pluggable",
        }
    )
    assert blocked is not None
    assert "parent_mod_id" in blocked


def test_bridge_members_project_to_one_public_erp_mod() -> None:
    rows = [
        {
            "id": "xcagi-erp-domain-bridge",
            "name": "legacy ERP",
            "composite_owner": "xcagi-erp",
            "mod_level": 2,
            "mod_kind": KIND_SYSTEM_MOD,
            "fixed_employees": [],
        },
        {
            "id": "xcagi-core-workflow-employees",
            "name": "legacy workflow",
            "composite_owner": "xcagi-erp",
            "mod_level": 2,
            "mod_kind": KIND_SYSTEM_MOD,
            "fixed_employees": ["shipment_mgmt"],
        },
    ]
    public = ModManager._collapse_public_composite_rows(rows)
    assert [row["id"] for row in public] == ["xcagi-erp"]
    assert public[0]["component_count"] == 2
    assert public[0]["fixed_employees"] == ["shipment_mgmt"]
