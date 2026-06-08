"""员工自治闭环服务层。

提供：
- 建议单（EmployeeSuggestion）创建 / 审批 / 分发
- 协作线程（thread + mention）最小实现
- 每日简报待办任务入队与调度
- 文档一致性报告触发自动修复建议
- 员工执行指标驱动的 prompt 自进化建议
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import func

from modstore_server.models import (
    EmployeeChangeRequest,
    EmployeeCollabMessage,
    EmployeeCollabThread,
    EmployeeEvolutionRecord,
    EmployeeExecutionMetric,
    EmployeeSuggestion,
    PendingBriefTask,
    User,
    get_session_factory,
)

logger = logging.getLogger(__name__)


def _jloads(text: str, default: Any) -> Any:
    raw = (text or "").strip()
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _jdumps(obj: Any, *, max_chars: int = 0) -> str:
    text = json.dumps(obj, ensure_ascii=False)
    if max_chars > 0 and len(text) > max_chars:
        return text[:max_chars] + "…"
    return text


def _dedupe_strs(items: Iterable[Any]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for it in items:
        s = str(it or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _resolve_actor_user_id(session, fallback_user_id: int = 0) -> int:
    uid = int(fallback_user_id or 0)
    if uid > 0:
        return uid
    u = (
        session.query(User).filter(User.is_admin == True).order_by(User.id.asc()).first()
    )  # noqa: E712
    if u:
        return int(u.id)
    u2 = session.query(User).order_by(User.id.asc()).first()
    return int(u2.id) if u2 else 0


def _publish_event(
    event_type: str, payload: Dict[str, Any], *, source: str, fingerprint: str | None = None
) -> None:
    try:
        from modstore_server.incident_bus import publish

        publish(event_type, payload, source=source, fingerprint=fingerprint)
    except Exception:
        logger.exception("publish event failed event_type=%s source=%s", event_type, source)


def _suggestion_auto_dispatch_enabled() -> bool:
    return (os.environ.get("MODSTORE_SUGGESTION_AUTO_DISPATCH", "1") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _brief_auto_dispatch_enabled() -> bool:
    return (
        os.environ.get("MODSTORE_DAILY_BRIEF_TODO_DISPATCH_ENABLED", "1") or ""
    ).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _doc_autofix_enabled() -> bool:
    return (
        os.environ.get("MODSTORE_DOC_CONSISTENCY_AUTOFIX_ENABLED", "1") or ""
    ).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _evolution_enabled() -> bool:
    return (os.environ.get("MODSTORE_EMPLOYEE_EVOLUTION_ENABLED", "1") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _infer_suggestion_targets(
    source_employee_id: str,
    payload: Dict[str, Any],
    explicit_targets: Sequence[str] | None = None,
) -> List[str]:
    direct = _dedupe_strs(explicit_targets or payload.get("target_employee_ids") or [])
    if direct:
        return direct
    target_one = str(payload.get("target_employee_id") or "").strip()
    if target_one:
        return [target_one]

    kind = str(payload.get("kind") or "").strip().lower()
    if kind in {"doc_consistency_fix", "doc_fix", "doc_change"}:
        return ["doc-knowledge-curator"]
    if kind in {"collab_mention"}:
        mentions = _dedupe_strs(payload.get("mentioned_employee_ids") or [])
        if mentions:
            return mentions
    if kind in {"scope_violation"}:
        return ["daily-orchestrator"]

    source = str(source_employee_id or "").strip()
    if source and source != "daily-orchestrator":
        return [source]
    return ["daily-orchestrator"]


def create_collab_thread(
    *,
    title: str,
    participants: Sequence[str],
    created_by_employee_id: str,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    pids = _dedupe_strs(participants)
    if created_by_employee_id and created_by_employee_id not in pids:
        pids.insert(0, created_by_employee_id)
    sf = get_session_factory()
    with sf() as session:
        row = EmployeeCollabThread(
            title=(title or "协作线程")[:256],
            participants_json=_jdumps(pids),
            context_json=_jdumps(context or {}),
            status="open",
            created_by_employee_id=(created_by_employee_id or "")[:128],
        )
        session.add(row)
        session.commit()
        tid = int(row.id)
    _publish_event(
        "employee.collab.thread_created",
        {"thread_id": tid, "participants": pids, "title": (title or "")[:256]},
        source=created_by_employee_id or "system",
    )
    return {"ok": True, "thread_id": tid, "participants": pids}


def post_collab_message(
    *,
    thread_id: int,
    sender_employee_id: str,
    content: str,
    mentions: Optional[Sequence[str]] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if int(thread_id or 0) <= 0:
        return {"ok": False, "error": "invalid thread_id"}
    text = str(content or "").strip()
    if not text:
        return {"ok": False, "error": "content empty"}
    mention_ids = _dedupe_strs(mentions or [])

    sf = get_session_factory()
    with sf() as session:
        thread = session.get(EmployeeCollabThread, int(thread_id))
        if not thread:
            return {"ok": False, "error": "thread not found"}
        row = EmployeeCollabMessage(
            thread_id=int(thread_id),
            sender_employee_id=(sender_employee_id or "")[:128],
            content=text[:20_000],
            mentions_json=_jdumps(mention_ids),
            payload_json=_jdumps(payload or {}, max_chars=30_000),
        )
        session.add(row)
        thread.updated_at = datetime.now(timezone.utc)
        session.commit()
        mid = int(row.id)

    _publish_event(
        "employee.collab.message_created",
        {
            "thread_id": int(thread_id),
            "message_id": mid,
            "sender_employee_id": sender_employee_id,
            "mentions": mention_ids,
            "content_excerpt": text[:500],
        },
        source=sender_employee_id or "system",
    )

    mention_suggestion_id: Optional[int] = None
    if mention_ids:
        # mention -> 自动生成协作建议单，后续由 suggestion dispatcher 处理
        out = create_employee_suggestion(
            source_employee_id=sender_employee_id or "system",
            summary=f"协作提及：{sender_employee_id} @ {'/'.join(mention_ids)}",
            detail=text[:4000],
            payload={
                "kind": "collab_mention",
                "thread_id": int(thread_id),
                "message_id": mid,
                "mentioned_employee_ids": mention_ids,
            },
            target_employee_ids=mention_ids,
            kind="collab_mention",
            risk_level="low",
            thread_id=int(thread_id),
            emit_event=True,
            auto_dispatch=True,
        )
        if out.get("ok"):
            mention_suggestion_id = int(out.get("suggestion_id") or 0)

    return {
        "ok": True,
        "thread_id": int(thread_id),
        "message_id": mid,
        "mentions": mention_ids,
        "suggestion_id": mention_suggestion_id,
    }


def create_employee_suggestion(
    *,
    source_employee_id: str,
    summary: str,
    detail: str = "",
    payload: Optional[Dict[str, Any]] = None,
    target_employee_ids: Optional[Sequence[str]] = None,
    kind: str = "general",
    risk_level: str = "medium",
    thread_id: Optional[int] = None,
    emit_event: bool = True,
    auto_dispatch: bool = False,
) -> Dict[str, Any]:
    src = str(source_employee_id or "").strip() or "system"
    pl = dict(payload or {})
    targets = _infer_suggestion_targets(src, pl, explicit_targets=target_employee_ids)
    targets = _dedupe_strs(targets)
    risk = str(risk_level or "medium").strip().lower()
    if risk not in ("low", "medium", "high"):
        risk = "medium"
    knd = str(kind or pl.get("kind") or "general").strip().lower()[:64] or "general"

    sf = get_session_factory()
    with sf() as session:
        row = EmployeeSuggestion(
            source_employee_id=src[:128],
            target_employee_ids_json=_jdumps(targets),
            kind=knd,
            summary=(summary or "")[:8000],
            detail=(detail or "")[:30_000],
            payload_json=_jdumps(pl, max_chars=100_000),
            risk_level=risk,
            status="pending",
            thread_id=int(thread_id) if thread_id else None,
        )
        session.add(row)
        session.commit()
        sid = int(row.id)

    payload_evt = {
        "suggestion_id": sid,
        "source_employee_id": src,
        "target_employee_ids": targets,
        "kind": knd,
        "summary": (summary or "")[:500],
        "risk_level": risk,
        "thread_id": int(thread_id) if thread_id else None,
        **{k: v for k, v in pl.items() if k not in ("summary", "target_employee_ids")},
    }
    if emit_event:
        _publish_event("employee.suggestion.created", payload_evt, source=src)

    if auto_dispatch and _suggestion_auto_dispatch_enabled():
        dispatch_suggestion(sid, approved_by_user_id=0, force_approve_if_needed=True)

    return {"ok": True, "suggestion_id": sid, "target_employee_ids": targets}


def ingest_suggestion_event_payload(
    *,
    source_employee_id: str,
    payload: Dict[str, Any],
    auto_dispatch: bool = True,
) -> Dict[str, Any]:
    """把已有 ``employee.suggestion.created`` 负载落库为 EmployeeSuggestion。"""
    pl = dict(payload or {})
    sid_raw = pl.get("suggestion_id")
    try:
        sid_existing = int(sid_raw) if sid_raw is not None else 0
    except Exception:
        sid_existing = 0
    if sid_existing > 0:
        sf = get_session_factory()
        with sf() as session:
            row = session.get(EmployeeSuggestion, sid_existing)
            if row:
                if auto_dispatch and _suggestion_auto_dispatch_enabled():
                    dispatch_suggestion(
                        sid_existing, approved_by_user_id=0, force_approve_if_needed=False
                    )
                return {"ok": True, "suggestion_id": sid_existing, "existing": True}
    summary = str(pl.get("summary") or pl.get("detail") or pl.get("kind") or "员工建议").strip()
    detail = str(pl.get("detail") or "").strip()
    kind = str(pl.get("kind") or "general").strip() or "general"
    risk = str(pl.get("risk_level") or "medium").strip() or "medium"
    thread_id_raw = pl.get("thread_id")
    try:
        tid = int(thread_id_raw) if thread_id_raw is not None else None
    except Exception:
        tid = None
    out = create_employee_suggestion(
        source_employee_id=source_employee_id,
        summary=summary,
        detail=detail,
        payload=pl,
        target_employee_ids=(
            pl.get("target_employee_ids")
            if isinstance(pl.get("target_employee_ids"), list)
            else None
        ),
        kind=kind,
        risk_level=risk,
        thread_id=tid,
        emit_event=False,  # 事件本身已存在，避免重复广播
        auto_dispatch=auto_dispatch,
    )
    sid = int(out.get("suggestion_id") or 0)
    return {"ok": True, "suggestion_id": sid}


def approve_suggestion(
    suggestion_id: int,
    *,
    approved_by_user_id: int,
    dispatch_now: bool = True,
) -> Dict[str, Any]:
    sid = int(suggestion_id or 0)
    if sid <= 0:
        return {"ok": False, "error": "invalid suggestion id"}
    sf = get_session_factory()
    with sf() as session:
        row = session.get(EmployeeSuggestion, sid)
        if not row:
            return {"ok": False, "error": "not found"}
        if (row.status or "") == "rejected":
            return {"ok": False, "error": "already rejected"}
        row.status = "approved"
        row.approved_by_user_id = int(approved_by_user_id or 0) or None
        row.approved_at = datetime.now(timezone.utc)
        session.commit()
    _publish_event(
        "employee.suggestion.approved",
        {"suggestion_id": sid, "approved_by_user_id": int(approved_by_user_id or 0)},
        source="admin",
    )
    if dispatch_now:
        return dispatch_suggestion(sid, approved_by_user_id=approved_by_user_id)
    return {"ok": True, "suggestion_id": sid}


def reject_suggestion(
    suggestion_id: int,
    *,
    rejected_reason: str,
    rejected_by_user_id: int,
) -> Dict[str, Any]:
    sid = int(suggestion_id or 0)
    if sid <= 0:
        return {"ok": False, "error": "invalid suggestion id"}
    sf = get_session_factory()
    with sf() as session:
        row = session.get(EmployeeSuggestion, sid)
        if not row:
            return {"ok": False, "error": "not found"}
        row.status = "rejected"
        row.rejected_reason = (rejected_reason or "")[:4000]
        row.approved_by_user_id = int(rejected_by_user_id or 0) or None
        row.approved_at = datetime.now(timezone.utc)
        session.commit()
    _publish_event(
        "employee.suggestion.rejected",
        {"suggestion_id": sid, "reason": (rejected_reason or "")[:500]},
        source="admin",
    )
    return {"ok": True, "suggestion_id": sid}


def _build_subtask_text(summary: str, detail: str, payload: Dict[str, Any]) -> str:
    lines = [str(summary or "").strip()]
    if detail:
        lines.append(f"详情：{detail.strip()[:2000]}")
    kind = str(payload.get("kind") or "").strip()
    if kind:
        lines.append(f"建议类型：{kind}")
    if payload:
        # 只携带小型结构，避免 task 文本过大
        tiny = {
            k: payload.get(k)
            for k in ("path", "thread_id", "message_id", "employee_id", "issue_count")
        }
        tiny = {k: v for k, v in tiny.items() if v is not None and str(v) != ""}
        if tiny:
            lines.append(f"上下文：{_jdumps(tiny, max_chars=1200)}")
    return "\n".join(x for x in lines if x).strip()[:4000]


def dispatch_suggestion(
    suggestion_id: int,
    *,
    approved_by_user_id: int = 0,
    force_approve_if_needed: bool = False,
) -> Dict[str, Any]:
    sid = int(suggestion_id or 0)
    if sid <= 0:
        return {"ok": False, "error": "invalid suggestion id"}

    sf = get_session_factory()
    with sf() as session:
        row = session.get(EmployeeSuggestion, sid)
        if not row:
            return {"ok": False, "error": "not found"}

        status = str(row.status or "")
        if status == "rejected":
            return {"ok": False, "error": "suggestion rejected"}
        if status == "done":
            return {"ok": True, "suggestion_id": sid, "status": "done"}

        if status == "pending":
            if force_approve_if_needed:
                row.status = "approved"
                row.approved_by_user_id = int(approved_by_user_id or 0) or None
                row.approved_at = datetime.now(timezone.utc)
                session.commit()
            elif str(row.risk_level or "medium") != "low":
                return {
                    "ok": False,
                    "error": "pending medium/high risk suggestion requires approval",
                }

        payload = _jloads(row.payload_json or "{}", {})
        if not isinstance(payload, dict):
            payload = {}
        targets = _dedupe_strs(_jloads(row.target_employee_ids_json or "[]", []))
        if not targets:
            targets = _infer_suggestion_targets(str(row.source_employee_id or ""), payload)

        actor_uid = _resolve_actor_user_id(session, fallback_user_id=int(approved_by_user_id or 0))
        summary = str(row.summary or "")
        detail = str(row.detail or "")

    # 数据库会话外执行任务，避免长事务
    from modstore_server.employee_orchestrator import dispatch_subtasks
    from modstore_server.task_router import SubTask

    task_brief = _build_subtask_text(summary, detail, payload)
    subtasks = [
        SubTask(
            employee_id=tid,
            task_brief=task_brief,
            input_data={
                "source_suggestion_id": sid,
                "source_employee_id": str(payload.get("source_employee_id") or ""),
                "suggestion_payload": payload,
            },
            depends_on=[],
            priority=3,
        )
        for tid in targets
    ]
    result: Dict[str, Any]
    try:
        result = dispatch_subtasks(
            subtasks,
            created_by_user_id=actor_uid,
            max_concurrency=min(max(1, len(subtasks)), 4),
            allow_high_risk_real_run=False,
        )
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}

    with sf() as session:
        row = session.get(EmployeeSuggestion, sid)
        if not row:
            return {"ok": False, "error": "suggestion disappeared"}
        row.created_task_ids_json = _jdumps(targets)
        ok = bool(result.get("ok"))
        row.status = "done" if ok else "dispatched"
        session.commit()

    _publish_event(
        "employee.suggestion.dispatched",
        {
            "suggestion_id": sid,
            "target_employee_ids": targets,
            "ok": bool(result.get("ok")),
            "error": str(result.get("error") or "")[:500],
        },
        source="suggestion_dispatcher",
    )
    return {"ok": True, "suggestion_id": sid, "dispatch_result": result}


def dispatch_pending_suggestions(limit: int = 20) -> Dict[str, Any]:
    lim = max(1, min(int(limit or 20), 100))
    sf = get_session_factory()
    with sf() as session:
        rows = (
            session.query(EmployeeSuggestion)
            .filter(
                (EmployeeSuggestion.status == "approved")
                | (
                    (EmployeeSuggestion.status == "pending")
                    & (EmployeeSuggestion.risk_level == "low")
                )
            )
            .order_by(EmployeeSuggestion.id.asc())
            .limit(lim)
            .all()
        )
        ids = [(int(r.id), str(r.status or ""), str(r.risk_level or "")) for r in rows]

    processed = 0
    ok_count = 0
    skipped = 0
    errors: List[str] = []
    for sid, status, risk in ids:
        force = status == "pending" and risk == "low"
        out = dispatch_suggestion(
            sid,
            approved_by_user_id=0,
            force_approve_if_needed=force,
        )
        processed += 1
        if out.get("ok"):
            ok_count += 1
        else:
            skipped += 1
            errors.append(str(out.get("error") or "unknown")[:200])
    return {
        "ok": True,
        "processed": processed,
        "ok_count": ok_count,
        "skipped": skipped,
        "errors": errors[:20],
    }


_TODO_BULLET_RE = re.compile(r"^\s*(?:[-*•]|(?:\d+[\.\)\、]))\s*(.+?)\s*$")


def _parse_todo_lines(todo_markdown: str) -> List[str]:
    out: List[str] = []
    for raw in (todo_markdown or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _TODO_BULLET_RE.match(line)
        if m:
            item = (m.group(1) or "").strip()
        else:
            item = line
        if not item:
            continue
        # 过滤“依据：”这类辅助行
        if item.startswith("**依据**") or item.startswith("依据："):
            continue
        out.append(item[:400])
    return _dedupe_strs(out)


def enqueue_daily_brief_todos(
    *,
    owner_employee_id: str,
    todo_markdown: str,
    source_ref: str,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    owner = str(owner_employee_id or "").strip()
    if not owner:
        return {"ok": False, "error": "owner_employee_id empty"}
    tasks = _parse_todo_lines(todo_markdown)
    if not tasks:
        return {"ok": True, "created": 0, "skipped": 0}

    created = 0
    skipped = 0
    source_key = str(source_ref or "").strip() or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sf = get_session_factory()
    with sf() as session:
        for item in tasks:
            fp = hashlib.sha256(
                f"daily_brief|{owner}|{source_key}|{item}".encode("utf-8")
            ).hexdigest()[:64]
            exists = (
                session.query(PendingBriefTask).filter(PendingBriefTask.fingerprint == fp).first()
            )
            if exists:
                skipped += 1
                continue
            row = PendingBriefTask(
                owner_employee_id=owner[:128],
                source_kind="daily_brief",
                source_ref=(source_ref or "")[:128],
                task_brief=item,
                payload_json=_jdumps(payload or {}, max_chars=20_000),
                fingerprint=fp,
                status="pending",
            )
            session.add(row)
            created += 1
        session.commit()

    if created > 0:
        _publish_event(
            "employee.brief_todo.created",
            {
                "owner_employee_id": owner,
                "count": created,
                "source_ref": (source_ref or "")[:128],
            },
            source="daily_employee_briefs",
        )
    return {"ok": True, "created": created, "skipped": skipped}


def list_pending_brief_tasks(limit: int = 100, *, status: str = "") -> List[Dict[str, Any]]:
    lim = max(1, min(int(limit or 100), 500))
    sf = get_session_factory()
    with sf() as session:
        q = session.query(PendingBriefTask).order_by(PendingBriefTask.id.desc())
        st = str(status or "").strip()
        if st:
            q = q.filter(PendingBriefTask.status == st)
        rows = q.limit(lim).all()
        return [
            {
                "id": int(r.id),
                "owner_employee_id": str(r.owner_employee_id or ""),
                "source_kind": str(r.source_kind or ""),
                "source_ref": str(r.source_ref or ""),
                "task_brief": str(r.task_brief or ""),
                "status": str(r.status or ""),
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "dispatched_at": r.dispatched_at.isoformat() if r.dispatched_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "error": str(r.error or ""),
            }
            for r in rows
        ]


def dispatch_pending_brief_tasks(limit: int = 20) -> Dict[str, Any]:
    lim = max(1, min(int(limit or 20), 100))
    sf = get_session_factory()
    with sf() as session:
        actor_uid = _resolve_actor_user_id(session, fallback_user_id=0)
        rows = (
            session.query(PendingBriefTask)
            .filter(PendingBriefTask.status == "pending")
            .order_by(PendingBriefTask.id.asc())
            .limit(lim)
            .all()
        )
        task_ids = [int(r.id) for r in rows]
        for r in rows:
            r.status = "running"
            r.dispatched_at = datetime.now(timezone.utc)
        session.commit()

    from modstore_server.task_router import route_and_dispatch

    processed = 0
    done = 0
    failed = 0
    for tid in task_ids:
        processed += 1
        sf2 = get_session_factory()
        with sf2() as session:
            row = session.get(PendingBriefTask, tid)
            if not row:
                continue
            task_brief = str(row.task_brief or "").strip()
            if not task_brief:
                row.status = "cancelled"
                row.error = "task_brief empty"
                row.completed_at = datetime.now(timezone.utc)
                session.commit()
                failed += 1
                continue
        try:
            out = route_and_dispatch(
                task_brief,
                created_by_user_id=actor_uid,
                llm_provider="auto",
                llm_model="auto",
                max_concurrency=2,
                allow_high_risk_real_run=False,
            )
            ok = bool(out.get("ok"))
            with sf2() as session:
                row2 = session.get(PendingBriefTask, tid)
                if row2:
                    row2.status = "done" if ok else "failed"
                    row2.dispatched_result_json = _jdumps(out, max_chars=120_000)
                    row2.error = str(out.get("error") or "")[:2000]
                    row2.completed_at = datetime.now(timezone.utc)
                    session.commit()
            if ok:
                done += 1
            else:
                failed += 1
        except Exception as exc:
            with sf2() as session:
                row2 = session.get(PendingBriefTask, tid)
                if row2:
                    row2.status = "failed"
                    row2.error = str(exc)[:2000]
                    row2.completed_at = datetime.now(timezone.utc)
                    session.commit()
            failed += 1
    if processed > 0:
        _publish_event(
            "employee.brief_todo.dispatched",
            {"processed": processed, "done": done, "failed": failed},
            source="brief_dispatcher",
        )
    return {"ok": True, "processed": processed, "done": done, "failed": failed}


def trigger_doc_autofix_from_report(
    report: Dict[str, Any],
    *,
    source: str = "consistency_checker",
    source_ref: str = "",
) -> Dict[str, Any]:
    if not _doc_autofix_enabled():
        return {"ok": True, "enabled": False, "created_suggestions": 0, "created_tasks": 0}
    issues = report.get("issues") if isinstance(report.get("issues"), list) else []
    if not issues:
        return {"ok": True, "enabled": True, "created_suggestions": 0, "created_tasks": 0}

    by_employee: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for it in issues:
        if not isinstance(it, dict):
            continue
        emp = str(it.get("employee") or "").strip() or "unknown"
        by_employee[emp].append(it)

    created_suggestions = 0
    created_tasks = 0
    for emp, emp_issues in by_employee.items():
        desc_lines = []
        for it in emp_issues[:20]:
            sev = str(it.get("severity") or "warning")
            typ = str(it.get("type") or "issue")
            d = str(it.get("description") or "")
            desc_lines.append(f"- [{sev}] {typ}: {d}")
        detail = "\n".join(desc_lines)[:12_000]
        summary = f"文档一致性修复：{emp} ({len(emp_issues)} 项)"
        out = create_employee_suggestion(
            source_employee_id=source,
            summary=summary,
            detail=detail,
            payload={
                "kind": "doc_consistency_fix",
                "employee": emp,
                "issue_count": len(emp_issues),
                "issues": emp_issues[:50],
                "source_ref": source_ref,
            },
            target_employee_ids=["doc-knowledge-curator"],
            kind="doc_consistency_fix",
            risk_level="low",
            emit_event=True,
            auto_dispatch=_suggestion_auto_dispatch_enabled(),
        )
        if out.get("ok"):
            created_suggestions += 1

        t = enqueue_daily_brief_todos(
            owner_employee_id="doc-knowledge-curator",
            todo_markdown=f"1. 修复 {emp} 文档一致性问题（{len(emp_issues)} 项）",
            source_ref=source_ref or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            payload={"kind": "doc_consistency_fix", "employee": emp},
        )
        created_tasks += int(t.get("created") or 0)

    if created_tasks > 0 and _brief_auto_dispatch_enabled():
        dispatch_pending_brief_tasks(limit=max(5, created_tasks))
    return {
        "ok": True,
        "enabled": True,
        "created_suggestions": created_suggestions,
        "created_tasks": created_tasks,
    }


class _PlatformBenchLlmClient:
    async def chat(self, messages: List[Dict[str, str]], *, max_tokens: int = 1024) -> str:
        from modstore_server.services.llm import (
            chat_dispatch_via_platform_only,
            resolve_platform_bench_llm,
        )

        provider, model = resolve_platform_bench_llm()
        if not provider or not model:
            raise RuntimeError("platform bench llm not configured")
        out = await chat_dispatch_via_platform_only(
            provider, model, messages, max_tokens=max_tokens
        )
        if not out.get("ok"):
            raise RuntimeError(str(out.get("error") or "llm call failed"))
        return str(out.get("content") or "")


def run_employee_evolution_scan(
    *,
    lookback_hours: int = 24,
    min_failures: int = 3,
    limit: int = 20,
    triggered_by: str = "scheduler",
) -> Dict[str, Any]:
    if not _evolution_enabled():
        return {"ok": True, "enabled": False, "processed": 0, "created": 0}
    lookback_hours = max(1, min(int(lookback_hours or 24), 168))
    min_failures = max(1, min(int(min_failures or 3), 50))
    lim = max(1, min(int(limit or 20), 100))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

    sf = get_session_factory()
    with sf() as session:
        # 仅关心最近窗口中失败较多的员工
        rows = (
            session.query(
                EmployeeExecutionMetric.employee_id,
                func.count(EmployeeExecutionMetric.id).label("fail_count"),
            )
            .filter(
                EmployeeExecutionMetric.created_at >= cutoff,
                EmployeeExecutionMetric.status != "success",
            )
            .group_by(EmployeeExecutionMetric.employee_id)
            .order_by(func.count(EmployeeExecutionMetric.id).desc())
            .limit(lim)
            .all()
        )
        candidates = [
            (str(r[0] or "").strip(), int(r[1] or 0))
            for r in rows
            if str(r[0] or "").strip() and int(r[1] or 0) >= min_failures
        ]
    if not candidates:
        return {"ok": True, "enabled": True, "processed": 0, "created": 0}

    from modstore_server.employee_ai_pipeline import refine_system_prompt
    from modstore_server.employee_runtime import load_employee_pack, parse_employee_config_v2
    from modstore_server.runtime_async import run_coro_sync

    created = 0
    processed = 0
    for employee_id, fail_count in candidates:
        processed += 1
        sf2 = get_session_factory()
        with sf2() as session:
            try:
                pack = load_employee_pack(session, employee_id)
            except Exception:
                continue
            manifest = pack.get("manifest") if isinstance(pack.get("manifest"), dict) else {}
            cfg = parse_employee_config_v2(manifest)
            cog = cfg.get("cognition") if isinstance(cfg.get("cognition"), dict) else {}
            agent = cog.get("agent") if isinstance(cog.get("agent"), dict) else {}
            current_prompt = str(agent.get("system_prompt") or "").strip()
            if not current_prompt:
                continue

        instruction = (
            f"该员工在最近 {lookback_hours} 小时失败 {fail_count} 次。"
            "请优化 prompt：减少歧义，强化失败降级、工具调用顺序、边界约束与自检。"
        )
        role_context = f"employee_id={employee_id}"
        try:
            result, err = run_coro_sync(
                refine_system_prompt(
                    current_prompt=current_prompt,
                    instruction=instruction,
                    role_context=role_context,
                    llm=_PlatformBenchLlmClient(),
                )
            )
        except Exception as exc:
            result = None
            err = str(exc)

        improved = ""
        diff_expl = ""
        status = "failed"
        if not err and result:
            improved = str(result.get("improved_prompt") or "").strip()
            diff_expl = str(result.get("diff_explanation") or "").strip()
            if improved:
                status = "suggested"

        suggestion_id: Optional[int] = None
        if status == "suggested":
            out = create_employee_suggestion(
                source_employee_id="evolution-engine",
                summary=f"员工 {employee_id} 自进化建议（失败 {fail_count} 次）",
                detail=(
                    f"建议更新 system_prompt。\n"
                    f"diff_explanation: {diff_expl or 'n/a'}\n"
                    f"\n---prompt_after---\n{improved[:20_000]}"
                ),
                payload={
                    "kind": "employee_evolution",
                    "employee_id": employee_id,
                    "failure_count": fail_count,
                    "lookback_hours": lookback_hours,
                    "prompt_before": current_prompt[:30_000],
                    "prompt_after": improved[:30_000],
                    "diff_explanation": diff_expl,
                },
                target_employee_ids=["employee-pack-curator"],
                kind="employee_evolution",
                risk_level="medium",
                emit_event=True,
                auto_dispatch=False,
            )
            if out.get("ok"):
                suggestion_id = int(out.get("suggestion_id") or 0)

        sf3 = get_session_factory()
        with sf3() as session:
            rec = EmployeeEvolutionRecord(
                employee_id=employee_id[:128],
                failure_count=int(fail_count),
                lookback_hours=lookback_hours,
                status=status,
                prompt_before=current_prompt[:30_000],
                prompt_after=improved[:30_000],
                diff_explanation=diff_expl[:2000],
                triggered_by=(triggered_by or "scheduler")[:64],
                created_suggestion_id=suggestion_id,
                error=(err or "")[:2000],
            )
            session.add(rec)
            session.commit()
        if status == "suggested":
            created += 1
            _publish_event(
                "employee.evolution.suggested",
                {
                    "employee_id": employee_id,
                    "failure_count": fail_count,
                    "lookback_hours": lookback_hours,
                    "suggestion_id": suggestion_id,
                },
                source="evolution-engine",
            )

    return {
        "ok": True,
        "enabled": True,
        "processed": processed,
        "created": created,
        "lookback_hours": lookback_hours,
        "min_failures": min_failures,
    }


def aggregate_admin_suggestion_dashboard(limit_recent: int = 30) -> Dict[str, Any]:
    lim = max(1, min(int(limit_recent or 30), 200))
    sf = get_session_factory()
    with sf() as session:
        pending_cr = (
            session.query(func.count(EmployeeChangeRequest.id))
            .filter(EmployeeChangeRequest.status == "pending")
            .scalar()
            or 0
        )
        failed_cr = (
            session.query(func.count(EmployeeChangeRequest.id))
            .filter(EmployeeChangeRequest.status == "failed")
            .scalar()
            or 0
        )
        pending_suggestion = (
            session.query(func.count(EmployeeSuggestion.id))
            .filter(EmployeeSuggestion.status == "pending")
            .scalar()
            or 0
        )
        approved_suggestion = (
            session.query(func.count(EmployeeSuggestion.id))
            .filter(EmployeeSuggestion.status == "approved")
            .scalar()
            or 0
        )
        pending_brief = (
            session.query(func.count(PendingBriefTask.id))
            .filter(PendingBriefTask.status == "pending")
            .scalar()
            or 0
        )
        running_brief = (
            session.query(func.count(PendingBriefTask.id))
            .filter(PendingBriefTask.status == "running")
            .scalar()
            or 0
        )
        open_threads = (
            session.query(func.count(EmployeeCollabThread.id))
            .filter(EmployeeCollabThread.status == "open")
            .scalar()
            or 0
        )

        recent_suggestions = (
            session.query(EmployeeSuggestion)
            .order_by(EmployeeSuggestion.id.desc())
            .limit(lim)
            .all()
        )
        recent_tasks = (
            session.query(PendingBriefTask).order_by(PendingBriefTask.id.desc()).limit(lim).all()
        )
        recent_evolution = (
            session.query(EmployeeEvolutionRecord)
            .order_by(EmployeeEvolutionRecord.id.desc())
            .limit(lim)
            .all()
        )

    return {
        "ok": True,
        "counts": {
            "change_requests_pending": int(pending_cr),
            "change_requests_failed": int(failed_cr),
            "suggestions_pending": int(pending_suggestion),
            "suggestions_approved": int(approved_suggestion),
            "brief_tasks_pending": int(pending_brief),
            "brief_tasks_running": int(running_brief),
            "collab_threads_open": int(open_threads),
        },
        "recent_suggestions": [
            {
                "id": int(r.id),
                "source_employee_id": str(r.source_employee_id or ""),
                "target_employee_ids": _jloads(r.target_employee_ids_json or "[]", []),
                "kind": str(r.kind or ""),
                "summary": str(r.summary or ""),
                "status": str(r.status or ""),
                "risk_level": str(r.risk_level or ""),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in recent_suggestions
        ],
        "recent_brief_tasks": [
            {
                "id": int(r.id),
                "owner_employee_id": str(r.owner_employee_id or ""),
                "source_kind": str(r.source_kind or ""),
                "task_brief": str(r.task_brief or ""),
                "status": str(r.status or ""),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in recent_tasks
        ],
        "recent_evolution_records": [
            {
                "id": int(r.id),
                "employee_id": str(r.employee_id or ""),
                "failure_count": int(r.failure_count or 0),
                "status": str(r.status or ""),
                "created_suggestion_id": (
                    int(r.created_suggestion_id) if r.created_suggestion_id else None
                ),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in recent_evolution
        ],
    }


__all__ = [
    "aggregate_admin_suggestion_dashboard",
    "approve_suggestion",
    "create_collab_thread",
    "create_employee_suggestion",
    "dispatch_pending_brief_tasks",
    "dispatch_pending_suggestions",
    "dispatch_suggestion",
    "enqueue_daily_brief_todos",
    "ingest_suggestion_event_payload",
    "list_pending_brief_tasks",
    "post_collab_message",
    "reject_suggestion",
    "run_employee_evolution_scan",
    "trigger_doc_autofix_from_report",
]
