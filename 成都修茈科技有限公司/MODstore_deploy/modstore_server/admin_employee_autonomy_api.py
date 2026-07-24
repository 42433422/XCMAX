"""管理员：员工自治闭环看板与协作 API。"""

from __future__ import annotations

import json
import math
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request
from sqlalchemy import func

from modstore_server.api.deps import get_current_user, require_admin
from modstore_server.employee_autonomy_service import (
    aggregate_admin_suggestion_dashboard,
    approve_suggestion,
    create_collab_thread,
    dispatch_pending_brief_tasks,
    dispatch_pending_suggestions,
    list_pending_brief_tasks,
    post_collab_message,
    reject_suggestion,
    run_employee_evolution_scan,
)
from modstore_server.models import (
    EmployeeCollabMessage,
    EmployeeCollabThread,
    EmployeeExecutionMetric,
    EmployeeSuggestion,
    User,
    get_session_factory,
)

router = APIRouter(prefix="/api/admin/employee-autonomy", tags=["admin-employee-autonomy"])

_MENTION_RE = re.compile(r"@([a-zA-Z0-9][a-zA-Z0-9_-]{0,127})")
_HOLLOW_DUTY_HANDLERS = frozenset({"echo", "llm_md"})


def _jloads(text: str, default: Any) -> Any:
    raw = (text or "").strip()
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _extract_mentions_from_text(text: str) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for m in _MENTION_RE.findall(text or ""):
        s = str(m or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _internal_api_key() -> str:
    return (
        os.environ.get("XCAGI_MARKET_INTERNAL_API_KEY")
        or os.environ.get("MODSTORE_INTERNAL_API_KEY")
        or os.environ.get("XCAGI_CS_INTAKE_LINK_SECRET")
        or ""
    ).strip()


def _has_valid_internal_api_key(request: Request) -> bool:
    expected = _internal_api_key()
    got = (request.headers.get("x-internal-api-key") or "").strip()
    return bool(expected and got and secrets.compare_digest(got, expected))


def _require_admin_or_internal(
    request: Request,
    authorization: Optional[str] = Header(None),
) -> Optional[User]:
    """Read-only service bridge for FHD mobile sync; writes still require admin JWT."""

    if _has_valid_internal_api_key(request):
        return None
    return require_admin(get_current_user(authorization))


def _workforce_assignment_snapshot(planned: set[str]) -> Dict[str, Any]:
    """Derive real assignment and shell counts from reviewed duty SSOTs."""

    from modstore_server.duty_workforce_contracts import (
        load_reviewed_duty_manifest,
        workforce_contract_map,
    )
    from modstore_server.employee_runtime import parse_employee_config_v2

    contracts = workforce_contract_map()
    assigned_ids: list[str] = []
    shell_ids: list[str] = []
    for employee_id in sorted(planned):
        contract = (
            contracts.get(employee_id) if isinstance(contracts.get(employee_id), dict) else {}
        )
        trigger = contract.get("trigger") if isinstance(contract.get("trigger"), dict) else {}
        acceptance = (
            contract.get("acceptance") if isinstance(contract.get("acceptance"), list) else []
        )
        assigned = all(
            (
                str(contract.get("mission") or "").strip(),
                str(contract.get("mode") or "").strip(),
                str(contract.get("risk_level") or "").strip(),
                bool(str(trigger.get("cron") or "").strip() or trigger.get("events")),
                bool([item for item in acceptance if str(item or "").strip()]),
            )
        )
        if assigned:
            assigned_ids.append(employee_id)

        try:
            manifest = load_reviewed_duty_manifest(employee_id)
            config = parse_employee_config_v2(manifest)
            actions = config.get("actions") if isinstance(config.get("actions"), dict) else {}
            if isinstance(actions.get("actions"), dict):
                actions = actions["actions"]
            handlers = {
                str(item).strip() for item in actions.get("handlers") or [] if str(item).strip()
            }
        except Exception:  # noqa: BLE001 - missing/invalid reviewed runtime is a shell
            handlers = set()
        if not handlers or handlers.issubset(_HOLLOW_DUTY_HANDLERS):
            shell_ids.append(employee_id)

    return {
        "assigned_count": len(assigned_ids),
        "assigned_employee_ids": assigned_ids,
        "shell_count": len(shell_ids),
        "shell_employee_ids": shell_ids,
    }


@router.get("/dashboard")
def get_autonomy_dashboard(
    limit_recent: int = Query(30, ge=1, le=200),
    _admin_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    _ = _admin_user
    return aggregate_admin_suggestion_dashboard(limit_recent=limit_recent)


@router.get("/execution-coverage")
def get_execution_coverage(
    window_hours: int = Query(24, ge=1, le=24 * 30),
    _admin_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Return roster employees with a fresh successful execution receipt."""

    _ = _admin_user
    from modstore_server.duty_roster import all_planned_employee_ids

    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=window_hours)
    planned = set(all_planned_employee_ids())
    sf = get_session_factory()
    with sf() as session:
        rows = (
            session.query(
                EmployeeExecutionMetric.employee_id,
                func.max(EmployeeExecutionMetric.created_at),
            )
            .filter(
                EmployeeExecutionMetric.status.in_(["success", "completed"]),
                EmployeeExecutionMetric.created_at >= cutoff,
            )
            .group_by(EmployeeExecutionMetric.employee_id)
            .all()
        )
    receipts = [
        {"employee_id": str(employee_id), "latest_success_at": created_at.isoformat()}
        for employee_id, created_at in rows
        if str(employee_id or "") in planned and created_at is not None
    ]
    receipts.sort(key=lambda item: item["employee_id"])
    assignment = _workforce_assignment_snapshot(planned)
    planned_count = len(planned)
    assigned_required = math.ceil(planned_count * 0.95) if planned_count else 0
    proven_required = math.ceil(planned_count * 0.80) if planned_count else 0
    workforce_ready = bool(planned_count) and all(
        (
            assignment["assigned_count"] >= assigned_required,
            len(receipts) >= proven_required,
            assignment["shell_count"] == 0,
        )
    )
    from modstore_server.services.llm import resolve_platform_bench_llm

    bench_provider, bench_model = resolve_platform_bench_llm()
    return {
        "ok": True,
        "window_hours": window_hours,
        "cutoff": cutoff.isoformat(),
        "planned_count": planned_count,
        **assignment,
        "proven_count": len(receipts),
        "assignment_required_count": assigned_required,
        "proof_required_count": proven_required,
        "assignment_ratio": (
            round(assignment["assigned_count"] / planned_count, 4) if planned_count else 0.0
        ),
        "proof_ratio": (round(len(receipts) / planned_count, 4) if planned_count else 0.0),
        "workforce_ready": workforce_ready,
        "employee_ids": [item["employee_id"] for item in receipts],
        "receipts": receipts,
        # Observable routing truth without exposing credential material.
        "platform_llm": {
            "configured": bool(bench_provider and bench_model),
            "provider": bench_provider,
            "model": bench_model,
        },
    }


@router.get("/burn-in/plan")
def get_duty_workforce_burn_in_plan(
    window_hours: int = Query(24, ge=1, le=24 * 30),
    limit: int = Query(2, ge=1, le=8),
    _admin_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Dry-run the fail-closed receipt coverage plan; never invokes employees."""

    _ = _admin_user
    from modstore_server.duty_workforce_burnin import build_burn_in_plan

    return build_burn_in_plan(window_hours=window_hours, limit=limit)


@router.post("/burn-in/run")
def run_duty_workforce_burn_in(
    body: Dict[str, Any] = Body(default_factory=dict),
    _admin_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Run a bounded burn-in wave.

    The request defaults to dry-run.  Even ``dry_run=false`` remains blocked
    until the effective runtime explicitly enables
    ``MODSTORE_EMPLOYEE_BURN_IN_ENABLED=1``.
    """

    _ = _admin_user
    from modstore_server.duty_workforce_burnin import run_burn_in

    dry_run = body.get("dry_run", True) is not False
    try:
        window_hours = max(1, min(int(body.get("window_hours") or 24), 24 * 30))
        limit = max(1, min(int(body.get("limit") or 2), 8))
    except (TypeError, ValueError):
        raise HTTPException(400, "window_hours/limit 必须是整数") from None
    return run_burn_in(
        dry_run=dry_run,
        window_hours=window_hours,
        limit=limit,
    )


@router.get("/suggestions")
def list_employee_suggestions(
    status: str = Query("", description="pending|approved|rejected|dispatched|done"),
    risk_level: str = Query("", description="low|medium|high"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _admin_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    _ = _admin_user
    sf = get_session_factory()
    with sf() as session:
        q = session.query(EmployeeSuggestion).order_by(EmployeeSuggestion.id.desc())
        st = (status or "").strip()
        if st:
            q = q.filter(EmployeeSuggestion.status == st)
        rk = (risk_level or "").strip().lower()
        if rk:
            q = q.filter(EmployeeSuggestion.risk_level == rk)
        total = int(q.count() or 0)
        rows = q.offset(offset).limit(limit).all()
        items = [
            {
                "id": int(r.id),
                "source_employee_id": str(r.source_employee_id or ""),
                "target_employee_ids": _jloads(r.target_employee_ids_json or "[]", []),
                "kind": str(r.kind or ""),
                "summary": str(r.summary or ""),
                "detail": str(r.detail or ""),
                "risk_level": str(r.risk_level or ""),
                "status": str(r.status or ""),
                "thread_id": int(r.thread_id) if r.thread_id else None,
                "created_task_ids": _jloads(r.created_task_ids_json or "[]", []),
                "created_change_request_ids": _jloads(
                    r.created_change_request_ids_json or "[]", []
                ),
                "approved_by_user_id": (
                    int(r.approved_by_user_id) if r.approved_by_user_id else None
                ),
                "approved_at": r.approved_at.isoformat() if r.approved_at else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.post("/suggestions/{suggestion_id}/approve")
def approve_employee_suggestion(
    suggestion_id: int,
    body: Dict[str, Any] = Body(default_factory=dict),
    admin_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    if suggestion_id <= 0:
        raise HTTPException(400, "invalid suggestion id")
    dispatch_now = bool(body.get("dispatch_now", True))
    out = approve_suggestion(
        int(suggestion_id),
        approved_by_user_id=int(admin_user.id),
        dispatch_now=dispatch_now,
    )
    if not out.get("ok"):
        raise HTTPException(400, str(out.get("error") or "approve failed"))
    return out


@router.post("/suggestions/{suggestion_id}/reject")
def reject_employee_suggestion(
    suggestion_id: int,
    body: Dict[str, Any] = Body(default_factory=dict),
    admin_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    if suggestion_id <= 0:
        raise HTTPException(400, "invalid suggestion id")
    reason = str(body.get("reason") or body.get("rejected_reason") or "").strip()
    out = reject_suggestion(
        int(suggestion_id),
        rejected_reason=reason or "(no reason)",
        rejected_by_user_id=int(admin_user.id),
    )
    if not out.get("ok"):
        raise HTTPException(400, str(out.get("error") or "reject failed"))
    return out


@router.post("/suggestions/batch-review")
def batch_review_employee_suggestions(
    body: Dict[str, Any] = Body(default_factory=dict),
    admin_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    ids_raw = body.get("ids") if isinstance(body.get("ids"), list) else []
    action = str(body.get("action") or "").strip().lower()
    reason = str(body.get("reason") or "").strip()
    dispatch_now = bool(body.get("dispatch_now", True))
    ids: List[int] = []
    for x in ids_raw:
        try:
            n = int(x)
        except Exception:
            continue
        if n > 0:
            ids.append(n)
    if not ids:
        raise HTTPException(400, "ids 不能为空")
    if action not in ("approve", "reject"):
        raise HTTPException(400, "action 仅支持 approve/reject")

    ok = 0
    failed = 0
    errors: List[Dict[str, Any]] = []
    for sid in ids:
        if action == "approve":
            out = approve_suggestion(
                sid,
                approved_by_user_id=int(admin_user.id),
                dispatch_now=dispatch_now,
            )
        else:
            out = reject_suggestion(
                sid,
                rejected_reason=reason or "(batch reject)",
                rejected_by_user_id=int(admin_user.id),
            )
        if out.get("ok"):
            ok += 1
        else:
            failed += 1
            errors.append({"id": sid, "error": str(out.get("error") or "unknown")[:300]})
    return {
        "ok": True,
        "action": action,
        "total": len(ids),
        "success": ok,
        "failed": failed,
        "errors": errors,
    }


@router.get("/brief-tasks")
def list_brief_tasks(
    status: str = Query("", description="pending|running|done|failed|cancelled"),
    limit: int = Query(100, ge=1, le=500),
    _admin_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    _ = _admin_user
    return {"items": list_pending_brief_tasks(limit=limit, status=status)}


@router.post("/dispatch/brief-tasks")
def run_brief_task_dispatch(
    body: Dict[str, Any] = Body(default_factory=dict),
    _admin_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    _ = _admin_user
    try:
        limit = int(body.get("limit") or 20)
    except ValueError:
        limit = 20
    return dispatch_pending_brief_tasks(limit=max(1, min(limit, 100)))


@router.post("/dispatch/suggestions")
def run_suggestion_dispatch(
    body: Dict[str, Any] = Body(default_factory=dict),
    _admin_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    _ = _admin_user
    try:
        limit = int(body.get("limit") or 20)
    except ValueError:
        limit = 20
    return dispatch_pending_suggestions(limit=max(1, min(limit, 100)))


@router.post("/evolution/scan")
def trigger_evolution_scan(
    body: Dict[str, Any] = Body(default_factory=dict),
    _admin_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    _ = _admin_user
    try:
        lookback = int(body.get("lookback_hours") or 24)
    except ValueError:
        lookback = 24
    try:
        min_fail = int(body.get("min_failures") or 3)
    except ValueError:
        min_fail = 3
    try:
        limit = int(body.get("limit") or 20)
    except ValueError:
        limit = 20
    return run_employee_evolution_scan(
        lookback_hours=max(1, min(lookback, 168)),
        min_failures=max(1, min(min_fail, 50)),
        limit=max(1, min(limit, 100)),
        triggered_by="admin_api",
    )


@router.get("/collab/threads")
def list_collab_threads(
    status: str = Query("", description="open|resolved|closed"),
    limit: int = Query(50, ge=1, le=200),
    _auth_user: Optional[User] = Depends(_require_admin_or_internal),
) -> Dict[str, Any]:
    _ = _auth_user
    sf = get_session_factory()
    with sf() as session:
        q = session.query(EmployeeCollabThread).order_by(EmployeeCollabThread.updated_at.desc())
        st = (status or "").strip()
        if st:
            q = q.filter(EmployeeCollabThread.status == st)
        rows = q.limit(limit).all()
        items = [
            {
                "id": int(r.id),
                "title": str(r.title or ""),
                "participants": _jloads(r.participants_json or "[]", []),
                "status": str(r.status or ""),
                "created_by_employee_id": str(r.created_by_employee_id or ""),
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]
    return {"items": items, "count": len(items)}


@router.post("/collab/threads")
def create_collab_thread_api(
    body: Dict[str, Any] = Body(default_factory=dict),
    _admin_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    _ = _admin_user
    title = str(body.get("title") or "").strip() or "协作线程"
    participants = body.get("participants") if isinstance(body.get("participants"), list) else []
    created_by = str(body.get("created_by_employee_id") or "admin").strip() or "admin"
    out = create_collab_thread(
        title=title,
        participants=[str(x).strip() for x in participants if str(x).strip()],
        created_by_employee_id=created_by,
        context=body.get("context") if isinstance(body.get("context"), dict) else {},
    )
    if not out.get("ok"):
        raise HTTPException(400, str(out.get("error") or "create thread failed"))
    return out


@router.get("/collab/threads/{thread_id}/messages")
def list_collab_messages(
    thread_id: int,
    limit: int = Query(100, ge=1, le=500),
    _auth_user: Optional[User] = Depends(_require_admin_or_internal),
) -> Dict[str, Any]:
    _ = _auth_user
    if thread_id <= 0:
        raise HTTPException(400, "invalid thread id")
    sf = get_session_factory()
    with sf() as session:
        rows = (
            session.query(EmployeeCollabMessage)
            .filter(EmployeeCollabMessage.thread_id == int(thread_id))
            .order_by(EmployeeCollabMessage.id.asc())
            .limit(limit)
            .all()
        )
        items = [
            {
                "id": int(r.id),
                "thread_id": int(r.thread_id),
                "sender_employee_id": str(r.sender_employee_id or ""),
                "content": str(r.content or ""),
                "mentions": _jloads(r.mentions_json or "[]", []),
                "payload": _jloads(r.payload_json or "{}", {}),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    return {"items": items, "count": len(items)}


@router.post("/collab/threads/{thread_id}/messages")
def post_collab_message_api(
    thread_id: int,
    body: Dict[str, Any] = Body(default_factory=dict),
    _admin_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    _ = _admin_user
    if thread_id <= 0:
        raise HTTPException(400, "invalid thread id")
    sender = str(body.get("sender_employee_id") or "admin").strip() or "admin"
    content = str(body.get("content") or "").strip()
    if not content:
        raise HTTPException(400, "content 不能为空")
    mentions = body.get("mentions") if isinstance(body.get("mentions"), list) else []
    mention_ids = [str(x).strip() for x in mentions if str(x).strip()]
    if not mention_ids:
        mention_ids = _extract_mentions_from_text(content)
    out = post_collab_message(
        thread_id=int(thread_id),
        sender_employee_id=sender,
        content=content,
        mentions=mention_ids,
        payload=body.get("payload") if isinstance(body.get("payload"), dict) else {},
    )
    if not out.get("ok"):
        raise HTTPException(400, str(out.get("error") or "post message failed"))
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Phase-D：员工向老板的双向问答回路
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/questions")
def list_pending_human_questions(
    include_history: bool = Query(False, description="true 则包含 answered/expired 历史"),
    limit: int = Query(50, ge=1, le=200),
    _admin_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """老板查看员工问自己的问题（pending 或历史）。

    GET /api/admin/employee-autonomy/questions?include_history=false
    """
    from modstore_server.human_uncertainty_queue import list_pending_questions
    from modstore_server.retort_clarification_gate import get_clarification, list_clarifications

    items = list_pending_questions(
        user_id=_admin_user.id,
        include_expired=include_history,
        limit=limit,
    )
    # Enrich Phase-D mirrored Retort items with structured questions / countdown.
    for item in items:
        if not isinstance(item, dict):
            continue
        ctx = item.get("context") if isinstance(item.get("context"), dict) else {}
        if str(ctx.get("kind") or "") != "retort_clarification":
            continue
        sid = str(ctx.get("session_id") or "").strip()
        detail = get_clarification(sid) if sid else None
        if not detail:
            continue
        item["questions"] = detail.get("questions") or []
        item["seconds_remaining"] = detail.get("seconds_remaining")
        item["urgency"] = detail.get("urgency")
        item["blocking_question_ids"] = detail.get("blocking_question_ids") or []
        item["source"] = "retort_clarification_gate"

    # Merge open Retort clarifications that may not yet have a Phase-D mirror.
    clar = list_clarifications(include_terminal=include_history, limit=limit)
    seen_sessions = {
        str((item.get("context") or {}).get("session_id") or "")
        for item in items
        if isinstance(item, dict)
    }
    for row in clar.get("items") or []:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("session_id") or "")
        if not sid or sid in seen_sessions:
            continue
        if not include_history and row.get("status") != "open":
            continue
        questions = row.get("questions") if isinstance(row.get("questions"), list) else []
        primary = ""
        for q in questions:
            if isinstance(q, dict) and str(q.get("question") or "").strip():
                primary = str(q.get("question") or "").strip()
                break
        items.append(
            {
                "id": f"retort:{sid}",
                "user_id": _admin_user.id,
                "employee_id": "retort-clarification",
                "task": str(row.get("source") or "retort_clarification"),
                "question": primary or "Retort 需要确认战略意图",
                "questions": questions,
                "blocking_question_ids": row.get("blocking_question_ids") or [],
                "seconds_remaining": row.get("seconds_remaining"),
                "urgency": row.get("urgency") or "none",
                "context": {
                    "kind": "retort_clarification",
                    "session_id": sid,
                    "subject": row.get("subject"),
                    "change_request_id": row.get("change_request_id"),
                },
                "status": (
                    "pending" if row.get("status") == "open" else str(row.get("status") or "")
                ),
                "answer": "",
                "asked_at": row.get("created_at"),
                "answered_at": row.get("answered_at"),
                "expires_at": row.get("expires_at"),
                "source": "retort_clarification_gate",
            }
        )
        seen_sessions.add(sid)

    # Pending Retort first, then soon-to-expire.
    def _sort_key(item: Dict[str, Any]) -> tuple:
        is_retort = 0 if str(item.get("employee_id") or "") == "retort-clarification" else 1
        remaining = item.get("seconds_remaining")
        remaining_key = int(remaining) if isinstance(remaining, int) else 10**9
        return (is_retort, remaining_key, str(item.get("asked_at") or ""))

    items = sorted([item for item in items if isinstance(item, dict)], key=_sort_key)
    return {
        "items": items[:limit],
        "count": min(len(items), limit),
        "retort_open_count": int(clar.get("open_count") or 0),
        "retort_critical_count": int(clar.get("critical_count") or 0),
        "retort_healthy": bool(clar.get("healthy")),
    }


@router.post("/questions/{question_id}/answer")
def answer_human_question(
    question_id: str,
    body: Dict[str, Any] = Body(...),
    _admin_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """老板回答员工的问题。

    POST /api/admin/employee-autonomy/questions/{id}/answer
    body: {"answer": "去这么做..."}
    ``question_id`` 可为数字，或合成 id ``retort:<session_id>``。
    """
    from modstore_server.human_uncertainty_queue import answer_pending_question

    raw_answers = (body or {}).get("answers")
    answer = str((body or {}).get("answer") or "").strip()
    if not answer and not isinstance(raw_answers, (dict, list)):
        raise HTTPException(400, "answer or answers is required")

    payload_answers: Any = raw_answers if isinstance(raw_answers, (dict, list)) else answer
    raw_id = str(question_id or "").strip()
    if raw_id.startswith("retort:"):
        from modstore_server.retort_clarification_gate import answer_clarification

        session_id = raw_id.split(":", 1)[1].strip()
        out = answer_clarification(
            session_id,
            answers=payload_answers,
            answered_by=f"user:{_admin_user.id}",
        )
        if not out.get("ok"):
            raise HTTPException(409, str(out.get("error") or "answer failed"))
        return {
            "ok": True,
            "question_id": raw_id,
            "employee_id": "retort-clarification",
            "status": "answered",
            "retort_clarification": out,
        }

    try:
        numeric_id = int(raw_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "invalid question_id") from exc

    # Phase-D mirrored Retort rows may carry structured answers.
    if isinstance(raw_answers, (dict, list)):
        from modstore_server.human_uncertainty_queue import list_pending_questions
        from modstore_server.retort_clarification_gate import answer_clarification

        matched = next(
            (
                item
                for item in list_pending_questions(
                    user_id=_admin_user.id, include_expired=True, limit=200
                )
                if int(item.get("id") or 0) == numeric_id
            ),
            None,
        )
        ctx = (matched or {}).get("context") if isinstance(matched, dict) else {}
        sid = str((ctx or {}).get("session_id") or "").strip()
        if sid and str((ctx or {}).get("kind") or "") == "retort_clarification":
            bridged = answer_clarification(
                sid,
                answers=payload_answers,
                answered_by=f"user:{_admin_user.id}",
            )
            if not bridged.get("ok"):
                raise HTTPException(409, str(bridged.get("error") or "answer failed"))
            # Also close the Phase-D row with a concise summary.
            summary = answer or json.dumps(raw_answers, ensure_ascii=False)[:1000]
            out = answer_pending_question(
                question_id=numeric_id,
                answer=summary,
                answered_by_user_id=_admin_user.id,
            )
            out["retort_clarification"] = bridged
            if not out.get("ok"):
                # Session already answered; treat as success if bridge ok.
                return {
                    "ok": True,
                    "question_id": numeric_id,
                    "employee_id": "retort-clarification",
                    "status": "answered",
                    "retort_clarification": bridged,
                }
            return out

    out = answer_pending_question(
        question_id=numeric_id,
        answer=answer or json.dumps(raw_answers, ensure_ascii=False)[:1000],
        answered_by_user_id=_admin_user.id,
    )
    if not out.get("ok"):
        raise HTTPException(409, str(out.get("reason") or "answer failed"))
    return out


@router.post("/internal/answer-latest")
def internal_answer_latest_question(
    request: Request,
    body: Dict[str, Any] = Body(default_factory=dict),
) -> Dict[str, Any]:
    """内部端点：老板在员工 IM 聊天页发的消息统一入站（回答问题 / 转新指令）。

    供 FHD 在「老板于员工 IM 聊天页直接回复」时经 ``X-Internal-Api-Key`` 调用，无需 question_id。
    POST body: ``{user_id, employee_id, answer}``。

    - 员工有 pending phase-D 问题 → 视为答案解阻塞（原有行为）；
    - 否则 → 视为老板新指令：入队 boss_im 任务 + 员工即时 ACK，执行完 IM 回音
      （见 ``boss_im_inbound.handle_boss_im_message``，不再静默丢消息）。
    """
    import os

    expected = (
        os.environ.get("XCAGI_MARKET_INTERNAL_API_KEY")
        or os.environ.get("XCAGI_CS_INTAKE_LINK_SECRET")
        or ""
    ).strip()
    provided = (request.headers.get("X-Internal-Api-Key") or "").strip()
    if not expected or provided != expected:
        raise HTTPException(401, "unauthorized")
    try:
        user_id = int((body or {}).get("user_id") or 0)
    except (TypeError, ValueError):
        user_id = 0
    employee_id = str((body or {}).get("employee_id") or "").strip()
    answer = str((body or {}).get("answer") or "").strip()
    if user_id <= 0 or not employee_id or not answer:
        raise HTTPException(400, "user_id/employee_id/answer required")
    from modstore_server.boss_im_inbound import handle_boss_im_message

    return handle_boss_im_message(user_id=user_id, employee_id=employee_id, text=answer)


@router.get("/questions/stats")
def human_questions_stats(
    _admin_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """老板查看问题统计（pending/answered/expired 数量）。

    GET /api/admin/employee-autonomy/questions/stats
    """
    from sqlalchemy import func

    from modstore_server.models import PendingHumanQuestion, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        rows = (
            session.query(PendingHumanQuestion.status, func.count(PendingHumanQuestion.id))
            .filter(PendingHumanQuestion.user_id == _admin_user.id)
            .group_by(PendingHumanQuestion.status)
            .all()
        )
        counts = {status: cnt for status, cnt in rows}
    return {
        "pending": counts.get("pending", 0),
        "answered": counts.get("answered", 0),
        "expired": counts.get("expired", 0),
        "total": sum(counts.values()),
    }


# ──────────────────────────────────────────────────────────────────────────────
# 员工成绩单（10 项成熟度要求第 8 项 — 会承担结果）
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/scorecard/{employee_id}")
def get_employee_scorecard_api(
    employee_id: str,
    days: int = Query(7, ge=1, le=90, description="回看多少天"),
    human_friendly: bool = Query(False, description="true 则返回人话文本，否则返回 JSON"),
    _admin_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """单个员工的成绩单 — 任务数/成功率/失败原因/处理时长/最近任务。

    GET /api/admin/employee-autonomy/scorecard/{employee_id}?days=7&human_friendly=false
    """
    from modstore_server.employee_scorecard import (
        build_human_friendly_scorecard_text,
        get_employee_scorecard,
    )

    if human_friendly:
        return {
            "ok": True,
            "employee_id": employee_id,
            "text": build_human_friendly_scorecard_text(employee_id, days=days),
        }
    return get_employee_scorecard(employee_id, days=days)


@router.get("/scorecard")
def list_employee_scorecards_api(
    days: int = Query(7, ge=1, le=90),
    sort_by: str = Query(
        "total_tasks",
        description="total_tasks|success_rate|avg_duration_ms|failure_count|total_llm_tokens",
    ),
    top_n: int = Query(50, ge=1, le=200),
    _admin_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """全部员工成绩汇总（按 sort_by 排序）。

    GET /api/admin/employee-autonomy/scorecard?days=7&sort_by=total_tasks&top_n=50

    用于老板「一览谁在干活、谁在拖后腿」。
    """
    from modstore_server.employee_scorecard import list_all_employee_scorecards

    return list_all_employee_scorecards(days=days, sort_by=sort_by, top_n=top_n)


__all__ = ["router"]
