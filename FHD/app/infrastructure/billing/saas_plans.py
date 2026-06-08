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
        plans.append(
            {
                "id": str(raw["id"]),
                "title": str(raw.get("title") or raw["id"]),
                "description": str(raw.get("description") or ""),
                "amount_cents": int(raw.get("amount_cents") or 0),
                "currency": currency,
                "badge": raw.get("badge"),
            }
        )
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
    return any(p.get("id") == pid for p in list_saas_plans(include_demo=False))
