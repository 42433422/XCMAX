# mypy: disable-error-code="arg-type, assignment, attr-defined, no-any-return, union-attr, valid-type"
"""Dynamic multi-agent incident team orchestration."""

from __future__ import annotations

import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from contextvars import copy_context
from typing import Any, Dict, List, Optional

from modstore_server.employee_executor import execute_employee_task
from modstore_server.incident_bus import _incident_payload as _payload  # noqa: F401
from modstore_server.incident_team_dispatch import dispatch_incident_team as dispatch_incident_team
from modstore_server.incident_team_handler_digest import handler_output_digest
from modstore_server.incident_team_handoff import format_role_handoff
from modstore_server.llm_failure_classifier import FAILURE_KIND_ROLE_TIMEOUT
from modstore_server.models import IncidentEvent as IncidentEvent
from modstore_server.models import User
from modstore_server.models import get_session_factory as get_session_factory
from modstore_server.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

ROLE_FALLBACKS = {
    "scout": ["change-request-auditor", "daily-orchestrator"],
    "fix": ["vibe-coding-maintainer", "daily-orchestrator"],
    "verify": ["test-qa-runner", "change-request-auditor"],
}

# 闭环开关：handler_failed 后是否自动 follow-up（按 failure_kind 分流）。
# 默认开启。设为 0 可关闭（旧行为：仅写 _team_claim 后 return）。
_HANDLER_FAILED_FOLLOWUP_ENV = "MODSTORE_INCIDENT_TEAM_HANDLER_FAILED_FOLLOWUP"
# transient 失败自动重试上限（防止限流抖动导致死亡螺旋）
_TRANSIENT_RETRY_LIMIT_ENV = "MODSTORE_INCIDENT_TEAM_TRANSIENT_RETRY_LIMIT"
# 单角色执行超时（秒）。超时记 handler_failed，避免 Para/LLM 挂死整单 dispatched_count=0。
_ROLE_TIMEOUT_ENV = "MODSTORE_INCIDENT_TEAM_ROLE_TIMEOUT_SECONDS"
_ROLE_TIMEOUT_DEFAULT = 120
_ROLE_TIMEOUT_PARA_GRACE = 120
_ROLE_TIMEOUT_ERROR = "incident_team_role_timeout:"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _role_timeout_seconds(role: str = "") -> int:
    raw = (os.environ.get(_ROLE_TIMEOUT_ENV) or "").strip()
    try:
        seconds = max(15, int(raw)) if raw else _ROLE_TIMEOUT_DEFAULT
    except ValueError:
        seconds = _ROLE_TIMEOUT_DEFAULT
    if role != "fix":
        return seconds
    # 修复岗同步等 Para 完成：外层超时不得早于 Para 自身等待窗口，否则 Codex 仍在改时
    # 就判 handler_failed，verify 报“无代码改动”，transient 重试再派第二个 fix。
    from modstore_server.para_delegate_handler import _wait_timeout_sec

    return max(seconds, int(_wait_timeout_sec({})) + _ROLE_TIMEOUT_PARA_GRACE)


def _is_role_timeout(row: Dict[str, Any]) -> bool:
    result = row.get("result") if isinstance(row.get("result"), dict) else {}
    return str(result.get("error") or "").startswith(_ROLE_TIMEOUT_ERROR)


def _execute_employee_task_with_timeout(
    employee_id: str,
    task: str,
    runtime_input: Dict[str, Any],
    *,
    user_id: int,
    bench_llm_override: Any,
    timeout_seconds: int,
) -> Dict[str, Any]:
    """Bound the waiting thread; a timeout does not cancel execution or its effects.

    Important: do not use ``with ThreadPoolExecutor`` here — its shutdown(wait=True)
    would block on the hung worker and defeat the timeout.
    """

    pool = ThreadPoolExecutor(max_workers=1)
    context = copy_context()
    fut = pool.submit(
        context.run,
        execute_employee_task,
        employee_id,
        task,
        runtime_input,
        user_id,
        bench_llm_override=bench_llm_override,
    )
    try:
        result = fut.result(timeout=max(15, int(timeout_seconds)))
        return result if isinstance(result, dict) else {"ok": False, "error": "invalid_result"}
    except FuturesTimeoutError:

        def late_receipt(done):
            try:
                result = done.result()
                if (
                    isinstance(result, dict)
                    and runtime_input.get("event_id")
                    and runtime_input.get("attempt_id")
                ):
                    from modstore_server.incident_team_completion import (
                        persist_late_role_result,
                    )

                    context.copy().run(
                        persist_late_role_result,
                        int(runtime_input["event_id"]),
                        str(runtime_input.get("role") or ""),
                        employee_id,
                        str(runtime_input["attempt_id"]),
                        result,
                    )
            except RECOVERABLE_ERRORS:
                logger.warning("incident late worker result could not be read")

        fut.add_done_callback(late_receipt)
        logger.warning("incident_team: role timed out")
        return {
            "ok": False,
            "handler_failed": True,
            "status": "handler_failed",
            "execution_status": "handler_failed",
            "error": f"{_ROLE_TIMEOUT_ERROR}{int(timeout_seconds)}s",
            "failure_kind": FAILURE_KIND_ROLE_TIMEOUT,
            "outcome": "unknown",
            "requires_reconciliation": True,
            "retryable": False,
            "attempt_id": runtime_input.get("attempt_id"),
            "event_id": runtime_input.get("event_id"),
        }
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _admin_user_id(session) -> int:
    row = (
        session.query(User).filter(User.is_admin.is_(True)).order_by(User.id.asc()).first()
    )  # noqa: E712
    if row:
        return int(row.id)
    row = session.query(User).order_by(User.id.asc()).first()
    return int(row.id) if row else 0


def _role_override(role: str) -> str:
    key = f"MODSTORE_INCIDENT_TEAM_{role.upper()}_EMPLOYEE"
    return (os.environ.get(key) or "").strip()


def _candidate_rows(event_id: int) -> List[Dict[str, Any]]:
    try:
        from modstore_server.employee_task_market import rank_market_candidates

        ranked = rank_market_candidates(event_id)
        rows = ranked.get("candidates") if isinstance(ranked.get("candidates"), list) else []
        return [row for row in rows if isinstance(row, dict)]
    except RECOVERABLE_ERRORS:
        return []


def _pick_role(role: str, candidates: List[str], used: set[str]) -> str:
    override = _role_override(role)
    if override and override not in used:
        return override
    preferred_exact = {
        "fix": (
            "code-validator",
            "vibe-coding-maintainer",
            "workflow-automator",
            "daily-orchestrator",
        ),
        "scout": (
            "workflow-automator",
            "self-checker",
            "host-checker",
            "intent-analyst",
            "quality-validator",
        ),
        "verify": (
            "sandbox-tester",
            "test-qa-runner",
            "quality-validator",
            "change-request-auditor",
        ),
    }.get(role, ())
    for eid in preferred_exact:
        if eid in candidates and eid not in used:
            return eid
    role_terms = {
        "fix": ("fix", "maintainer", "vibe", "code", "orchestrator"),
        "scout": (
            "workflow",
            "self",
            "host",
            "intent",
            "quality",
            "triage",
            "audit",
            "review",
            "security",
            "guard",
        ),
        "verify": ("qa", "test", "verify", "auditor"),
    }.get(role, ())
    for eid in candidates:
        low = eid.lower()
        if eid not in used and any(term in low for term in role_terms):
            return eid
    for eid in candidates:
        if eid and eid not in used:
            return eid
    for eid in ROLE_FALLBACKS.get(role, []):
        if eid not in used:
            return eid
    return ""


def build_incident_team(event_id: int) -> Dict[str, Any]:
    candidate_rows = _candidate_rows(event_id)
    candidates = [
        str(row.get("employee_id") or "")
        for row in candidate_rows
        if str(row.get("employee_id") or "").strip()
    ]
    code_owner = ""
    code_owner_match: Dict[str, Any] = {}
    for row in candidate_rows:
        ownership = row.get("code_ownership") if isinstance(row.get("code_ownership"), dict) else {}
        if ownership.get("match_count"):
            code_owner = str(row.get("employee_id") or "").strip()
            code_owner_match = ownership
            break
    used: set[str] = set()
    team: List[Dict[str, str]] = []
    for role in ("scout", "fix", "verify"):
        if role == "fix" and code_owner and code_owner not in used:
            eid = code_owner
        else:
            reserved = {code_owner} if code_owner and role == "scout" else set()
            eid = _pick_role(role, candidates, used | reserved)
        if eid:
            used.add(eid)
            team.append({"employee_id": eid, "role": role})
    return {
        "candidates": candidates,
        "code_owner": code_owner,
        "code_owner_match": code_owner_match,
        "event_id": int(event_id),
        "team": team,
    }


def _task_for_role(
    *,
    code_ownership: Optional[Dict[str, Any]] = None,
    event_type: str,
    payload: Dict[str, Any],
    role: str,
    scout_result: Optional[Dict[str, Any]] = None,
    fix_result: Optional[Dict[str, Any]] = None,
) -> str:
    from modstore_server.incident_model_router import route_for_incident

    budget = route_for_incident(event_type=event_type, payload=payload, role=role).get("budget", {})
    handoff_chars = int(budget.get("handoff_chars") or 4000)
    summary = str(payload.get("summary") or event_type or "incident")
    base = (
        f"你是事故处理小组的 {role}。事件类型：{event_type}。问题摘要：{summary}。\n"
        "回复必须说人话：先给结论/状态，再说原因，再说下一步；不要直接倾倒 JSON、内部字段或英文模板。"
    )
    resolution = payload.get("resolution")
    if isinstance(resolution, dict) and resolution.get("route") in {
        "shared_core",
        "private_mod",
    }:
        base += (
            f"\n原工单 {payload.get('ticket_no')}，账号 {payload.get('user_id')}，"
            f"来源 {resolution.get('source_ref')}，交付路线 {resolution['route']}。"
            "所有修复、验证和交付证据必须保留原工单关联。"
        )
        if resolution["route"] == "private_mod":
            base += (
                f"目标私有模块 {payload.get('target_mod_id') or resolution.get('target_mod_id') or '待确认'}。"
                "客户需求落入该模块；平台能力不足时先提交共享主线能力前置任务，再交付私有模块。"
                "禁止创建客户专用宿主分支或把客户业务数据并入共享代码。"
            )
        else:
            base += "共享修复须进入主线并正式发布；仍须等待此账号客户端运行该修复版本的回执。fix 岗必须使用现有 EmployeeChangeRequest 工具提交代码，在真实执行结果保留 change_request_id；验证岗核对该变更的实际测试结果。没有真实 CR、合并与 CI 证据不得声明修复完成。"
    ownership_text = ""
    if isinstance(code_ownership, dict) and code_ownership:
        files = [
            str(item).strip()
            for item in (code_ownership.get("matched_files") or [])
            if str(item or "").strip()
        ][:8]
        globs = [
            str(item).strip()
            for item in (code_ownership.get("matched_globs") or [])
            if str(item or "").strip()
        ][:6]
        bits = ["\n你是本事故命中的代码负责人，必须围绕归属代码给可执行处理。"]
        if files:
            bits.append("命中文件：" + "、".join(files))
        if globs:
            bits.append("归属规则：" + "、".join(globs))
        ownership_text = "\n".join(bits)
    if role == "scout":
        return base + "你的任务是判断最可能的原因、影响范围、严重程度和安全的下一步。"
    if role == "fix":
        return base + (
            "你的任务是执行或委派最小安全修复。可参考前面排查结果，但输出时要翻译成人话。"
            "改完先 commit，push 或开 PR 前必须在仓库 FHD/ 下运行 "
            "python scripts/dev/push_preflight.py --fix，按提示补 CHANGELOG、提交重生成的能力中心页面、"
            "显式写原因更新净删除基线，直到全部通过再 push。"
            f"{ownership_text}"
            f"\n排查交接（摘要仅供上下文，完成结论须核对原任务凭证）：{format_role_handoff(scout_result, 'scout', max_chars=handoff_chars)}"
        )
    return base + (
        "你的任务是验证修复或恢复路径。用 PASS/FAIL 开头，并给出证据和剩余风险。"
        f"\n排查交接：{format_role_handoff(scout_result, 'scout', max_chars=min(2400, handoff_chars))}"
        f"\n修复交接（按引用核对真实凭证）：{format_role_handoff(fix_result, 'fix', max_chars=handoff_chars)}"
    )


def _follow_up_handler_failures(
    *,
    event_id: int,
    results: List[Dict[str, Any]],
    team_plan: Dict[str, Any],
    payload: Dict[str, Any],
    event_type: str,
    source: str,
    uid: int,
) -> List[Dict[str, Any]]:
    """handler_failed 失败闭环：分类 → 降级/回喂再修/退避重试 → 到上限升级终极员工。

    见 ``incident_team_failure_loop``；返回记录写入 _team_claim.follow_ups 并回写工单。
    """
    from modstore_server.incident_team_failure_loop import run_failure_loop

    raw_limit = os.environ.get(_TRANSIENT_RETRY_LIMIT_ENV)
    try:
        transient_limit = None if raw_limit in (None, "") else max(0, int(raw_limit))
    except ValueError:
        transient_limit = None
    return run_failure_loop(
        retry_member=lambda **kw: _retry_member(**kw),
        event_id=event_id,
        results=results,
        team_plan=team_plan,
        payload=payload,
        event_type=event_type,
        source=source,
        uid=uid,
        transient_limit=transient_limit,
    )


def _retry_member(
    *,
    event_id: int,
    member: Dict[str, Any],
    team_plan: Dict[str, Any],
    payload: Dict[str, Any],
    event_type: str,
    source: str,
    uid: int,
    prev_results: Dict[str, Dict[str, Any]],
    feedback: str = "",
) -> Dict[str, Any]:
    """对失败的员工重新调用 execute_employee_task 一次（code 类带上次失败日志回喂）。

    复用 _task_for_role 构造 prompt（带 scout/fix_result 上下文），env/route 与首次一致。
    """
    role = str(member.get("role") or "")
    employee_id = str(member.get("employee_id") or "")
    if not employee_id:
        return {"status": "failed", "error": "no_employee_id"}

    scout_result = prev_results.get("scout")
    fix_result = prev_results.get("fix")
    code_ownership = (
        team_plan.get("code_owner_match")
        if role == "fix" and isinstance(team_plan.get("code_owner_match"), dict)
        else None
    )
    task = _task_for_role(
        code_ownership=code_ownership,
        event_type=event_type,
        fix_result=fix_result,
        payload=payload,
        role=role,
        scout_result=scout_result,
    )
    if feedback:
        task += f"\n上一轮失败日志（请据此修正后再提交）：{feedback[:2000]}"

    try:
        from modstore_server.incident_model_router import (
            bench_override_for_route,
            route_for_incident,
        )

        route = route_for_incident(event_type=event_type, payload=payload, role=role)
        bench_override = bench_override_for_route(route)
    except RECOVERABLE_ERRORS:
        route = {"provider": "auto", "model": "auto", "reason": "router_error"}
        bench_override = None

    from modstore_server.customer_issue_delivery_contract import (
        execution_pending,
        execution_succeeded,
    )
    from modstore_server.incident_team_completion import persist_role_attempt
    from modstore_server.incident_team_dispatch import member_runtime_input

    attempt_id = uuid.uuid4().hex
    runtime_input = member_runtime_input(
        employee_id=employee_id,
        role=role,
        event_id=event_id,
        team_plan=team_plan,
        payload=payload,
        event_type=event_type,
        source=source,
        route=route,
        attempt_id=attempt_id,
        fix_result=fix_result,
    )
    runtime_input["is_transient_retry"] = True
    row = {
        "role": role,
        "employee_id": employee_id,
        "attempt_id": attempt_id,
        "event_id": event_id,
        "tenant_id": runtime_input.get("tenant_id"),
        "status": "dispatching",
        "ok": False,
        "outcome": "unknown",
        "verified_fix_attempt_id": runtime_input["revision"] if role == "verify" else "",
    }
    persist_role_attempt(event_id, row)
    result = _execute_employee_task_with_timeout(
        employee_id,
        task,
        runtime_input,
        user_id=0,
        bench_llm_override=bench_override,
        timeout_seconds=_role_timeout_seconds(role),
    )
    result = {
        **result,
        "attempt_id": attempt_id,
        "verified_fix_attempt_id": row["verified_fix_attempt_id"],
    }
    row.update(
        handler_outputs=handler_output_digest(result),
        ok=execution_succeeded(result),
        status=(
            "pending"
            if execution_pending(result)
            else "completed" if execution_succeeded(result) else "failed"
        ),
    )
    row.pop("outcome", None)
    persist_role_attempt(event_id, row, expected_attempt=attempt_id)
    return result


__all__ = ["build_incident_team", "dispatch_incident_team"]
