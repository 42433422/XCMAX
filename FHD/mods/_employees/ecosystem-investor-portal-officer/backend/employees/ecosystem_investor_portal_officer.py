"""Build a deterministic public investor snapshot without exposing private data."""

from __future__ import annotations

from typing import Any

_FORBIDDEN_KEYS = {
    "amount",
    "api_key",
    "customer_id",
    "email",
    "phone",
    "revenue",
    "secret",
    "token",
    "transaction_id",
    "user_id",
}


def _forbidden_paths(value: Any, prefix: str = "input") -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}"
            if str(key).strip().lower() in _FORBIDDEN_KEYS:
                paths.append(path)
            paths.extend(_forbidden_paths(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(_forbidden_paths(child, f"{prefix}[{index}]"))
    return sorted(set(paths))


def run(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    milestones = payload.get("milestones")
    risks = payload.get("risks")
    if not isinstance(milestones, list) or not isinstance(risks, list):
        return _failed("milestones and risks must be arrays")

    redacted_fields = _forbidden_paths(payload)
    normalized_milestones: list[dict[str, Any]] = []
    normalized_risks: list[dict[str, Any]] = []
    invalid: list[str] = []

    for index, item in enumerate(milestones):
        if not isinstance(item, dict) or not str(item.get("id") or "").strip():
            invalid.append(f"milestones[{index}].id")
            continue
        progress = item.get("progress_pct")
        if not isinstance(progress, (int, float)) or not 0 <= float(progress) <= 100:
            invalid.append(f"milestones[{index}].progress_pct")
            continue
        normalized_milestones.append(
            {
                "id": str(item["id"])[:128],
                "status": str(item.get("status") or "unknown")[:32],
                "progress_pct": round(float(progress), 2),
                "evidence_ref": str(item.get("evidence_ref") or "")[:256],
            }
        )

    for index, item in enumerate(risks):
        if not isinstance(item, dict) or not str(item.get("id") or "").strip():
            invalid.append(f"risks[{index}].id")
            continue
        normalized_risks.append(
            {
                "id": str(item["id"])[:128],
                "severity": str(item.get("severity") or "unknown")[:24],
                "status": str(item.get("status") or "unknown")[:32],
                "mitigation": str(item.get("mitigation") or "")[:300],
            }
        )

    approved = not invalid and not redacted_fields
    snapshot = {
        "milestone_count": len(normalized_milestones),
        "milestones": normalized_milestones,
        "open_risk_count": sum(
            1 for item in normalized_risks if item["status"] not in {"closed", "resolved"}
        ),
        "risks": normalized_risks,
    }
    return {
        "ok": True,
        "status": "approved" if approved else "rejected",
        "summary": (
            f"已只读校验 {len(normalized_milestones)} 个里程碑和 {len(normalized_risks)} 个风险；"
            f"隐私字段 {len(redacted_fields)} 个，格式问题 {len(invalid)} 个，未输出客户或财务明细。"
        ),
        "public_snapshot": snapshot if approved else {},
        "redacted_fields": redacted_fields,
        "invalid_fields": invalid,
        "evidence": ["input.milestones", "input.risks", "public-field allowlist"],
        "read_only": True,
        "side_effects": [],
    }


def _failed(message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "failed",
        "summary": message,
        "public_snapshot": {},
        "redacted_fields": [],
        "evidence": [],
        "read_only": True,
        "side_effects": [],
    }
