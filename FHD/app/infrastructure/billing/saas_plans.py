"""SaaS 阶梯定价 SSOT（config/saas_plans.json）。"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

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


def list_saas_plans() -> list[dict[str, Any]]:
    cfg = load_saas_plans_config()
    currency = str(cfg.get("currency") or "CNY")
    plans: list[dict[str, Any]] = []
    for raw in cfg.get("plans") or []:
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
        ):
            if key in raw:
                plan[key] = raw[key]
        plans.append(plan)
    return plans


def plan_by_id(
    plan_id: str, *, extra_plans: list[dict[str, Any]] | None = None
) -> dict[str, Any] | None:
    pid = (plan_id or "").strip()
    for p in list(extra_plans or []) + list_saas_plans():
        if p.get("id") == pid:
            return p
    return None


def _demo_payment_enabled() -> bool:
    return os.environ.get("FHD_DEMO_PAYMENT", "").strip().lower() in {"1", "true", "yes", "on"}


def is_saas_plan_id(plan_id: str) -> bool:
    pid = (plan_id or "").strip()
    return any(p.get("id") == pid for p in list_saas_plans())


_BUDGET_ALIASES: dict[str, str] = {
    "1–5 万": "1–5 万",
    "1-5 万": "1–5 万",
    "1-5万": "1–5 万",
    "5 万以内": "1–5 万",
    "5万以内": "1–5 万",
    "under-50k": "1–5 万",
    "5–10 万": "5–10 万",
    "5-10 万": "5–10 万",
    "5-10万": "5–10 万",
    "5–20 万": "5–10 万",
    "5-20 万": "5–10 万",
    "5-20万": "5–10 万",
    "50k-200k": "5–10 万",
    "10–50 万": "10–50 万",
    "10-50 万": "10–50 万",
    "10-50万": "10–50 万",
    "20–50 万": "10–50 万",
    "20-50 万": "10–50 万",
    "20-50万": "10–50 万",
    "200k-500k": "10–50 万",
    "50–100 万": "50–100 万",
    "50-100 万": "50–100 万",
    "50-100万": "50–100 万",
    "50 万以上": "50–100 万",
    "50万以上": "50–100 万",
    "500k-plus": "50–100 万",
}


def normalize_budget_range(raw: str | None) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    return _BUDGET_ALIASES.get(s, s)


def budget_permanent_map() -> dict[str, str]:
    cfg = load_saas_plans_config()
    raw = cfg.get("budget_permanent_map") or {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if k and v}


def permanent_plan_id_for_budget(budget_range: str | None) -> str:
    mapping = budget_permanent_map()
    normalized = normalize_budget_range(budget_range)
    if normalized and normalized in mapping:
        return mapping[normalized]
    return mapping.get("1–5 万") or mapping.get("5 万以内") or "saas-permanent-starter"


def permanent_plan_for_budget(budget_range: str | None) -> dict[str, Any] | None:
    return plan_by_id(permanent_plan_id_for_budget(budget_range))


def pricing_plans_for_budget(budget_range: str | None = None) -> list[dict[str, Any]]:
    """定价页展示：30 天试用 + 预算档位对应的永久购买。"""
    all_plans = list_saas_plans()
    trial = [p for p in all_plans if p.get("id") == "saas-trial-30"]
    perm_id = permanent_plan_id_for_budget(budget_range)
    permanent = [p for p in all_plans if p.get("id") == perm_id]
    return trial + permanent


def is_permanent_saas_plan_id(plan_id: str) -> bool:
    return (plan_id or "").strip().startswith("saas-permanent-")
