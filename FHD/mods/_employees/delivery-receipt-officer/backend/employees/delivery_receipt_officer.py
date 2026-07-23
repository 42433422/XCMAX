"""Deterministic, read-only delivery receipt verifier."""

from __future__ import annotations

from typing import Any

_REQUIRED_LINKS = ("goal_id", "artifact_id", "customer_id")


def run(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    receipt = payload.get("receipt")
    if not isinstance(receipt, dict):
        return _failed("receipt object is required", "missing_receipt")

    missing = [
        key for key in _REQUIRED_LINKS if not str(receipt.get(key) or "").strip()
    ]
    acceptance = receipt.get("acceptance")
    acceptance_rows = acceptance if isinstance(acceptance, list) else []
    accepted_rows = [
        row
        for row in acceptance_rows
        if isinstance(row, dict) and row.get("passed") is True
    ]
    value_evidence = receipt.get("value_evidence")
    has_value_evidence = isinstance(value_evidence, list) and any(
        str(item or "").strip() for item in value_evidence
    )
    blockers: list[str] = []
    if missing:
        blockers.append("missing_links:" + ",".join(missing))
    if not acceptance_rows:
        blockers.append("acceptance_missing")
    elif len(accepted_rows) != len(acceptance_rows):
        blockers.append("acceptance_not_passed")
    if not has_value_evidence:
        blockers.append("value_evidence_missing")

    approved = not blockers
    return {
        "ok": True,
        "status": "approved" if approved else "rejected",
        "summary": (
            f"交付回执已只读核验：目标、产物、客户三方关联"
            f"{'完整' if not missing else '不完整'}，{len(blockers)} 个阻塞项；未修改交付状态。"
        ),
        "linked": not missing,
        "acceptance_count": len(acceptance_rows),
        "blockers": blockers,
        "evidence": [
            "receipt.goal_id",
            "receipt.artifact_id",
            "receipt.customer_id",
            "receipt.acceptance",
            "receipt.value_evidence",
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
