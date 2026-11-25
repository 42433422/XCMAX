"""XCAGI account-license catalog shared by registration and payment.

VIP/SVIP ``plan_*`` products are usage memberships. Only the ``saas-*``
products below authorize an XCAGI desktop account.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PERSONAL_PLAN_ID = "saas-personal-free"
STANDARD_PLAN_ID = "saas-permanent-standard"


ACCOUNT_LICENSE_PLANS: tuple[dict[str, Any], ...] = (
    {
        "id": PERSONAL_PLAN_ID,
        "title": "个人使用版",
        "description": "免费使用 XCAGI 桌面端基础功能，不含任何 Mod。",
        "amount_cents": 0,
        "quota_cents": 500,
        "license_type": "free",
        "account_tier": "normal",
        "badge": "免费",
        "features": [
            "桌面端基础功能",
            "验证邮箱且活动预算可用时可领取 5 元 AI 额度",
            "无 Mod 权益",
        ],
    },
    {
        "id": "saas-trial-30",
        "title": "30 天全功能体验",
        "description": "用 30 天完整体验 XCAGI，包含 100 元 AI 使用额度。",
        "amount_cents": 9900,
        "quota_cents": 10000,
        "duration_days": 30,
        "license_type": "trial",
        "expires_behavior": "freeze",
        "account_tier": "normal",
        "badge": "体验",
        "features": ["XCAGI 桌面端完整功能", "30 天使用期", "100 元 AI 使用额度"],
    },
    {
        "id": STANDARD_PLAN_ID,
        "title": "XCAGI 软件买断",
        "description": "3,000 元一次购买，永久使用已购软件；定制按确认的报价收费，AI 调用按量另计。",
        "amount_cents": 300000,
        "quota_cents": 0,
        "license_type": "permanent",
        "account_tier": "normal",
        "badge": "一次购买",
        "features": ["软件永久使用", "无软件续租费", "定制另行报价", "AI 调用按量付费"],
    },
)

# Keep the original metadata for existing grants and in-flight paid orders.
# These products are no longer offered for new checkout.
LEGACY_ACCOUNT_LICENSE_PLANS: tuple[dict[str, Any], ...] = (
    {
        "id": "saas-permanent-starter",
        "title": "企业启航版",
        "description": "适合首次部署 XCAGI 的企业，包含 1 个行业 Mod、四部门 AI 员工配置、上线交付与 1 年维护。",
        "amount_cents": 4999900,
        "license_type": "permanent",
        "account_tier": "normal",
        "badge": "永久使用",
        "features": [
            "永久使用 XCAGI",
            "1 个行业 Mod",
            "四部门 AI 员工配置",
            "1 年维护",
        ],
    },
    {
        "id": "saas-permanent-growth",
        "title": "企业成长版",
        "description": "适合需要多业务协同或现有系统对接的企业，包含专属 AI 员工训练与 2 年维护。",
        "amount_cents": 9999900,
        "license_type": "permanent",
        "account_tier": "pro",
        "badge": "永久使用",
        "features": [
            "永久使用 XCAGI",
            "多行业 Mod 组合",
            "现有系统对接",
            "专属 AI 员工训练",
            "2 年维护",
        ],
    },
    {
        "id": "saas-permanent-max",
        "title": "集团协同版",
        "description": "适合多组织、多分支机构协同的集团企业，包含集团架构支持与 3 年维护。",
        "amount_cents": 49999900,
        "license_type": "permanent",
        "account_tier": "max",
        "badge": "永久使用",
        "features": ["永久使用 XCAGI", "集团多组织架构", "多分支协同", "3 年维护"],
    },
    {
        "id": "saas-permanent-ultra",
        "title": "企业旗舰版",
        "description": "适合需要深度定制与长期技术保障的企业，包含源码托管、二次开发授权与 99.9% SLA。",
        "amount_cents": 99999900,
        "license_type": "permanent",
        "account_tier": "ultra",
        "badge": "永久使用",
        "features": ["永久使用 XCAGI", "源码托管", "二次开发授权", "99.9% SLA"],
    },
)

_BY_ID = {str(plan["id"]): plan for plan in (*ACCOUNT_LICENSE_PLANS, *LEGACY_ACCOUNT_LICENSE_PLANS)}
_LEGACY_IDS = frozenset(str(plan["id"]) for plan in LEGACY_ACCOUNT_LICENSE_PLANS)


def account_license_plan(plan_id: str | None) -> dict[str, Any] | None:
    row = _BY_ID.get((plan_id or "").strip())
    return dict(row) if row else None


def is_account_license_plan_id(plan_id: str | None) -> bool:
    return (plan_id or "").strip() in _BY_ID


def is_legacy_account_license_plan_id(plan_id: str | None) -> bool:
    return (plan_id or "").strip() in _LEGACY_IDS


def account_license_priority(plan_id: str | None) -> tuple[int, int, int]:
    """Select durable purchased access before a newer trial or lower tier."""
    plan = account_license_plan(plan_id) or {}
    return (
        {"free": 0, "trial": 1, "permanent": 2}.get(str(plan.get("license_type")), -1),
        {"normal": 0, "pro": 1, "max": 2, "ultra": 3}.get(str(plan.get("account_tier")), 0),
        int(is_legacy_account_license_plan_id(plan_id)),
    )


def account_license_plan_rows() -> list[dict[str, Any]]:
    """Seed current and historical rows without rewriting order snapshots."""

    return [
        {
            "id": str(plan["id"]),
            "name": str(plan["title"]),
            "description": str(plan["description"]),
            "price": int(plan["amount_cents"]) / 100,
            "features_json": json.dumps(plan.get("features") or [], ensure_ascii=False),
            "quotas_json": "{}",
        }
        for plan in (*ACCOUNT_LICENSE_PLANS, *LEGACY_ACCOUNT_LICENSE_PLANS)
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


def public_commercial_terms() -> dict[str, Any]:
    """Read the packaged projection of FHD/config/saas_plans.json."""
    path = Path(__file__).with_name("data") / "commerce_terms.generated.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Invalid packaged commercial terms")
    return dict(data)


__all__ = [
    "ACCOUNT_LICENSE_PLANS",
    "LEGACY_ACCOUNT_LICENSE_PLANS",
    "account_license_plan",
    "account_license_priority",
    "account_license_plan_rows",
    "is_account_license_plan_id",
    "is_legacy_account_license_plan_id",
    "public_account_license_plans",
    "public_commercial_terms",
]
