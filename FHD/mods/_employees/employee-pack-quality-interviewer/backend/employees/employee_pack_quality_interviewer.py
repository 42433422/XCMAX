"""Deterministic, read-only employee capability closure interviewer."""

from __future__ import annotations

from typing import Any

_HOLLOW_HANDLERS = {"echo", "llm_md"}


def run(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    capability = payload.get("capability")
    if not isinstance(capability, dict):
        return _failed("capability object is required", "missing_capability")

    input_contract = capability.get("input_contract")
    handlers = capability.get("handlers") if isinstance(capability.get("handlers"), list) else []
    acceptance = capability.get("acceptance")
    gaps: list[str] = []
    if not isinstance(input_contract, dict) or not input_contract.get("required"):
        gaps.append("real_input_contract_missing")
    normalized_handlers = {str(item).strip() for item in handlers if str(item).strip()}
    if not normalized_handlers or normalized_handlers.issubset(_HOLLOW_HANDLERS):
        gaps.append("executable_handler_missing")
    if not isinstance(acceptance, list) or not any(str(item or "").strip() for item in acceptance):
        gaps.append("acceptance_contract_missing")

    approved = not gaps
    return {
        "ok": True,
        "status": "approved" if approved else "rejected",
        "summary": (
            f"员工能力闭环已只读访谈核验：输入、动作、验收三段中发现 {len(gaps)} 个缺口；"
            "未修改员工包。"
        ),
        "closure_ready": approved,
        "gaps": gaps,
        "recommendations": [f"implement:{gap}" for gap in gaps],
        "evidence": [
            "capability.input_contract",
            "capability.handlers",
            "capability.acceptance",
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
