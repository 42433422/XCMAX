"""XCAGI account-license catalog shared by registration and payment.

VIP/SVIP ``plan_*`` products are usage memberships. Only the ``saas-*``
products below authorize an XCAGI desktop account.
"""

from __future__ import annotations

import json
from typing import Any


ACCOUNT_LICENSE_PLANS: tuple[dict[str, Any], ...] = (
    {
        "id": "saas-trial-30",
        "title": "30 天试用",
        "description": "99 元体验账户，含 100 元额度，30 天到期后冻结，可购买永久授权继续使用。",
        "amount_cents": 9900,
        "quota_cents": 10000,
        "duration_days": 30,
        "license_type": "trial",
        "expires_behavior": "freeze",
        "account_tier": "normal",
        "badge": "试用",
        "features": ["XCAGI 桌面端账号授权", "30 天全功能体验", "含 100 元 AI 额度"],
    },
    {
        "id": "saas-permanent-starter",
        "title": "永久授权 · 1–5 万",
        "description": "1 个行业 Mod 定制 + 四部门 AI 员工配置 + 1-3 天上线交付 + 1 年免费维护。",
        "amount_cents": 4999900,
        "license_type": "permanent",
        "account_tier": "normal",
        "badge": "永久",
        "features": ["XCAGI 永久账号授权", "1 个行业 Mod 定制", "1 年免费维护"],
    },
    {
        "id": "saas-permanent-growth",
        "title": "永久授权 · 5–10 万",
        "description": "多行业 Mod 组合 + 现有系统对接 + 专属 AI 员工训练 + 2 年免费维护。",
        "amount_cents": 9999900,
        "license_type": "permanent",
        "account_tier": "pro",
        "badge": "永久",
        "features": ["XCAGI 永久账号授权", "多行业 Mod 与系统对接", "2 年免费维护"],
    },
    {
        "id": "saas-permanent-max",
        "title": "永久授权 · 10–50 万",
        "description": "集团多组织架构 + 3 年免费维护，一次购买永久使用。",
        "amount_cents": 49999900,
        "license_type": "permanent",
        "account_tier": "max",
        "badge": "永久",
        "features": ["XCAGI 永久账号授权", "集团多组织架构", "3 年免费维护"],
    },
    {
        "id": "saas-permanent-ultra",
        "title": "永久授权 · 50–100 万",
        "description": "源码托管 + 二开授权 + SLA 99.9% 保障，一次购买永久使用。",
        "amount_cents": 99999900,
        "license_type": "permanent",
        "account_tier": "ultra",
        "badge": "永久",
        "features": ["XCAGI 永久账号授权", "源码托管与二开授权", "SLA 99.9% 保障"],
    },
)

_BY_ID = {str(plan["id"]): plan for plan in ACCOUNT_LICENSE_PLANS}


def account_license_plan(plan_id: str | None) -> dict[str, Any] | None:
    row = _BY_ID.get((plan_id or "").strip())
    return dict(row) if row else None


def is_account_license_plan_id(plan_id: str | None) -> bool:
    return (plan_id or "").strip() in _BY_ID


def account_license_plan_rows() -> list[dict[str, Any]]:
    """Return rows compatible with the existing ``plan_templates`` table."""

    return [
        {
            "id": str(plan["id"]),
            "name": str(plan["title"]),
            "description": str(plan["description"]),
            "price": int(plan["amount_cents"]) / 100,
            "features_json": json.dumps(plan.get("features") or [], ensure_ascii=False),
            "quotas_json": "{}",
        }
        for plan in ACCOUNT_LICENSE_PLANS
    ]


def public_account_license_plans() -> list[dict[str, Any]]:
    return [
        {
            **dict(plan),
            "name": str(plan["title"]),
            "price": int(plan["amount_cents"]) / 100,
            "catalog": "account_license",
        }
        for plan in ACCOUNT_LICENSE_PLANS
    ]


__all__ = [
    "ACCOUNT_LICENSE_PLANS",
    "account_license_plan",
    "account_license_plan_rows",
    "is_account_license_plan_id",
    "public_account_license_plans",
]
