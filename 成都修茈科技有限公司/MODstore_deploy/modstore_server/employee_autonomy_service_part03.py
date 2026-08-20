# mypy: disable-error-code="arg-type, attr-defined, no-any-return, union-attr, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.employee_autonomy_service")


def _alert_evolution_quota_circuit_break(quota_failures: int, lookback_hours: int) -> None:
    """配额耗尽触发自进化熔断：高优先级告警日志（供 ops 监控/告警管道捕获）。

    改 prompt 无法修复额度耗尽，继续重写只会再发 LLM 调用、放大 403 死亡螺旋；
    因此本轮直接暂停，并把根因(配额/计费)显式告警，而非淹没在通用 failed 噪声里。
    """
    _facade().logger.warning(
        "employee_evolution_circuit_break reason=quota_exhausted quota_failures=%s lookback_hours=%s —— 失败由配额/计费(403)主导，已暂停本轮 prompt 自进化以止血 LLM 调用；请补充平台/用户 LLM 额度后自动恢复",
        quota_failures,
        lookback_hours,
    )


def _evolution_failure_candidates(
    session, *, cutoff, min_failures: int, limit: int
) -> _facade().List[_facade().Tuple[str, int]]:
    """近窗口内 prompt-可修失败 ≥ ``min_failures`` 的员工 ``(employee_id, fail_count)``。

    排除 ``_EVOLUTION_INFRA_FAILURE_MARKERS`` 命中的基建/配额类失败——这些不是 prompt 问题，
    若计入会导致配额耗尽时进化引擎空转（见上方说明）。
    """
    err_col = _facade().func.coalesce(_facade().EmployeeExecutionMetric.error, "")
    task_col = _facade().func.lower(
        _facade().func.coalesce(_facade().EmployeeExecutionMetric.task, "")
    )
    infra_kinds = [_facade().FAILURE_KIND_QUOTA, _facade().FAILURE_KIND_TRANSIENT]
    query = session.query(
        _facade().EmployeeExecutionMetric.employee_id,
        _facade().func.count(_facade().EmployeeExecutionMetric.id).label("fail_count"),
    ).filter(
        _facade().EmployeeExecutionMetric.created_at >= cutoff,
        _facade().EmployeeExecutionMetric.status != "success",
        _facade().or_(
            _facade().EmployeeExecutionMetric.failure_kind.is_(None),
            ~_facade().EmployeeExecutionMetric.failure_kind.in_(infra_kinds),
        ),
    )
    for marker in _facade()._EVOLUTION_INFRA_FAILURE_MARKERS:
        query = query.filter(~err_col.ilike(f"%{marker}%"))
    for marker in _facade()._EVOLUTION_IGNORED_TASK_MARKERS:
        query = query.filter(~task_col.like(f"%{marker}%"))
    query = query.filter(
        ~_facade().and_(
            _facade().EmployeeExecutionMetric.employee_id.in_(_facade()._PARA_DELEGATE_EMPLOYEES),
            _facade().func.lower(err_col) == _facade()._GENERIC_HANDLER_FAILURE,
        )
    )
    rows = (
        query.group_by(_facade().EmployeeExecutionMetric.employee_id)
        .order_by(_facade().func.count(_facade().EmployeeExecutionMetric.id).desc())
        .limit(limit)
        .all()
    )
    return [
        (str(r[0] or "").strip(), int(r[1] or 0))
        for r in rows
        if str(r[0] or "").strip() and int(r[1] or 0) >= min_failures
    ]


@_facade().platform_llm_scoped
def run_employee_evolution_scan(
    *,
    lookback_hours: int = 24,
    min_failures: int = 3,
    limit: int = 20,
    triggered_by: str = "scheduler",
) -> _facade().Dict[str, _facade().Any]:
    if not _facade()._evolution_enabled():
        return {"ok": True, "enabled": False, "processed": 0, "created": 0}
    lookback_hours = max(1, min(int(lookback_hours or 24), 168))
    min_failures = max(1, min(int(min_failures or 3), 50))
    lim = max(1, min(int(limit or 20), 100))
    cutoff = _facade().datetime.now(_facade().timezone.utc) - _facade().timedelta(
        hours=lookback_hours
    )
    sf = _facade().get_session_factory()
    with sf() as session:
        candidates = _facade()._evolution_failure_candidates(
            session, cutoff=cutoff, min_failures=min_failures, limit=lim
        )
        quota_fail_total = int(
            session.query(_facade().func.count(_facade().EmployeeExecutionMetric.id))
            .filter(
                _facade().EmployeeExecutionMetric.created_at >= cutoff,
                _facade().EmployeeExecutionMetric.status != "success",
                _facade().EmployeeExecutionMetric.failure_kind == _facade().FAILURE_KIND_QUOTA,
            )
            .scalar()
            or 0
        )
    if not candidates and quota_fail_total > 0:
        _facade()._alert_evolution_quota_circuit_break(quota_fail_total, lookback_hours)
        return {
            "ok": True,
            "enabled": True,
            "processed": 0,
            "created": 0,
            "circuit_broken": True,
            "skipped_reason": "quota_exhausted",
            "quota_failures": quota_fail_total,
        }
    if not candidates:
        return {
            "ok": True,
            "enabled": True,
            "processed": 0,
            "created": 0,
            "quota_failures": quota_fail_total,
        }
    from modstore_server.employee_ai_pipeline import refine_system_prompt
    from modstore_server.employee_runtime import (
        load_employee_pack,
        parse_employee_config_v2,
    )
    from modstore_server.runtime_async import run_coro_sync

    created = 0
    processed = 0
    for employee_id, fail_count in candidates:
        processed += 1
        try:
            from modstore_server.employee_runtime_policy import (
                record_employee_degradation,
            )

            record_employee_degradation(
                employee_id=employee_id,
                fail_count=fail_count,
                lookback_hours=lookback_hours,
                reason="employee_evolution_signal_failure_rate",
                severity="warn",
            )
        except RECOVERABLE_ERRORS:
            _facade().logger.debug(
                "employee evolution runtime policy update failed employee=%s",
                employee_id,
                exc_info=True,
            )
        sf2 = _facade().get_session_factory()
        with sf2() as session:
            try:
                pack = load_employee_pack(session, employee_id)
            except RECOVERABLE_ERRORS:
                continue
            manifest = pack.get("manifest") if isinstance(pack.get("manifest"), dict) else {}
            cfg = parse_employee_config_v2(manifest)
            cog = cfg.get("cognition") if isinstance(cfg.get("cognition"), dict) else {}
            agent = cog.get("agent") if isinstance(cog.get("agent"), dict) else {}
            current_prompt = str(agent.get("system_prompt") or "").strip()
            if not current_prompt:
                continue
        instruction = f"该员工在最近 {lookback_hours} 小时失败 {fail_count} 次。请优化 prompt：减少歧义，强化失败降级、工具调用顺序、边界约束与自检。"
        role_context = f"employee_id={employee_id}"
        try:
            result, err = run_coro_sync(
                refine_system_prompt(
                    current_prompt=current_prompt,
                    instruction=instruction,
                    role_context=role_context,
                    llm=_facade()._PlatformBenchLlmClient(),
                )
            )
        except RECOVERABLE_ERRORS as exc:
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
        suggestion_id: _facade().Optional[int] = None
        if status == "suggested":
            out = _facade().create_employee_suggestion(
                source_employee_id="evolution-engine",
                summary=f"员工 {employee_id} 自进化建议（失败 {fail_count} 次）",
                detail=f"建议更新 system_prompt。\ndiff_explanation: {diff_expl or 'n/a'}\n\n---prompt_after---\n{improved[:20000]}",
                payload={
                    "kind": "employee_evolution",
                    "employee_id": employee_id,
                    "failure_count": fail_count,
                    "lookback_hours": lookback_hours,
                    "prompt_before": current_prompt[:30000],
                    "prompt_after": improved[:30000],
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
        evolution_record_id = 0
        apply_meta: _facade().Dict[str, _facade().Any] = {}
        sf3 = _facade().get_session_factory()
        with sf3() as session:
            rec = _facade().EmployeeEvolutionRecord(
                employee_id=employee_id[:128],
                failure_count=int(fail_count),
                lookback_hours=lookback_hours,
                status=status,
                prompt_before=current_prompt[:30000],
                prompt_after=improved[:30000],
                diff_explanation=diff_expl[:2000],
                triggered_by=(triggered_by or "scheduler")[:64],
                created_suggestion_id=suggestion_id,
                error=(err or "")[:2000],
            )
            session.add(rec)
            session.commit()
            evolution_record_id = int(rec.id or 0)
        if status == "suggested" and improved:
            try:
                from modstore_server.prompt_evolution_ab import (
                    maybe_auto_apply_prompt_evolution,
                )

                apply_meta = maybe_auto_apply_prompt_evolution(
                    employee_id=employee_id,
                    prompt_before=current_prompt,
                    prompt_after=improved,
                    evolution_record_id=evolution_record_id,
                    lookback_hours=lookback_hours,
                )
                if apply_meta.get("applied"):
                    sf4 = _facade().get_session_factory()
                    with sf4() as session:
                        row = session.get(_facade().EmployeeEvolutionRecord, evolution_record_id)
                        if row is not None:
                            row.status = "applied"
                            session.commit()
                    status = "applied"
                elif apply_meta.get("ab", {}).get("verdict") == "before":
                    revert = apply_meta.get("ab", {})
                    sf4 = _facade().get_session_factory()
                    with sf4() as session:
                        row = session.get(_facade().EmployeeEvolutionRecord, evolution_record_id)
                        if row is not None:
                            row.status = "ab_rejected"
                            row.error = str(revert)[:2000]
                            session.commit()
            except RECOVERABLE_ERRORS:
                _facade().logger.exception(
                    "prompt evolution A/B apply failed employee=%s", employee_id
                )
        if status == "suggested":
            created += 1
            _facade()._publish_event(
                "employee.evolution.suggested",
                {
                    "employee_id": employee_id,
                    "failure_count": fail_count,
                    "lookback_hours": lookback_hours,
                    "suggestion_id": suggestion_id,
                },
                source="evolution-engine",
            )
        if evolution_record_id:
            try:
                from modstore_server.employee_collab_reporter import report_evolution

                report_evolution(evolution_record_id=evolution_record_id)
            except RECOVERABLE_ERRORS:
                _facade().logger.exception(
                    "collab report (evolution) failed id=%s", evolution_record_id
                )
    return {
        "ok": True,
        "enabled": True,
        "processed": processed,
        "created": created,
        "lookback_hours": lookback_hours,
        "min_failures": min_failures,
        "quota_failures": quota_fail_total,
    }


def aggregate_admin_suggestion_dashboard(
    limit_recent: int = 30,
) -> _facade().Dict[str, _facade().Any]:
    lim = max(1, min(int(limit_recent or 30), 200))
    sf = _facade().get_session_factory()
    with sf() as session:
        pending_cr = (
            session.query(_facade().func.count(_facade().EmployeeChangeRequest.id))
            .filter(_facade().EmployeeChangeRequest.status == "pending")
            .scalar()
            or 0
        )
        failed_cr = (
            session.query(_facade().func.count(_facade().EmployeeChangeRequest.id))
            .filter(_facade().EmployeeChangeRequest.status == "failed")
            .scalar()
            or 0
        )
        pending_suggestion = (
            session.query(_facade().func.count(_facade().EmployeeSuggestion.id))
            .filter(_facade().EmployeeSuggestion.status == "pending")
            .scalar()
            or 0
        )
        approved_suggestion = (
            session.query(_facade().func.count(_facade().EmployeeSuggestion.id))
            .filter(_facade().EmployeeSuggestion.status == "approved")
            .scalar()
            or 0
        )
        pending_brief = (
            session.query(_facade().func.count(_facade().PendingBriefTask.id))
            .filter(_facade().PendingBriefTask.status == "pending")
            .scalar()
            or 0
        )
        running_brief = (
            session.query(_facade().func.count(_facade().PendingBriefTask.id))
            .filter(_facade().PendingBriefTask.status == "running")
            .scalar()
            or 0
        )
        open_threads = (
            session.query(_facade().func.count(_facade().EmployeeCollabThread.id))
            .filter(_facade().EmployeeCollabThread.status == "open")
            .scalar()
            or 0
        )
        recent_suggestions = (
            session.query(_facade().EmployeeSuggestion)
            .order_by(_facade().EmployeeSuggestion.id.desc())
            .limit(lim)
            .all()
        )
        recent_tasks = (
            session.query(_facade().PendingBriefTask)
            .order_by(_facade().PendingBriefTask.id.desc())
            .limit(lim)
            .all()
        )
        recent_evolution = (
            session.query(_facade().EmployeeEvolutionRecord)
            .order_by(_facade().EmployeeEvolutionRecord.id.desc())
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
                "target_employee_ids": _facade()._jloads(r.target_employee_ids_json or "[]", []),
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
