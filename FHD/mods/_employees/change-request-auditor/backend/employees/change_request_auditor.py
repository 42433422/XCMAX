"""Deterministic strategic change review for the change-request-auditor."""

from __future__ import annotations

from typing import Any, Dict


async def run(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(payload or {})
    action = str(data.get("action") or "review").strip().lower()
    if action in {"help", "status"}:
        return {
            "ok": True,
            "summary": "Persy + Para + Retort 战略变更评审门已就绪（含 Retort 澄清门）",
            "items": [],
            "warnings": [],
            "error": "",
            "meta": {"handler": "direct_python", "action": action},
        }
    if action not in {"review", "audit", "run"}:
        return _error(f"unsupported_action:{action}")

    changed_files = data.get("changed_files")
    if not isinstance(changed_files, list) or not changed_files:
        diff = str(data.get("diff") or "")
        if diff:
            try:
                from retort_engine.pr_review import parse_unified_diff

                changed_files = parse_unified_diff(diff)
            except (ImportError, RuntimeError, ValueError) as exc:
                return _error(f"retort_diff_parse_failed:{type(exc).__name__}")
        else:
            changed_files = []

    try:
        from modstore_server.strategic_council import build_strategic_council_receipt

        receipt = build_strategic_council_receipt(
            proposal_id=str(data.get("proposal_id") or ""),
            run_id=str(data.get("run_id") or ""),
            package_id=str(data.get("package_id") or ""),
            version=str(data.get("version") or ""),
            package_sha256=str(data.get("package_sha256") or ""),
            goal_id=str(data.get("goal_id") or ""),
            loop_run_id=str(data.get("loop_run_id") or ""),
            para_task_id=str(data.get("para_task_id") or ""),
            strategy_intent=str(data.get("strategy_intent") or data.get("task") or ""),
            changed_files=changed_files,
            persy_evidence=(
                data.get("persy_evidence")
                if isinstance(data.get("persy_evidence"), dict)
                else {}
            ),
            para_evidence=(
                data.get("para_evidence")
                if isinstance(data.get("para_evidence"), dict)
                else {}
            ),
            veto_state=(
                data.get("veto_state")
                if isinstance(data.get("veto_state"), dict)
                else {}
            ),
        )
    except (ImportError, RuntimeError, TypeError, ValueError) as exc:
        return _error(f"strategic_council_failed:{type(exc).__name__}")

    verified = receipt.get("verified") is True
    return {
        "ok": verified,
        "summary": (
            "战略三席已放行变更"
            if verified
            else "战略三席阻止变更：" + ",".join(receipt.get("blockers") or [])
        ),
        "items": [receipt],
        "warnings": [] if verified else list(receipt.get("blockers") or []),
        "error": "" if verified else "strategic_council_not_approved",
        "meta": {
            "handler": "direct_python",
            "action": "review",
            "employee_id": str(ctx.get("employee_id") or "change-request-auditor"),
            "receipt_id": receipt.get("receipt_id"),
        },
    }


def _error(message: str) -> Dict[str, Any]:
    return {
        "ok": False,
        "summary": message,
        "items": [],
        "warnings": [],
        "error": message,
        "meta": {"handler": "direct_python", "action": "review"},
    }
