"""Semantic verification for Agent tool executions.

Tool schema validation proves that an adapter returned the expected envelope.
It does not prove that the user's business goal was completed. This module
adds a small, deterministic verification layer that records concrete receipts
without asking an LLM to judge its own work.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
from app.utils.operational_errors import RECOVERABLE_ERRORS


@dataclass(frozen=True)
class ExecutionVerification:
    accepted: bool
    verified: bool
    status: str
    verifier: str
    reason: str
    evidence: dict[str, Any]
    recovery_hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _present_keys(payload: dict[str, Any], keys: list[str]) -> list[str]:
    present: list[str] = []
    for key in keys:
        if key not in payload:
            continue
        value = payload.get(key)
        if value is None or value == "":
            continue
        present.append(key)
    return present


def _safe_evidence(output: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    for key in keys:
        if key not in output:
            continue
        value = output.get(key)
        if isinstance(value, list):
            evidence[key] = {"count": len(value)}
        elif isinstance(value, dict):
            evidence[key] = {"keys": sorted(str(item) for item in value.keys())[:20]}
        elif isinstance(value, (str, int, float, bool)) or value is None:
            evidence[key] = value
    return evidence


def verify_tool_execution(
    tool_id: str,
    action: str,
    params: dict[str, Any] | None,
    output: dict[str, Any] | None,
) -> ExecutionVerification:
    payload = dict(output or {})
    spec = get_tool_action_spec(tool_id, action)
    contract = dict(getattr(spec, "verification", {}) or {})
    verifier = str(contract.get("verifier") or "tool_contract")
    required = [str(item) for item in contract.get("required_evidence") or [] if str(item).strip()]

    if payload.get("success") is not True:
        reason = str(
            payload.get("message")
            or payload.get("error")
            or payload.get("error_code")
            or "工具未返回 success=true"
        )
        return ExecutionVerification(
            accepted=False,
            verified=False,
            status="failed",
            verifier=verifier,
            reason=reason,
            evidence=_safe_evidence(payload, ["error_code", "message", "error"]),
            recovery_hint="按工具错误信息修复参数或外部依赖后重试。",
        )

    if verifier == "employee_result":
        try:
            from app.application.employee_runtime.result_verifier import (
                verify_employee_run_result,
            )

            employee_id = str(
                (params or {}).get("employee_id") or payload.get("employee_id") or "employee"
            )
            ok, reason = verify_employee_run_result(employee_id, payload)
        except RECOVERABLE_ERRORS as exc:
            ok, reason = False, f"员工结果验收器不可用: {exc}"
        return ExecutionVerification(
            accepted=bool(ok),
            verified=bool(ok),
            status="verified" if ok else "failed",
            verifier=verifier,
            reason=reason,
            evidence=_safe_evidence(
                payload, ["employee_id", "summary", "items", "sheets", "outputs", "data"]
            ),
            recovery_hint=""
            if ok
            else "检查员工输出是否包含可验收的 summary、items、sheets、outputs 或 data。",
        )

    present = _present_keys(payload, required)
    if present:
        return ExecutionVerification(
            accepted=True,
            verified=True,
            status="verified",
            verifier=verifier,
            reason=f"已取得业务回执: {', '.join(present)}",
            evidence=_safe_evidence(payload, present),
        )

    return ExecutionVerification(
        accepted=True,
        verified=False,
        status="inconclusive",
        verifier=verifier,
        reason="工具执行成功，但没有返回可独立核验的业务回执",
        evidence=_safe_evidence(payload, ["message"]),
        recovery_hint="补充查询回读、业务记录 ID、变更计数、打印任务号或产物路径后再宣称完成。",
    )


def summarize_run_verification(tool_calls: list[Any]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for call in tool_calls:
        metadata = getattr(call, "metadata", {})
        verification = (
            metadata.get("verification")
            if isinstance(metadata, dict) and isinstance(metadata.get("verification"), dict)
            else {}
        )
        if verification:
            records.append(dict(verification))
    verified_count = sum(1 for item in records if item.get("verified") is True)
    failed_count = sum(1 for item in records if item.get("accepted") is False)
    inconclusive_count = sum(
        1 for item in records if item.get("accepted") is True and item.get("verified") is not True
    )
    return {
        "goal_verified": bool(records) and failed_count == 0 and inconclusive_count == 0,
        "verification_count": len(records),
        "verified_count": verified_count,
        "inconclusive_count": inconclusive_count,
        "failed_count": failed_count,
        "status": (
            "verified"
            if records and failed_count == 0 and inconclusive_count == 0
            else "failed"
            if failed_count
            else "inconclusive"
        ),
    }
