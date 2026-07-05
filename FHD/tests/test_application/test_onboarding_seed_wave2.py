"""Wave 2: onboarding seed mapper + approval card tests."""

from __future__ import annotations

from app.application.onboarding_seed_mapper import resolve_onboarding_seed_profile
from app.application.workflow.approval_card import build_approval_card_payload


def test_attendance_profile_uses_subsystem_entities():
    profile = resolve_onboarding_seed_profile("考勤")
    assert profile.mod_id == "attendance-industry"
    assert profile.customer_entity == "部门"
    assert profile.product_entity == "人员"
    assert profile.demo_customer_name == "XC 演示部门"
    assert profile.demo_product_name == "XC 演示人员"


def test_coating_profile_uses_subsystem_entities():
    profile = resolve_onboarding_seed_profile("涂料")
    assert profile.mod_id == "coating-industry"
    assert profile.customer_entity == "客户"
    assert profile.product_entity == "产品"


def test_unknown_industry_falls_back():
    profile = resolve_onboarding_seed_profile("未知行业XYZ")
    assert profile.demo_customer_name == "XC 演示客户"
    assert profile.demo_product_name == "XC 演示产品"


def test_approval_card_payload_interactive():
    card = build_approval_card_payload(
        action="workflow_confirmation_required",
        inner={
            "plan_id": "p1",
            "blocking_nodes": ["n1"],
            "approval_required": False,
            "reason": "写库需确认",
            "todo": ["步骤1"],
        },
    )
    assert card["confirm_mode"] == "interactive"
    assert card["blocking_nodes"] == ["n1"]
    assert card["reason"] == "写库需确认"


def test_approval_card_payload_approval_mode():
    card = build_approval_card_payload(
        action="workflow_confirmation_required",
        inner={
            "approval_required": True,
            "approval_nodes": [{"tool_id": "products", "action": "create"}],
        },
    )
    assert card["confirm_mode"] == "approval"
    assert card["approval_required"] is True
