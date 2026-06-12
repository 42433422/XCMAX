# -*- coding: utf-8 -*-

from __future__ import annotations

from app.mod_sdk.industry_baseline import (
    build_industry_baseline_plan,
    build_onboarding_industry_catalog,
)


def test_industry_baseline_attendance_plan():
    data = build_industry_baseline_plan(
        "考勤",
        installed_mod_ids=["xcagi-planner-bridge"],
    )
    assert data["industry_id"] == "考勤"
    assert data["industry_package"]["product_name"] == "考勤行业包"
    assert data["industry_package"]["mod_id"] == "attendance-industry"
    assert "customer_brand" not in (data.get("industry_package") or {})
    assert "xcagi-planner-bridge" in data["required_mod_ids"]
    assert "attendance-industry" in data["industry_mod_ids"]
    assert "xcagi-planner-bridge" not in data["missing_required_mod_ids"]
    assert "xcagi-erp-domain-bridge" in data["missing_required_mod_ids"]
    assert data["baseline_ready"] is False
    assert data["host_baseline_ready"] is False
    assert data["account_custom_ready"] is True
    assert data["industry_mod_ready"] is False
    pkg_group = next(g for g in data["groups"] if g["id"] == "industry_package")
    assert pkg_group["title"] == "行业包"
    assert pkg_group["items"][0]["label"] == "考勤行业包"
    assert pkg_group["items"][0]["show_mod_id"] is False
    assert not any(g["id"] == "account_custom" for g in data["groups"])


def test_industry_baseline_attendance_with_entitled_custom():
    data = build_industry_baseline_plan(
        "考勤",
        installed_mod_ids=["xcagi-planner-bridge", "xcagi-neuro-bus-bridge"],
        entitled_mod_ids={"taiyangniao-pro"},
    )
    custom_group = next(g for g in data["groups"] if g["id"] == "account_custom")
    assert custom_group["items"][0]["mod_id"] == "taiyangniao-pro"
    assert custom_group["items"][0]["label"] == "太阳鸟 PRO"
    assert custom_group["items"][0]["required"] is True
    assert data["account_custom_ready"] is False
    assert data["baseline_ready"] is False
    assert "taiyangniao-pro" in data["missing_account_custom_mod_ids"]


def test_industry_baseline_attendance_custom_installed():
    data = build_industry_baseline_plan(
        "考勤",
        installed_mod_ids=[
            "xcagi-planner-bridge",
            "xcagi-neuro-bus-bridge",
            "xcagi-erp-domain-bridge",
            "xcagi-core-workflow-employees",
            "xcagi-planner-excel-tools",
            "xcagi-office-employee-pack-bridge",
            "taiyangniao-pro",
        ],
        entitled_mod_ids={"taiyangniao-pro"},
    )
    assert data["account_custom_ready"] is True
    assert data["missing_account_custom_mod_ids"] == []


def test_onboarding_industry_catalog_neutral_names():
    cat = build_onboarding_industry_catalog()
    assert cat["open_industry_ids"] == ["涂料", "考勤"]
    names = {p["industry_id"]: p["product_name"] for p in cat["open_packages"]}
    assert names["考勤"] == "考勤行业包"
    assert names["涂料"] == "涂料行业包"
    assert "太阳鸟" not in str(cat)
    assert "奇士美" not in str(cat)
    paint = next(p for p in cat["open_packages"] if p["industry_id"] == "涂料")
    assert paint["name"] == "涂料/油漆"
    assert "批发" in paint["scenario"]
    assert paint["selectable"] is True
    assert cat["preview_packages"]
    locked = next(p for p in cat["preview_packages"] if p["industry_id"] == "通用")
    assert locked["selectable"] is False
    assert locked["name"] == "通用"


def test_industry_baseline_generic_minimal():
    data = build_industry_baseline_plan(
        "通用",
        installed_mod_ids=[
            "xcagi-planner-bridge",
            "xcagi-neuro-bus-bridge",
        ],
    )
    assert data["baseline_ready"] is True
    assert data["industry_mod_ids"] == []


def test_industry_baseline_industry_package_installed():
    data = build_industry_baseline_plan(
        "考勤",
        installed_mod_ids=["attendance-industry"],
    )
    pkg = next(g for g in data["groups"] if g["id"] == "industry_package")
    assert "考勤" in pkg["hint"] or "排班" in pkg["hint"]
    assert data["custom_mod_ids"] == ["attendance-industry"]
    assert data["industry_mod_ready"] is True


def test_onboarding_catalog_filtered_attendance_only():
    from app.mod_sdk.industry_baseline import (
        build_onboarding_industry_catalog,
        filter_onboarding_catalog_for_entitlements,
    )

    cat = build_onboarding_industry_catalog()
    filtered = filter_onboarding_catalog_for_entitlements(cat, {"taiyangniao-pro"})
    assert filtered["open_industry_ids"] == ["考勤"]
    assert all(p["selectable"] for p in filtered["open_packages"])


def test_onboarding_catalog_filtered_coating_only():
    from app.mod_sdk.industry_baseline import (
        build_onboarding_industry_catalog,
        filter_onboarding_catalog_for_entitlements,
    )

    cat = build_onboarding_industry_catalog()
    filtered = filter_onboarding_catalog_for_entitlements(cat, {"sz-qsm-pro"})
    assert filtered["open_industry_ids"] == ["涂料"]


def test_onboarding_catalog_both_entitled():
    from app.mod_sdk.industry_baseline import (
        build_onboarding_industry_catalog,
        filter_onboarding_catalog_for_entitlements,
    )

    cat = build_onboarding_industry_catalog()
    filtered = filter_onboarding_catalog_for_entitlements(
        cat, {"taiyangniao-pro", "sz-qsm-pro", "attendance-industry"}
    )
    assert set(filtered["open_industry_ids"]) == {"涂料", "考勤"}


def test_industry_baseline_unknown_falls_back_to_generic():
    data = build_industry_baseline_plan("不存在的行业", installed_mod_ids=[])
    assert data["industry_id"] == "不存在的行业"
    assert "xcagi-planner-bridge" in data["missing_required_mod_ids"]


def test_account_custom_skip_gate_for_admin():
    data = build_industry_baseline_plan(
        "考勤",
        installed_mod_ids=["xcagi-planner-bridge"],
        entitled_mod_ids={"taiyangniao-pro"},
        skip_account_custom_gate=True,
    )
    assert data["account_custom_ready"] is True
    assert "taiyangniao-pro" in data["missing_account_custom_mod_ids"]
