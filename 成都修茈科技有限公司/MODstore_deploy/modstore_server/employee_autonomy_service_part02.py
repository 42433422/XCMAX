# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_autonomy_service")


def _parse_todo_lines(todo_markdown: str) -> _facade().List[str]:
    out: _facade().List[str] = []
    for raw in (todo_markdown or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _facade()._TODO_BULLET_RE.match(line)
        if m:
            item = (m.group(1) or "").strip()
        else:
            item = line
        if not item:
            continue
        if item.startswith("**依据**") or item.startswith("依据："):
            continue
        out.append(item[:400])
    return _facade()._dedupe_strs(out)


def enqueue_daily_brief_todos(
    *,
    owner_employee_id: str,
    todo_markdown: str,
    source_ref: str,
    payload: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
) -> _facade().Dict[str, _facade().Any]:
    owner = str(owner_employee_id or "").strip()
    if not owner:
        return {"ok": False, "error": "owner_employee_id empty"}
    tasks = _facade()._parse_todo_lines(todo_markdown)
    if not tasks:
        return {"ok": True, "created": 0, "skipped": 0}
    created = 0
    skipped = 0
    source_key = str(source_ref or "").strip() or _facade().datetime.now(
        _facade().timezone.utc
    ).strftime("%Y-%m-%d")
    sf = _facade().get_session_factory()
    with sf() as session:
        for item in tasks:
            fp = (
                _facade()
                .hashlib.sha256(f"daily_brief|{owner}|{source_key}|{item}".encode("utf-8"))
                .hexdigest()[:64]
            )
            exists = (
                session.query(_facade().PendingBriefTask)
                .filter(_facade().PendingBriefTask.fingerprint == fp)
                .first()
            )
            if exists:
                skipped += 1
                continue
            row = _facade().PendingBriefTask(
                owner_employee_id=owner[:128],
                source_kind="daily_brief",
                source_ref=(source_ref or "")[:128],
                task_brief=item,
                payload_json=_facade()._jdumps(payload or {}, max_chars=20000),
                fingerprint=fp,
                status="pending",
            )
            session.add(row)
            created += 1
        session.commit()
    if created > 0:
        _facade()._publish_event(
            "employee.brief_todo.created",
            {"owner_employee_id": owner, "count": created, "source_ref": (source_ref or "")[:128]},
            source="daily_employee_briefs",
        )
    return {"ok": True, "created": created, "skipped": skipped}


def list_pending_brief_tasks(
    limit: int = 100, *, status: str = ""
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    lim = max(1, min(int(limit or 100), 500))
    sf = _facade().get_session_factory()
    with sf() as session:
        q = session.query(_facade().PendingBriefTask).order_by(_facade().PendingBriefTask.id.desc())
        st = str(status or "").strip()
        if st:
            q = q.filter(_facade().PendingBriefTask.status == st)
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


@_facade().platform_llm_scoped
def dispatch_pending_brief_tasks(limit: int = 20) -> _facade().Dict[str, _facade().Any]:
    lim = max(1, min(int(limit or 20), 100))
    sf = _facade().get_session_factory()
    with sf() as session:
        actor_uid = _facade()._resolve_actor_user_id(session, fallback_user_id=0)
        rows = (
            session.query(_facade().PendingBriefTask)
            .filter(_facade().PendingBriefTask.status == "pending")
            .order_by(_facade().PendingBriefTask.id.asc())
            .limit(lim)
            .all()
        )
        task_ids = [int(r.id) for r in rows]
        for r in rows:
            r.status = "running"
            r.dispatched_at = _facade().datetime.now(_facade().timezone.utc)
        session.commit()
    from modstore_server.task_router import route_and_dispatch

    processed = 0
    done = 0
    failed = 0
    for tid in task_ids:
        processed += 1
        sf2 = _facade().get_session_factory()
        with sf2() as session:
            row = session.get(_facade().PendingBriefTask, tid)
            if not row:
                continue
            task_brief = str(row.task_brief or "").strip()
            source_kind = str(row.source_kind or "").strip()
            if not task_brief:
                row.status = "cancelled"
                row.error = "task_brief empty"
                row.completed_at = _facade().datetime.now(_facade().timezone.utc)
                session.commit()
                failed += 1
                continue
        if source_kind == "boss_im":
            try:
                from modstore_server.boss_im_inbound import dispatch_boss_im_task

                bo = dispatch_boss_im_task(tid, actor_user_id=actor_uid)
                if bo.get("ok"):
                    done += 1
                else:
                    failed += 1
            except Exception as exc:
                _facade().logger.exception("boss_im dispatch crashed task_id=%s", tid)
                with sf2() as session:
                    row2 = session.get(_facade().PendingBriefTask, tid)
                    if row2:
                        row2.status = "failed"
                        row2.error = str(exc)[:2000]
                        row2.completed_at = _facade().datetime.now(_facade().timezone.utc)
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
                row2 = session.get(_facade().PendingBriefTask, tid)
                if row2:
                    row2.status = "done" if ok else "failed"
                    row2.dispatched_result_json = _facade()._jdumps(out, max_chars=120000)
                    row2.error = str(out.get("error") or "")[:2000]
                    row2.completed_at = _facade().datetime.now(_facade().timezone.utc)
                    session.commit()
            if ok:
                done += 1
            else:
                failed += 1
        except Exception as exc:
            with sf2() as session:
                row2 = session.get(_facade().PendingBriefTask, tid)
                if row2:
                    row2.status = "failed"
                    row2.error = str(exc)[:2000]
                    row2.completed_at = _facade().datetime.now(_facade().timezone.utc)
                    session.commit()
            failed += 1
    if task_ids:
        try:
            from modstore_server.employee_collab_reporter import report_brief_task

            for _tid in task_ids:
                report_brief_task(task_id=_tid)
        except Exception:
            _facade().logger.exception("collab report (brief tasks) failed")
    if processed > 0:
        _facade()._publish_event(
            "employee.brief_todo.dispatched",
            {"processed": processed, "done": done, "failed": failed},
            source="brief_dispatcher",
        )
    return {"ok": True, "processed": processed, "done": done, "failed": failed}


def trigger_doc_autofix_from_report(
    report: _facade().Dict[str, _facade().Any],
    *,
    source: str = "consistency_checker",
    source_ref: str = "",
) -> _facade().Dict[str, _facade().Any]:
    if not _facade()._doc_autofix_enabled():
        return {"ok": True, "enabled": False, "created_suggestions": 0, "created_tasks": 0}
    issues = report.get("issues") if isinstance(report.get("issues"), list) else []
    if not issues:
        return {"ok": True, "enabled": True, "created_suggestions": 0, "created_tasks": 0}
    by_employee: _facade().Dict[str, _facade().List[_facade().Dict[str, _facade().Any]]] = (
        _facade().defaultdict(list)
    )
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
        detail = "\n".join(desc_lines)[:12000]
        summary = f"文档一致性修复：{emp} ({len(emp_issues)} 项)"
        out = _facade().create_employee_suggestion(
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
            auto_dispatch=_facade()._suggestion_auto_dispatch_enabled(),
        )
        if out.get("ok"):
            created_suggestions += 1
        t = _facade().enqueue_daily_brief_todos(
            owner_employee_id="doc-knowledge-curator",
            todo_markdown=f"1. 修复 {emp} 文档一致性问题（{len(emp_issues)} 项）",
            source_ref=source_ref
            or _facade().datetime.now(_facade().timezone.utc).strftime("%Y-%m-%d"),
            payload={"kind": "doc_consistency_fix", "employee": emp},
        )
        created_tasks += int(t.get("created") or 0)
    if created_tasks > 0 and _facade()._brief_auto_dispatch_enabled():
        _facade().dispatch_pending_brief_tasks(limit=max(5, created_tasks))
    return {
        "ok": True,
        "enabled": True,
        "created_suggestions": created_suggestions,
        "created_tasks": created_tasks,
    }


class _PlatformBenchLlmClient:

    async def chat(
        self, messages: _facade().List[_facade().Dict[str, str]], *, max_tokens: int = 1024
    ) -> str:
        from modstore_server.services.llm import (
            chat_dispatch_via_platform_only,
            resolve_platform_bench_llm,
        )

        (provider, model) = resolve_platform_bench_llm()
        if not provider or not model:
            raise RuntimeError("platform bench llm not configured")
        out = await chat_dispatch_via_platform_only(
            provider, model, messages, max_tokens=max_tokens
        )
        if not out.get("ok"):
            raise RuntimeError(str(out.get("error") or "llm call failed"))
        return str(out.get("content") or "")
