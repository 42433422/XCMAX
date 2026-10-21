"""事故小组失败闭环：先分类，再按类处置，设上限，到上限升级终极员工并回写工单。

分类（category）：
  - model_unavailable：模型不被当前账号/渠道支持 → 交模型降级层（本模块只调用预留接口）
  - code：代码问题（含 CI 失败、实现错误）→ 失败日志回喂上下文，同岗再修一轮
  - environment：网络/限流/登录/401 等 → 指数退避后重试
  - role_timeout：外层角色超时，任务可能仍在跑 → 不重派（防并行），直接升级
  - quota：配额/欠费 → 改代码或重试都无效，直接升级
同一角色串行处理，任何时刻只有一个在跑的重派。
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List

from modstore_server.customer_issue_delivery_contract import (
    execution_requires_reconciliation,
    execution_succeeded,
)
from modstore_server.incident_team_handler_digest import handler_output_digest
from modstore_server.llm_failure_classifier import (
    FAILURE_KIND_MODEL_UNSUPPORTED,
    FAILURE_KIND_NONE,
    FAILURE_KIND_QUOTA,
    FAILURE_KIND_ROLE_TIMEOUT,
    FAILURE_KIND_TRANSIENT,
    classify_failure_kind,
)
from modstore_server.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

MAX_ROUNDS_ENV = "MODSTORE_INCIDENT_TEAM_REPAIR_MAX_ROUNDS"
BACKOFF_ENV = "MODSTORE_INCIDENT_TEAM_RETRY_BACKOFF_SEC"
ESCALATE_TO = "ultimate_employee"
_AUTH_NEEDLES = (
    "401",
    "unauthorized",
    "not logged in",
    "login required",
    "未登录",
    "鉴权失败",
)


def _env_int(name: str, default: int, low: int = 0) -> int:
    try:
        return max(low, int(os.environ.get(name) or default))
    except ValueError:
        return default


def max_rounds() -> int:
    return _env_int(MAX_ROUNDS_ENV, 3)


def _sleep(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def failure_text(result: Dict[str, Any]) -> str:
    """顶层 error 为空时，取嵌套 handler / Para 子任务的报错，避免“无原因”静默停摆。"""
    parts = [str(result.get("error") or result.get("reason") or "")]
    for out in _list(_dict(result.get("result")).get("outputs")):
        if not isinstance(out, dict):
            continue
        parts.append(str(out.get("error") or ""))
        subtasks = _list(_dict(out.get("para_result")).get("subtasks"))
        parts += [str(_dict(sub).get("last_error") or "") for sub in subtasks]
    return " | ".join(p.strip() for p in parts if p and p.strip())[:2000]


def categorize(error_text: str) -> tuple[str, str]:
    kind = classify_failure_kind(error_text)
    low = (error_text or "").lower()
    if kind == FAILURE_KIND_ROLE_TIMEOUT:
        return kind, "role_timeout"
    if kind == FAILURE_KIND_QUOTA:
        return kind, "quota"
    if kind == FAILURE_KIND_MODEL_UNSUPPORTED:
        return kind, "model_unavailable"
    if kind == FAILURE_KIND_TRANSIENT or any(n in low for n in _AUTH_NEEDLES):
        return kind, "environment"
    if kind == FAILURE_KIND_NONE:
        return kind, "unknown"
    return kind, "code"


def request_model_fallback(**request: Any) -> Dict[str, Any]:
    """模型降级层预留接口：网关（另一 PR）提供 ``model_fallback_gateway.request_fallback``。"""
    try:
        from modstore_server import model_fallback_gateway  # type: ignore[attr-defined]
    except ImportError:
        return {"ok": False, "reason": "model_fallback_gateway_not_installed"}
    try:
        out = model_fallback_gateway.request_fallback(**request)
        return out if isinstance(out, dict) else {"ok": False, "reason": "invalid_result"}
    except RECOVERABLE_ERRORS as exc:
        return {"ok": False, "reason": f"model_fallback_error:{str(exc)[:200]}"}


def _is_handler_failed(result: Dict[str, Any]) -> bool:
    return bool(result.get("handler_failed")) or (
        str(result.get("status") or "").strip().lower() == "handler_failed"
    )


def _mark_recovered(row: Dict[str, Any], result: Dict[str, Any]) -> None:
    row.update(ok=True, status="completed", result=result)
    row["handler_outputs"] = handler_output_digest(result)
    for key in ("attempt_id", "verified_fix_attempt_id"):
        if result.get(key):
            row[key] = result[key]


def _retry_ok(result: Dict[str, Any]) -> bool:
    return (
        str(result.get("status") or "").strip().lower() == "success"
        and not _is_handler_failed(result)
        and not result.get("error")
    ) or (not _is_handler_failed(result) and execution_succeeded(result))


def run_failure_loop(
    *,
    retry_member,
    event_id: int,
    results: List[Dict[str, Any]],
    team_plan: Dict[str, Any],
    payload: Dict[str, Any],
    event_type: str,
    source: str,
    uid: int,
    transient_limit: int | None = None,
) -> List[Dict[str, Any]]:
    """逐个处置 handler_failed 的角色；重派成功时就地更新该行（并对 fix 重跑一次 verify）。"""
    team = _list(team_plan.get("team"))
    members = {str(m.get("role") or ""): m for m in team if isinstance(m, dict)}
    limit = max_rounds()
    backoff = _env_int(BACKOFF_ENV, 5)
    follow_ups: List[Dict[str, Any]] = []
    for row in list(results):
        result = _dict(row.get("result"))
        if execution_requires_reconciliation(result):
            row.update(ok=False, status="pending")
            follow_ups.append(
                {
                    "role": row.get("role"),
                    "employee_id": row.get("employee_id"),
                    "action": "reconcile_original_attempt",
                    "category": "unknown",
                    "attempts": 0,
                    "ok": False,
                    "retryable": False,
                    "requires_reconciliation": True,
                    "attempt_id": row.get("attempt_id") or result.get("attempt_id"),
                    "handler_outputs": handler_output_digest(result),
                }
            )
            continue
        if not _is_handler_failed(result):
            continue
        role = str(row.get("role") or "")
        employee_id = str(row.get("employee_id") or "")
        error = failure_text(result)
        kind, category = categorize(error)
        fu: Dict[str, Any] = {
            "role": role,
            "employee_id": employee_id,
            "failure_kind": kind,
            "category": category,
            "error": error[:500],
            "attempts": 0,
            "max_rounds": limit,
            "action": "",
            "ok": False,
            "retry_result": None,
            "escalated_to": "",
        }
        while True:
            if result.get("retryable") is False:
                fu["action"] = "nonretryable_need_human"
                break
            if category == "role_timeout":
                fu["action"] = "role_timeout_no_retry_need_human"
                break
            if category == "quota":
                fu["action"] = "quota_blocked_need_human"
                break
            if category == "unknown":
                fu["action"] = "no_action_unknown_kind"
                break
            if category == "model_unavailable":
                fu["action"] = "model_unsupported_need_fallback"
                hook = request_model_fallback(
                    event_id=event_id,
                    role=role,
                    employee_id=employee_id,
                    error=error[:500],
                )
                fu["model_fallback"] = {k: hook.get(k) for k in ("ok", "reason", "model")}
                if hook.get("ok"):
                    fu["action"] = "model_fallback_requested"
                    fu["ok"] = True
                break
            cap = limit
            if category == "environment" and transient_limit is not None:
                cap = min(cap, transient_limit)
            if fu["attempts"] >= cap:
                break
            if role == "fix":
                verify = next((item for item in results if item.get("role") == "verify"), None)
                if verify is not None:
                    verify.update(
                        ok=False,
                        status="verification_invalidated",
                        verified_fix_attempt_id="",
                    )
            fu["attempts"] += 1
            fu["action"] = (
                "transient_retry" if category == "environment" else "code_retry_with_feedback"
            )
            if category == "environment":
                _sleep(min(60, backoff * 2 ** (fu["attempts"] - 1)))
            prev = {str(r.get("role") or ""): r for r in results if isinstance(r, dict)}
            try:
                retry = retry_member(
                    event_id=event_id,
                    member=members.get(role, {"employee_id": employee_id, "role": role}),
                    team_plan=team_plan,
                    payload=payload,
                    event_type=event_type,
                    source=source,
                    uid=uid,
                    prev_results=prev,
                    **({"feedback": error} if category == "code" else {}),
                )
            except RECOVERABLE_ERRORS as exc:
                retry = {
                    "status": "unknown",
                    "handler_failed": True,
                    "outcome": "unknown",
                    "requires_reconciliation": True,
                    "retryable": False,
                    "error": str(exc)[:500],
                }
                logger.exception("incident_team: retry failed event_id=%s role=%s", event_id, role)
            retry = retry if isinstance(retry, dict) else {"status": "failed", "error": "invalid"}
            fu["retry_result"] = {
                k: v for k, v in retry.items() if k in {"status", "ok", "error", "handler_failed"}
            }
            if execution_requires_reconciliation(retry):
                row.update(
                    ok=False,
                    status="pending",
                    result=retry,
                    handler_outputs=handler_output_digest(retry),
                )
                fu.update(
                    action="reconcile_original_attempt",
                    requires_reconciliation=True,
                    retryable=False,
                )
                break
            if retry.get("retryable") is False:
                fu["action"] = "nonretryable_need_human"
                break
            if _retry_ok(retry):
                fu["ok"] = True
                _mark_recovered(row, retry)
                break
            error = failure_text(retry) or error
            kind, category = categorize(error)
            fu.update(last_category=category, error=error[:500])
        if not fu["ok"] and not fu.get("requires_reconciliation"):
            fu["action"] = fu["action"] or "retry_disabled_escalated"
            fu["escalated_to"] = ESCALATE_TO
            fu["need_human"] = True
            fu["reason"] = (
                f"{category} 失败，已自动处理 {fu['attempts']}/{limit} 轮未恢复：{error[:200]}"
            )
            logger.warning(
                "incident_team: escalate event_id=%s role=%s category=%s attempts=%s",
                event_id,
                role,
                category,
                fu["attempts"],
            )
        elif role == "fix":
            ctx = {
                "event_id": event_id,
                "team_plan": team_plan,
                "payload": payload,
                "event_type": event_type,
                "source": source,
                "uid": uid,
            }
            _rerun_verify(retry_member, results, members, ctx)
        follow_ups.append(fu)
    return follow_ups


def _rerun_verify(retry_member, results, members, ctx: Dict[str, Any]) -> None:
    """fix 重派成功后，原 verify 是对失败修复的结论，必须重验一次。"""
    verify = next((r for r in results if r.get("role") == "verify"), None)
    if verify is None:
        return
    verify.update(ok=False, status="verification_invalidated", verified_fix_attempt_id="")
    member = members.get("verify") or {
        "employee_id": verify.get("employee_id"),
        "role": "verify",
    }
    prev = {str(r.get("role") or ""): r for r in results if isinstance(r, dict)}
    try:
        out = retry_member(member=member, prev_results=prev, **ctx)
    except RECOVERABLE_ERRORS as exc:
        out = {
            "ok": False,
            "status": "unknown",
            "outcome": "unknown",
            "requires_reconciliation": True,
            "error": f"verify rerun unavailable: {type(exc).__name__}",
        }
        logger.exception("incident_team: verify rerun failed")
    if isinstance(out, dict):
        verify.update(
            result=out,
            handler_outputs=handler_output_digest(out),
            status="pending" if execution_requires_reconciliation(out) else "failed",
        )
        if _retry_ok(out):
            _mark_recovered(verify, out)


def loop_summary(follow_ups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    keys = (
        "role",
        "category",
        "failure_kind",
        "attempts",
        "max_rounds",
        "action",
        "ok",
    )
    return [
        {**{k: fu.get(k) for k in keys}, "escalated_to": fu.get("escalated_to") or "",
         "reason": str(fu.get("reason") or "")[:300]}
        for fu in follow_ups
    ]  # fmt: skip


__all__ = ["categorize", "failure_text", "request_model_fallback", "run_failure_loop"]
