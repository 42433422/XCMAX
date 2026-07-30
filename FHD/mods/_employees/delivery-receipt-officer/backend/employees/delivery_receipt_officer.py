"""Deterministic, read-only delivery receipt verifier."""

from __future__ import annotations

from typing import Any

_REQUIRED_LINKS = ("goal_id", "artifact_id", "customer_id")


def run(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    receipt = payload.get("receipt")
    if not isinstance(receipt, dict):
        # 事故总线 / employee.task.done 等派发常不带 receipt。缺回执应记为只读驳回，
        # 不可 ok=False（否则大厅会因 handler_failed 长期挂红）。
        return {
            "ok": True,
            "status": "rejected",
            "summary": "无交付回执可核验：输入未提供 receipt；未修改交付状态。",
            "linked": False,
            "acceptance_count": 0,
            "blockers": ["missing_receipt"],
            "error_code": "missing_receipt",
            "evidence": [],
            "read_only": True,
            "side_effects": [],
        }

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
