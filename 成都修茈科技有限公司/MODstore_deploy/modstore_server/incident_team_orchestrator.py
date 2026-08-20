# mypy: disable-error-code="arg-type, assignment, attr-defined, no-any-return, union-attr, valid-type"
"""Dynamic multi-agent incident team orchestration."""

from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Any, Dict, List, Optional

from modstore_server.employee_executor import execute_employee_task
from modstore_server.incident_team_dispatch import dispatch_incident_team as dispatch_incident_team
from modstore_server.llm_failure_classifier import (
    FAILURE_KIND_PROMPT,
    FAILURE_KIND_QUOTA,
    FAILURE_KIND_TRANSIENT,
    classify_failure_kind,
)
from modstore_server.models import IncidentEvent, User
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


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _payload(row: IncidentEvent) -> Dict[str, Any]:
    try:
        data = json.loads(row.payload_json or "{}")
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _role_timeout_seconds() -> int:
    raw = (os.environ.get(_ROLE_TIMEOUT_ENV) or "").strip()
    if not raw:
        return _ROLE_TIMEOUT_DEFAULT
    try:
        return max(15, int(raw))
    except ValueError:
        return _ROLE_TIMEOUT_DEFAULT


def _execute_employee_task_with_timeout(
    employee_id: str,
    task: str,
    runtime_input: Dict[str, Any],
    *,
    user_id: int,
    bench_llm_override: Any,
    timeout_seconds: int,
) -> Dict[str, Any]:
    """Run execute_employee_task with a hard timeout so team dispatch can finish.

    Important: do not use ``with ThreadPoolExecutor`` here — its shutdown(wait=True)
    would block on the hung worker and defeat the timeout.
    """

    pool = ThreadPoolExecutor(max_workers=1)
    fut = pool.submit(
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
        logger.warning(
            "incident_team: role timeout employee_id=%s timeout=%ss",
            employee_id,
            timeout_seconds,
        )
        return {
            "ok": False,
            "handler_failed": True,
            "status": "handler_failed",
            "execution_status": "handler_failed",
            "error": f"incident_team_role_timeout:{int(timeout_seconds)}s",
            "failure_kind": FAILURE_KIND_TRANSIENT,
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


def _candidate_ids(event_id: int) -> List[str]:
    return [
        str(row.get("employee_id") or "")
        for row in _candidate_rows(event_id)
        if isinstance(row, dict) and str(row.get("employee_id") or "").strip()
    ]


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
    summary = str(payload.get("summary") or event_type or "incident")
    base = (
        f"你是事故处理小组的 {role}。事件类型：{event_type}。问题摘要：{summary}。\n"
        "回复必须说人话：先给结论/状态，再说原因，再说下一步；不要直接倾倒 JSON、内部字段或英文模板。"
    )
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
            f"{ownership_text}"
            f"\n排查结果：{json.dumps(scout_result or {}, ensure_ascii=False)[:4000]}"
        )
    return base + (
        "你的任务是验证修复或恢复路径。用 PASS/FAIL 开头，并给出证据和剩余风险。"
        f"\n排查结果：{json.dumps(scout_result or {}, ensure_ascii=False)[:3000]}"
        f"\n修复结果：{json.dumps(fix_result or {}, ensure_ascii=False)[:3000]}"
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
    """对每个 handler_failed 的角色按 failure_kind 分流自动 follow-up。

    返回 follow_up 记录列表，写入 _team_claim.follow_ups 便于追踪与可视化。

    分流策略：
      - quota：不重试（避免 403 死亡螺旋）。标记 need_human=true，由人工或 boss_report 处理。
      - transient：调一次 execute_employee_task 自动重试（同 employee + 同 task）。
      - prompt：fallback 到 task market（dispatch_incident_via_market），让 self-evolution 重写 prompt。
    """
    follow_ups: List[Dict[str, Any]] = []
    team = team_plan.get("team") if isinstance(team_plan.get("team"), list) else []
    member_by_role = {str(m.get("role") or ""): m for m in team if isinstance(m, dict)}

    # transient 重试上限（env 可调，默认 1，避免无限重试占满调度）
    try:
        transient_retry_limit = max(0, int(os.environ.get(_TRANSIENT_RETRY_LIMIT_ENV) or "1"))
    except ValueError:
        transient_retry_limit = 1

    for row in results:
        role = str(row.get("role") or "")
        employee_id = str(row.get("employee_id") or "")
        result = row.get("result") if isinstance(row.get("result"), dict) else {}
        is_handler_failed = (
            bool(result.get("handler_failed"))
            or str(result.get("status") or "").strip().lower() == "handler_failed"
        )
        if not is_handler_failed:
            continue

        error_text = str(result.get("error") or result.get("reason") or "")
        failure_kind = classify_failure_kind(error_text)
        follow_up: Dict[str, Any] = {
            "role": role,
            "employee_id": employee_id,
            "failure_kind": failure_kind,
            "error": error_text[:500],
            "action": "",
            "ok": False,
            "retry_result": None,
        }

        if failure_kind == FAILURE_KIND_QUOTA:
            # 配额/计费类：不重试，标记需要人工处理。飞书告警由 boss_daily_im_report 消费 _team_claim.follow_ups。
            follow_up["action"] = "quota_blocked_need_human"
            follow_up["ok"] = False
            logger.warning(
                "incident_team: event_id=%s role=%s handler_failed quota_blocked error=%s",
                event_id,
                role,
                error_text[:200],
            )
        elif failure_kind == FAILURE_KIND_TRANSIENT and transient_retry_limit > 0:
            # 瞬时网络/限流抖动：自动重试 1 次（同 employee + 同 task）。
            follow_up["action"] = "transient_retry"
            try:
                retry_result = _retry_member(
                    event_id=event_id,
                    member=member_by_role.get(role, {"employee_id": employee_id, "role": role}),
                    team_plan=team_plan,
                    payload=payload,
                    event_type=event_type,
                    source=source,
                    uid=uid,
                    prev_results={
                        str(r.get("role") or ""): r for r in results if isinstance(r, dict)
                    },
                )
                follow_up["retry_result"] = {
                    k: v
                    for k, v in retry_result.items()
                    if k in {"status", "ok", "error", "handler_failed"}
                }
                retry_status = str(retry_result.get("status") or "").strip().lower()
                follow_up["ok"] = (
                    retry_status == "success"
                    and not retry_result.get("handler_failed")
                    and not retry_result.get("error")
                )
            except RECOVERABLE_ERRORS as exc:
                follow_up["retry_result"] = {"error": str(exc)[:500]}
                follow_up["ok"] = False
                logger.exception(
                    "incident_team: transient retry failed event_id=%s role=%s",
                    event_id,
                    role,
                )
        elif failure_kind == FAILURE_KIND_PROMPT:
            # prompt/逻辑类：fallback 到 task market，让 self-evolution 重写 prompt 后重新分发。
            follow_up["action"] = "fallback_task_market"
            try:
                from modstore_server.employee_task_market import (
                    dispatch_incident_via_market,
                )

                market_result = dispatch_incident_via_market(event_id)
                follow_up["retry_result"] = {
                    k: v
                    for k, v in market_result.items()
                    if k in {"ok", "claimed", "employee_id", "reason"}
                }
                follow_up["ok"] = bool(market_result.get("ok") and market_result.get("claimed"))
            except RECOVERABLE_ERRORS as exc:
                follow_up["retry_result"] = {"error": str(exc)[:500]}
                follow_up["ok"] = False
                logger.exception(
                    "incident_team: fallback task market failed event_id=%s role=%s",
                    event_id,
                    role,
                )
        else:
            follow_up["action"] = "no_action_unknown_kind"
            follow_up["ok"] = False

        follow_ups.append(follow_up)

    return follow_ups


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
) -> Dict[str, Any]:
    """对 transient 失败的员工重新调用 execute_employee_task 一次。

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

    return execute_employee_task(
        employee_id,
        task,
        {
            "allow_high_risk_real_run": role in {"fix", "verify"},
            "allow_medium_risk": True,
            "incident": payload,
            "incident_team": team_plan,
            "is_transient_retry": True,
            "model_route": route,
            "role": role,
            "source": source,
            "suppress_lifecycle_events": True,
            "unified_incident_bus": True,
        },
        user_id=uid,
        bench_llm_override=bench_override,
    )


__all__ = ["build_incident_team", "dispatch_incident_team"]
