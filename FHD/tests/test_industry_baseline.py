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
    assert data["industry_mod_ready"] is False
    industry_group = next(g for g in data["groups"] if g["id"] == "custom")
    assert industry_group["title"] == "定制线"
    assert industry_group["items"][0]["label"] == "考勤行业包"
    assert industry_group["items"][0]["show_mod_id"] is False


def test_onboarding_industry_catalog_neutral_names():
    cat = build_onboarding_industry_catalog()
    assert cat["open_industry_ids"] == ["涂料", "考勤"]
    names = {p["industry_id"]: p["product_name"] for p in cat["open_packages"]}
    assert names["考勤"] == "考勤行业包"
    assert names["涂料"] == "涂料行业包"
    assert "太阳鸟" not in str(cat)
    assert "奇士美" not in str(cat)


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


def test_industry_baseline_custom_line_from_manifest():
    data = build_industry_baseline_plan(
        "考勤",
        installed_mod_ids=["attendance-industry"],
    )
    custom = next(g for g in data["groups"] if g["id"] == "custom")
    assert "考勤转换" in custom["hint"]
    assert data["custom_mod_ids"] == ["attendance-industry"]
    assert data["industry_mod_ready"] is True


def test_industry_baseline_unknown_falls_back_to_generic():
    data = build_industry_baseline_plan("不存在的行业", installed_mod_ids=[])
    assert data["industry_id"] == "不存在的行业"
    assert "xcagi-planner-bridge" in data["missing_required_mod_ids"]
