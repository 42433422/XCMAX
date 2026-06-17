# -*- coding: utf-8 -*-

from __future__ import annotations

from types import SimpleNamespace

import pytest

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
        installed_mod_ids=[
            "xcagi-planner-bridge",
            "xcagi-neuro-bus-bridge",
            "xcagi-erp-domain-bridge",
            "xcagi-planner-excel-tools",
        ],
        entitled_mod_ids={"taiyangniao-pro"},
    )
    custom_group = next(g for g in data["groups"] if g["id"] == "account_custom")
    custom_mod_ids = {it["mod_id"] for it in custom_group["items"]}
    assert "taiyangniao-pro" in custom_mod_ids
    assert "xcagi-core-workflow-employees" in custom_mod_ids
    assert custom_group["items"][0]["mod_id"] == "taiyangniao-pro"
    assert custom_group["items"][0]["label"] == "太阳鸟 PRO"
    assert custom_group["items"][0]["required"] is True
    assert data["account_custom_ready"] is False
    assert data["baseline_ready"] is False
    assert "taiyangniao-pro" in data["missing_account_custom_mod_ids"]
    assert "xcagi-core-workflow-employees" in data["missing_account_custom_mod_ids"]


def test_industry_baseline_attendance_custom_installed():
    data = build_industry_baseline_plan(
        "考勤",
        installed_mod_ids=[
            "xcagi-planner-bridge",
            "xcagi-neuro-bus-bridge",
            "xcagi-erp-domain-bridge",
            "xcagi-planner-excel-tools",
            "xcagi-core-workflow-employees",
            "xcagi-office-employee-pack-bridge",
            "wechat-contacts-ai-employee",
            "taiyangniao-pro",
        ],
        entitled_mod_ids={"taiyangniao-pro"},
    )
    assert data["account_custom_ready"] is True
    assert data["missing_account_custom_mod_ids"] == []
    assert data["baseline_ready"] is True
    assert data["full_stack_ready"] is True


def test_industry_baseline_coating_with_entitled_custom():
    data = build_industry_baseline_plan(
        "涂料",
        installed_mod_ids=[
            "xcagi-planner-bridge",
            "xcagi-neuro-bus-bridge",
            "xcagi-erp-domain-bridge",
            "xcagi-planner-excel-tools",
            "xcagi-approval-bridge",
            "xcagi-customer-service-bridge",
        ],
        entitled_mod_ids={"sz-qsm-pro"},
    )
    custom_group = next(g for g in data["groups"] if g["id"] == "account_custom")
    custom_mod_ids = {it["mod_id"] for it in custom_group["items"]}
    assert "sz-qsm-pro" in custom_mod_ids
    assert "xcagi-core-workflow-employees" in custom_mod_ids
    assert data["account_custom_ready"] is False
    assert data["baseline_ready"] is False
    assert "sz-qsm-pro" in data["missing_account_custom_mod_ids"]


def test_onboarding_industry_catalog_neutral_names():
    cat = build_onboarding_industry_catalog()
    assert "涂料" in cat["open_industry_ids"]
    names = {p["industry_id"]: p["product_name"] for p in cat["open_packages"]}
    assert names["涂料"] == "涂料行业包"
    assert "太阳鸟" not in str(cat)
    assert "奇士美" not in str(cat)
    paint = next(p for p in cat["open_packages"] if p["industry_id"] == "涂料")
    assert paint["name"] == "涂料/油漆"
    assert "批发" in paint["scenario"]
    assert paint["selectable"] is True
    all_names = {
        p["industry_id"]: p["product_name"]
        for p in [*cat["open_packages"], *cat["preview_packages"]]
    }
    assert all_names["考勤"] == "考勤行业包"
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


def test_industry_baseline_canonical_industry_does_not_grant_account_custom():
    data = build_industry_baseline_plan(
        "考勤",
        installed_mod_ids=["attendance-industry"],
        entitled_mod_ids={"attendance-industry"},
    )

    assert data["account_custom_mod_ids"] == []
    assert all(g["id"] != "account_custom" for g in data["groups"])


def test_industry_baseline_legacy_custom_entitlement_adds_account_custom():
    data = build_industry_baseline_plan(
        "考勤",
        installed_mod_ids=["attendance-industry"],
        entitled_mod_ids={"taiyangniao-pro"},
    )

    assert "taiyangniao-pro" in data["account_custom_mod_ids"]
    assert any(g["id"] == "account_custom" for g in data["groups"])


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


@pytest.mark.asyncio
async def test_onboarding_catalog_request_uses_authorization_session(monkeypatch):
    import app.enterprise.mod_entitlements as entitlements
    import app.infrastructure.auth.dependencies as auth_deps
    import app.mod_sdk.industry_baseline as industry_baseline

    called = {"sync": False}

    async def fake_sync(_request):
        called["sync"] = True

    monkeypatch.setattr(auth_deps, "resolve_session_user", lambda _request: None)
    monkeypatch.setattr(entitlements, "enterprise_mod_filter_active", lambda: True)
    monkeypatch.setattr(entitlements, "sync_entitlements_from_request", fake_sync)
    monkeypatch.setattr(entitlements, "is_admin_account_session", lambda: False)
    monkeypatch.setattr(
        entitlements,
        "get_cached_entitled_client_mod_ids",
        lambda: {"taiyangniao-pro"},
    )
    monkeypatch.setattr(
        industry_baseline,
        "build_onboarding_industry_catalog",
        lambda: {
            "open_industry_ids": ["涂料", "考勤"],
            "open_packages": [
                {"industry_id": "涂料", "mod_id": "coating-industry"},
                {"industry_id": "考勤", "mod_id": "attendance-industry"},
            ],
            "preview_packages": [],
        },
    )

    request = SimpleNamespace(headers={"Authorization": "Bearer sid-1"}, cookies={})
    catalog = await industry_baseline.build_onboarding_industry_catalog_for_request(request)

    assert called["sync"] is True
    assert catalog["enterprise_filter_applied"] is True
    assert catalog["open_industry_ids"] == ["考勤"]


@pytest.mark.asyncio
async def test_industry_baseline_request_uses_authorization_session(monkeypatch):
    import app.enterprise.mod_entitlements as entitlements
    import app.mod_sdk.industry_baseline as industry_baseline

    called = {"sync": False, "kwargs": None}

    async def fake_sync(_request):
        called["sync"] = True

    def fake_plan(_industry_id, **kwargs):
        called["kwargs"] = kwargs
        return {"industry_id": "考勤"}

    monkeypatch.setattr(entitlements, "enterprise_mod_filter_active", lambda: True)
    monkeypatch.setattr(entitlements, "sync_entitlements_from_request", fake_sync)
    monkeypatch.setattr(entitlements, "is_admin_account_session", lambda: False)
    monkeypatch.setattr(
        entitlements,
        "get_cached_entitled_client_mod_ids",
        lambda: {"taiyangniao-pro"},
    )
    monkeypatch.setattr(industry_baseline, "build_industry_baseline_plan", fake_plan)

    request = SimpleNamespace(headers={"Authorization": "Bearer sid-1"}, cookies={})
    result = await industry_baseline.build_industry_baseline_plan_for_request(request, "考勤")

    assert result == {"industry_id": "考勤"}
    assert called["sync"] is True
    assert called["kwargs"]["entitled_mod_ids"] == {"taiyangniao-pro"}


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
