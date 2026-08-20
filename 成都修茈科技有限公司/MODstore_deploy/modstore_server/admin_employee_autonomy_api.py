# mypy: disable-error-code="arg-type, attr-defined, no-any-return, union-attr, valid-type"
"""管理员：员工自治闭环看板与协作 API。"""

from __future__ import annotations

import importlib
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from modstore_server.admin_employee_autonomy_helpers import (
    _extract_mentions_from_text as _extract_mentions_from_text,
)
from modstore_server.admin_employee_autonomy_helpers import (
    _has_valid_internal_api_key as _has_valid_internal_api_key,
)
from modstore_server.admin_employee_autonomy_helpers import _internal_api_key as _internal_api_key
from modstore_server.admin_employee_autonomy_helpers import _jloads as _jloads
from modstore_server.admin_employee_autonomy_helpers import (
    _require_admin_or_internal as _require_admin_or_internal,
)
from modstore_server.admin_employee_autonomy_helpers import (
    _workforce_assignment_snapshot as _workforce_assignment_snapshot,
)
from modstore_server.api.deps import require_admin
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
    EmployeeSuggestion,
    User,
    get_session_factory,
)
from modstore_server.operational_errors import RECOVERABLE_ERRORS

router = APIRouter(prefix="/api/admin/employee-autonomy", tags=["admin-employee-autonomy"])


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
    production_window_hours: int = Query(24 * 30, ge=24, le=24 * 90),
    _admin_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Return capability and production-duty receipts without conflating burn-in.

    Strict duty burn-in proves that an employee can execute safely.  It does not
    prove that the employee has performed production work, so production receipts
    deliberately exclude the ``[duty-burn-in:...]`` task marker.
    """

    _ = _admin_user
    from modstore_server.duty_roster import all_planned_employee_ids
    from modstore_server.employee_execution_coverage import build_execution_coverage

    planned = set(all_planned_employee_ids())
    assignment = _workforce_assignment_snapshot(planned)
    return build_execution_coverage(
        planned=planned,
        assignment=assignment,
        window_hours=window_hours,
        production_window_hours=production_window_hours,
    )


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
        except RECOVERABLE_ERRORS:
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


_human_routes = importlib.import_module("modstore_server.admin_employee_human_routes")
list_pending_human_questions = _human_routes.list_pending_human_questions
answer_human_question = _human_routes.answer_human_question
internal_answer_latest_question = _human_routes.internal_answer_latest_question
human_questions_stats = _human_routes.human_questions_stats
get_employee_scorecard_api = _human_routes.get_employee_scorecard_api
list_employee_scorecards_api = _human_routes.list_employee_scorecards_api


__all__ = ["router"]
