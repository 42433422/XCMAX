"""Deterministic, read-only ecosystem delivery status reporter."""

from __future__ import annotations

from collections import Counter
from typing import Any

_VALID_SLA = {"met", "at_risk", "breached"}


def run(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    deliveries = payload.get("deliveries")
    if not isinstance(deliveries, list):
        return _failed("deliveries must be a non-empty list", "missing_deliveries")
    if not deliveries:
        return {
            "ok": True,
            "status": "no_data",
            "summary": "已只读查询客户价值交付回执，当前没有已验证交付可汇总；未发送报告。",
            "sla_counts": {},
            "blockers": [],
            "evidence": ["input.deliveries", "authoritative_empty_observation"],
            "read_only": True,
            "side_effects": [],
            "no_effect": True,
        }

    blockers: list[dict[str, Any]] = []
    statuses: Counter[str] = Counter()
    for index, raw in enumerate(deliveries):
        row = raw if isinstance(raw, dict) else {}
        missing = [
            key
            for key in ("partner_id", "delivery_receipt_id", "owner", "sla_status")
            if not str(row.get(key) or "").strip()
        ]
        status = str(row.get("sla_status") or "").strip().lower()
        if status and status not in _VALID_SLA:
            missing.append("sla_status_invalid")
        if (
            status in {"at_risk", "breached"}
            and not str(row.get("next_step") or "").strip()
        ):
            missing.append("next_step")
        if missing:
            blockers.append({"index": index, "reasons": missing})
        else:
            statuses[status] += 1

    approved = not blockers
    return {
        "ok": True,
        "status": "approved" if approved else "rejected",
        "summary": (
            f"伙伴交付状态已只读汇总：{len(deliveries)} 条记录，"
            f"SLA 违约 {statuses['breached']} 条，{len(blockers)} 条证据不完整；未发送报告。"
        ),
        "sla_counts": dict(sorted(statuses.items())),
        "blockers": blockers,
        "evidence": [
            "deliveries[].delivery_receipt_id",
            "deliveries[].sla_status",
            "deliveries[].owner",
        ],
        "read_only": True,
        "side_effects": [],
    }


def _failed(message: str, code: str) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "failed",
        "summary": message,
        "error_code": code,
        "evidence": [],
        "read_only": True,
        "side_effects": [],
    }
