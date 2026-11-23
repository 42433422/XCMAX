"""公开软件价格与历史授权目录（config/saas_plans.json）。"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

PERSONAL_PLAN_ID = "saas-personal-free"
PERMANENT_PLAN_ID = "saas-permanent-standard"

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _plans_path() -> Path:
    custom = (os.environ.get("FHD_SAAS_PLANS_FILE") or "").strip()
    if custom:
        return Path(custom)
    return _REPO_ROOT / "config" / "saas_plans.json"


@lru_cache(maxsize=1)
def load_saas_plans_config() -> dict[str, Any]:
    path = _plans_path()
    if not path.is_file():
        return {"trial_days": 14, "currency": "CNY", "plans": []}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        return {"trial_days": 14, "currency": "CNY", "plans": []}
    data.setdefault("trial_days", 14)
    data.setdefault("currency", "CNY")
    data.setdefault("plans", [])
    return data


def trial_days() -> int:
    try:
        return max(1, int(load_saas_plans_config().get("trial_days") or 14))
    except (TypeError, ValueError):
        return 14


def list_saas_plans(*, include_legacy: bool = False) -> list[dict[str, Any]]:
    cfg = load_saas_plans_config()
    currency = str(cfg.get("currency") or "CNY")
    plans: list[dict[str, Any]] = []
    rows = list(cfg.get("plans") or [])
    if include_legacy:
        rows += list(cfg.get("legacy_plans") or [])
    for raw in rows:
        if not isinstance(raw, dict) or not raw.get("id"):
            continue
        plan: dict[str, Any] = {
            "id": str(raw["id"]),
            "title": str(raw.get("title") or raw["id"]),
            "description": str(raw.get("description") or ""),
            "amount_cents": int(raw.get("amount_cents") or 0),
            "currency": currency,
            "badge": raw.get("badge"),
        }
        for key in (
            "quota_cents",
            "duration_days",
            "license_type",
            "expires_behavior",
            "account_tier",
            "features",
        ):
            if key in raw:
                plan[key] = raw[key]
        plans.append(plan)
    return plans


def plan_by_id(
    plan_id: str, *, extra_plans: list[dict[str, Any]] | None = None
) -> dict[str, Any] | None:
    pid = (plan_id or "").strip()
    for p in list(extra_plans or []) + list_saas_plans(include_legacy=True):
        if p.get("id") == pid:
            return p
    return None


def _demo_payment_enabled() -> bool:
    return os.environ.get("FHD_DEMO_PAYMENT", "").strip().lower() in {"1", "true", "yes", "on"}


def is_saas_plan_id(plan_id: str) -> bool:
    return plan_by_id(plan_id) is not None


def normalize_budget_range(raw: str | None) -> str:
    """预算只保留为销售线索，不归并为授权等级。"""
    return (raw or "").strip()


def budget_permanent_map() -> dict[str, str]:
    return {}


def permanent_plan_id_for_budget(budget_range: str | None) -> str:
    """兼容旧调用方；所有预算使用同一公开永久授权。"""
    return PERMANENT_PLAN_ID


def permanent_plan_for_budget(budget_range: str | None) -> dict[str, Any] | None:
    return plan_by_id(permanent_plan_id_for_budget(budget_range))


def pricing_plans_for_budget(budget_range: str | None = None) -> list[dict[str, Any]]:
    """免费个人、原体验与唯一永久授权；不按预算改变报价或权益。"""
    return list_saas_plans()


def is_permanent_saas_plan_id(plan_id: str) -> bool:
    return (plan_by_id(plan_id) or {}).get("license_type") == "permanent"
