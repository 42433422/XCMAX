"""Aggregate enterprise adoption evidence into a deterministic funnel."""

from __future__ import annotations

from collections import Counter
from typing import Any


def run(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    tenants = payload.get("tenants")
    if not isinstance(tenants, list):
        return _failed("tenants must be an array")
    if not tenants:
        return {
            "ok": True,
            "status": "no_data",
            "summary": "已只读查询企业租户数据源，当前没有可观测企业租户。",
            "funnel": {
                "observed": 0,
                "activated": 0,
                "active_30d": 0,
                "feature_adopted": 0,
                "value_milestone_reached": 0,
                "activation_rate": 0.0,
                "adoption_rate": 0.0,
                "value_rate": 0.0,
            },
            "blockers": [],
            "invalid_fields": [],
            "evidence": ["input.tenants", "authoritative_empty_observation"],
            "read_only": True,
            "side_effects": [],
            "no_effect": True,
        }

    activated = active = adopted = value_reached = 0
    blocker_counts: Counter[str] = Counter()
    invalid: list[str] = []
    seen: set[str] = set()
    for index, tenant in enumerate(tenants):
        if not isinstance(tenant, dict):
            invalid.append(f"tenants[{index}]_not_object")
            continue
        tenant_id = str(tenant.get("tenant_id") or "").strip()
        if not tenant_id or tenant_id in seen:
            invalid.append(f"tenants[{index}]_missing_or_duplicate_id")
            continue
        seen.add(tenant_id)
        days = tenant.get("active_days_30")
        if not isinstance(days, int) or not 0 <= days <= 30:
            invalid.append(f"tenants[{index}].active_days_30")
            continue
        features = tenant.get("adopted_features")
        blockers = tenant.get("blocked_reasons")
        milestones = tenant.get("value_milestones")
        if not all(isinstance(value, list) for value in (features, blockers, milestones)):
            invalid.append(f"tenants[{index}]_list_fields")
            continue
        if tenant.get("activated") is True:
            activated += 1
        if days > 0:
            active += 1
        if any(str(value).strip() for value in features):
            adopted += 1
        if any(str(value).strip() for value in milestones):
            value_reached += 1
        blocker_counts.update(str(value).strip() for value in blockers if str(value).strip())

    total = len(seen)
    funnel = {
        "observed": total,
        "activated": activated,
        "active_30d": active,
        "feature_adopted": adopted,
        "value_milestone_reached": value_reached,
        "activation_rate": round(activated / total, 4) if total else 0.0,
        "adoption_rate": round(adopted / total, 4) if total else 0.0,
        "value_rate": round(value_reached / total, 4) if total else 0.0,
    }
    blockers_out = [
        {"reason": reason, "tenant_count": count}
        for reason, count in sorted(blocker_counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    approved = not invalid
    return {
        "ok": True,
        "status": "approved" if approved else "rejected",
        "summary": (
            f"已只读汇总 {total} 个企业租户：激活 {activated}、30 日活跃 {active}、"
            f"功能采纳 {adopted}、价值达成 {value_reached}；输入问题 {len(invalid)} 个。"
        ),
        "funnel": funnel,
        "blockers": blockers_out,
        "invalid_fields": invalid,
        "evidence": ["input.tenants", "deterministic funnel aggregation"],
        "read_only": True,
        "side_effects": [],
    }


def _failed(message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "failed",
        "summary": message,
        "funnel": {},
        "blockers": [],
        "evidence": [],
        "read_only": True,
        "side_effects": [],
    }
