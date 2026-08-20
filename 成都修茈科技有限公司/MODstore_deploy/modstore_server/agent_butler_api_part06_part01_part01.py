# mypy: disable-error-code="attr-defined, misc, no-any-return, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.agent_butler_api")


@_facade().router.post("/orchestrate")
async def butler_orchestrate(
    body: _facade()._ButlerOrchestrateBody,
    db: _facade().Session = _facade().Depends(_facade().get_db),
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """启动 vibe-coding 改写管线（异步，返回 session_id 供轮询）。

    前端用 GET /api/workbench/sessions/{session_id} 轮询进度。
    """
    from modstore_server.workbench_api import (
        _SESSION_LOCK,
        WORKBENCH_SESSIONS,
        _persist_workbench_session_unlocked,
        _pipeline_task_failsafe,
    )

    sid = _facade().uuid.uuid4().hex[:24]
    payload = body.model_dump()
    async with _SESSION_LOCK:
        WORKBENCH_SESSIONS[sid] = {
            "id": sid,
            "user_id": user.id,
            "intent": "butler",
            "status": "running",
            "steps": _facade()._butler_orchestrate_steps(),
            "planning_record": {
                "brief": body.brief,
                "target_type": body.target_type,
                "target_id": body.target_id,
            },
            "artifact": None,
            "error": None,
            "validate_warnings": None,
            "sandbox_report": None,
            "script_result": None,
        }
        _persist_workbench_session_unlocked(sid)
    task = _facade().asyncio.create_task(
        _facade()._run_butler_orchestrate_pipeline(sid, user.id, payload)
    )
    task.add_done_callback(_pipeline_task_failsafe(sid))
    return {"session_id": sid, "status": "running"}


def _safe_json(s: _facade().Any) -> _facade().Dict[str, _facade().Any]:
    if isinstance(s, dict):
        return s
    try:
        return _facade().json.loads(s or "{}")
    except RECOVERABLE_ERRORS:
        return {}


class AllHandsReportDTO(_facade().BaseModel):
    """``POST /api/agent/butler/all-hands-report`` 入参。

    - ``employee_ids`` 为空时，从 ``duty_roster`` ∩ ``catalog`` 取全集；
    - ``with_research`` 控制是否做联网 + GitHub 调研（关掉可加快出报告，但失去
      "上网思考自我优化"那一段的真实根据）；
    - ``max_employees`` / ``concurrency`` 两个上限避免一次把平台 LLM bench 配额
      打爆；
    - ``user_question`` 非空时切到 Q&A 模板：每个员工只针对该问题回答（保留
      manifest_signals / recent_failures / yuangon_pack_excerpt 作为根据）；
    - ``synthesize`` 在 ``user_question`` 模式下默认开启，用 bench LLM 合并
      所有员工的答复，输出一段「数字管家综合答复」。
    """

    employee_ids: _facade().Optional[_facade().List[str]] = None
    with_research: bool = True
    max_employees: int = _facade().Field(8, ge=1, le=_facade().MAX_ALL_HANDS_EMPLOYEES)
    concurrency: int = _facade().Field(2, ge=1, le=4)
    user_question: _facade().Optional[str] = _facade().Field(default=None, max_length=600)
    synthesize: bool = True


def _all_hands_session_steps(
    *, with_synthesize: bool = False
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    """与 workbench session 结构对齐的全员汇报阶段。

    ``with_synthesize=True`` 时插入一段「数字管家综合答复」步骤，与
    :func:`modstore_server.all_hands_report.build_all_hands_report` 中的合并阶段
    一一对应。
    """
    steps: _facade().List[_facade().Dict[str, _facade().Any]] = [
        {
            "id": "prepare",
            "label": "准备员工清单",
            "status": "pending",
            "message": None,
        },
        {
            "id": "collect",
            "label": "收集全员汇报",
            "status": "pending",
            "message": None,
        },
    ]
    if with_synthesize:
        steps.append(
            {
                "id": "synthesize",
                "label": "数字管家综合答复",
                "status": "pending",
                "message": None,
            }
        )
    steps.append({"id": "minutes", "label": "生成会议摘要", "status": "pending", "message": None})
    steps.append({"id": "complete", "label": "完成", "status": "pending", "message": None})
    return steps


async def _run_all_hands_report_session(
    sid: str, user_id: int, payload: _facade().Dict[str, _facade().Any]
) -> None:
    """后台执行全员汇报，并把结果写入 workbench session。"""
    from modstore_server.all_hands_report import (
        build_all_hands_report,
        synthesize_meeting_minutes,
    )
    from modstore_server.daily_digest import (
        DEFAULT_DIGEST_EMAIL,
        parse_daily_digest_recipient_emails,
    )
    from modstore_server.email_service import send_simple_html_email
    from modstore_server.workbench_api import (
        _SESSION_LOCK,
        WORKBENCH_SESSIONS,
        _fail_session,
        _finalize_session_done,
        _persist_workbench_session_unlocked,
        _set_step,
    )

    employee_ids_raw = payload.get("employee_ids")
    employee_ids = employee_ids_raw if isinstance(employee_ids_raw, list) else None
    max_employees = _facade().clamp_all_hands_max_employees(payload.get("max_employees"))
    with_research = bool(payload.get("with_research", True))
    concurrency = int(payload.get("concurrency") or 2)
    user_question_raw = payload.get("user_question")
    user_question = str(user_question_raw or "").strip() if user_question_raw else ""
    synthesize_flag = bool(payload.get("synthesize", True)) and bool(user_question)
    await _set_step(sid, "prepare", "running", "正在整理可汇报员工清单…")
    await _set_step(
        sid,
        "prepare",
        "done",
        f"并发 {max(1, min(concurrency, 4))}；最多 {max_employees} 人",
    )
    await _set_step(
        sid,
        "collect",
        "running",
        (
            f"数字管家在向 {max_employees} 名员工发问…"
            if user_question
            else "数字管家正在逐个收集员工汇报（含 manifest/执行流水/可选联网调研）…"
        ),
    )

    def _to_nonneg_int(v: _facade().Any) -> int:
        try:
            return max(0, int(v))
        except (TypeError, ValueError):
            return 0

    async def _on_progress(evt: _facade().Dict[str, _facade().Any]) -> None:
        stage = str(evt.get("stage") or "").strip().lower()
        total = _to_nonneg_int(evt.get("total"))
        completed = _to_nonneg_int(evt.get("completed"))
        ok_n = _to_nonneg_int(evt.get("ok"))
        err_n = _to_nonneg_int(evt.get("error"))
        if stage == "minutes":
            percent = 97
        elif stage == "synthesize":
            percent = 92
        elif stage == "completed":
            percent = 90 if total > 0 else 100
        elif total > 0:
            completed = min(completed, total)
            percent = int(round(completed / total * 88))
        else:
            percent = 0
        progress = {
            "stage": stage or "collect",
            "total": total,
            "completed": completed,
            "ok": ok_n,
            "error": err_n,
            "percent": max(0, min(percent, 100)),
            "current_employee_id": str(evt.get("employee_id") or ""),
            "current_employee_name": str(evt.get("employee_name") or ""),
            "current_employee_status": str(evt.get("employee_status") or ""),
            "updated_at": str(
                evt.get("updated_at")
                or _facade().datetime.now(_facade().timezone.utc).isoformat() + "Z"
            ),
        }
        async with _SESSION_LOCK:
            sess = WORKBENCH_SESSIONS.get(sid)
            if not sess:
                return
            planning = sess.get("planning_record")
            if not isinstance(planning, dict):
                planning = {}
            planning["progress"] = progress
            sess["planning_record"] = planning
            _persist_workbench_session_unlocked(sid)
        if stage == "prepare":
            await _set_step(
                sid,
                "prepare",
                "done",
                f"已准备 {total} 名员工，开始收集汇报（并发 {max(1, min(concurrency, 4))}）",
            )
        elif stage == "employee_done":
            await _set_step(
                sid,
                "collect",
                "running",
                f"已完成 {completed}/{max(total, completed)}（成功 {ok_n}，异常 {err_n}）",
            )

    try:
        report = await build_all_hands_report(
            employee_ids=employee_ids,
            max_employees=max_employees,
            with_research=with_research,
            user_id=user_id,
            concurrency=concurrency,
            progress_cb=_on_progress,
            user_question=user_question or None,
            synthesize=synthesize_flag,
        )
    except RECOVERABLE_ERRORS as exc:
        _facade().logger.exception("all-hands-report session failed sid=%s user=%s", sid, user_id)
        await _fail_session(sid, "collect", f"全员汇报失败：{exc}")
        return
    if not bool(report.get("ok", True)):
        await _fail_session(sid, "collect", str(report.get("error") or "全员汇报失败"))
        return
    done_count = len(report.get("employees") or [])
    await _set_step(sid, "collect", "done", f"已收集 {done_count} 名员工汇报")
    await _on_progress(
        {
            "stage": "completed",
            "total": done_count,
            "completed": done_count,
            "ok": int((report.get("summary") or {}).get("ok") or 0),
            "error": int((report.get("summary") or {}).get("error") or 0),
            "updated_at": _facade().datetime.now(_facade().timezone.utc).isoformat(),
        }
    )
    if synthesize_flag:
        synth = report.get("synthesized_answer") if isinstance(report, dict) else None
        if isinstance(synth, dict) and (synth.get("markdown") or "").strip():
            cited = synth.get("cited_employees") or []
            cite_count = len(cited) if isinstance(cited, list) else 0
            await _set_step(sid, "synthesize", "done", f"综合答复已生成，引用员工 {cite_count} 名")
        else:
            err = ""
            if isinstance(synth, dict):
                err = str(synth.get("error") or "").strip()
            await _set_step(
                sid,
                "synthesize",
                "done",
                f"综合答复跳过：{err}" if err else "综合答复未生成（bench LLM 不可用）",
            )
    await _set_step(sid, "minutes", "running", "正在生成会议摘要…")
    await _on_progress(
        {
            "stage": "minutes",
            "total": done_count,
            "completed": done_count,
            "ok": int((report.get("summary") or {}).get("ok") or 0),
            "error": int((report.get("summary") or {}).get("error") or 0),
            "updated_at": _facade().datetime.now(_facade().timezone.utc).isoformat(),
        }
    )
    meeting_minutes = await synthesize_meeting_minutes(report=report, user_id=user_id)
    body_text = str(meeting_minutes.get("text") or "").strip()
    minutes_err = str(meeting_minutes.get("error") or "").strip()
    day = _facade().datetime.now(_facade().timezone.utc).strftime("%Y-%m-%d")
    subject = f"MODstore 员工大会会议摘要 · {day}"
    recipients = parse_daily_digest_recipient_emails(
        _facade().os.environ.get("MODSTORE_DAILY_DIGEST_EMAIL", DEFAULT_DIGEST_EMAIL).strip()
    )
    meeting_minutes_email: _facade().Dict[str, _facade().Any] = {
        "recipients_count": len(recipients),
        "any_delivered": False,
        "per_to": [],
    }
    if not recipients:
        meeting_minutes_email["skipped_reason"] = "无有效收件人（MODSTORE_DAILY_DIGEST_EMAIL）"
    elif not body_text:
        meeting_minutes_email["skipped_reason"] = "会议摘要正文为空，已跳过发信"
    else:
        html_body = f'<html><body style="font-family:sans-serif;padding:20px"><h2 style="color:#1e293b">员工大会 · 会议摘要</h2><pre style="white-space:pre-wrap;font-size:14px;line-height:1.6;color:#334155">{_facade().html.escape(body_text)}</pre></body></html>'
        any_delivered = False
        for to_email in recipients:
            result = send_simple_html_email(to_email, subject, html_body)
            deliv = bool(result.get("delivered"))
            if deliv:
                any_delivered = True
            meeting_minutes_email["per_to"].append(
                {
                    "to": to_email,
                    "delivered": deliv,
                    "mode": str(result.get("mode") or ""),
                }
            )
        meeting_minutes_email["any_delivered"] = any_delivered
        _facade().logger.info(
            "all-hands meeting minutes email sid=%s recipients=%s any_delivered=%s",
            sid,
            len(recipients),
            any_delivered,
        )
    if body_text and meeting_minutes_email.get("any_delivered"):
        minutes_done_msg = "会议摘要已生成并已发信（每日摘要收件箱）"
    elif body_text and (not recipients):
        minutes_done_msg = "会议摘要已生成；无有效早报收件人，未发信"
    elif body_text:
        minutes_done_msg = "会议摘要已生成；SMTP 未配置或邮件未成功投递"
    elif minutes_err:
        minutes_done_msg = f"会议摘要未产出正文：{minutes_err[:120]}"
    else:
        minutes_done_msg = "会议摘要未产出正文"
    await _set_step(sid, "minutes", "done", minutes_done_msg)
    await _set_step(sid, "complete", "running", "正在整理报告输出…")
    await _finalize_session_done(
        sid,
        {
            "type": "all_hands_report",
            "all_hands_report": report,
            "summary": report.get("summary") if isinstance(report, dict) else {},
            "synthesized_answer": (
                report.get("synthesized_answer") if isinstance(report, dict) else None
            ),
            "meeting_minutes": meeting_minutes,
            "meeting_minutes_email": meeting_minutes_email,
            "completed_at": _facade().datetime.now(_facade().timezone.utc).isoformat() + "Z",
        },
    )


@_facade().router.post("/all-hands-report/sessions")
async def butler_all_hands_report_session_start(
    body: AllHandsReportDTO,
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """启动全员汇报后台任务（秒回 session_id，前端轮询 `/api/workbench/sessions/{id}`）。"""
    if not getattr(user, "is_admin", False):
        raise _facade().HTTPException(403, "仅管理员可触发全员汇报")
    from modstore_server.workbench_api import (
        _SESSION_LOCK,
        WORKBENCH_SESSIONS,
        _persist_workbench_session_unlocked,
        _pipeline_task_failsafe,
    )

    sid = _facade().uuid.uuid4().hex[:24]
    payload = body.model_dump()
    req_ids = payload.get("employee_ids")
    req_count = len(req_ids) if isinstance(req_ids, list) else 0
    user_question_raw = payload.get("user_question")
    user_question_str = str(user_question_raw or "").strip() if user_question_raw else ""
    synth_flag = bool(payload.get("synthesize", True)) and bool(user_question_str)
    async with _SESSION_LOCK:
        WORKBENCH_SESSIONS[sid] = {
            "id": sid,
            "user_id": user.id,
            "intent": "butler_all_hands_report",
            "status": "running",
            "steps": _facade()._all_hands_session_steps(with_synthesize=synth_flag),
            "planning_record": {
                "employee_ids_count": req_count,
                "with_research": bool(payload.get("with_research", True)),
                "max_employees": _facade().clamp_all_hands_max_employees(
                    payload.get("max_employees")
                ),
                "concurrency": int(payload.get("concurrency") or 2),
                "user_question": user_question_str,
                "synthesize": synth_flag,
                "progress": {
                    "stage": "prepare",
                    "total": 0,
                    "completed": 0,
                    "ok": 0,
                    "error": 0,
                    "percent": 0,
                    "current_employee_id": "",
                    "current_employee_name": "",
                    "current_employee_status": "",
                    "updated_at": _facade().datetime.now(_facade().timezone.utc).isoformat() + "Z",
                },
            },
            "artifact": None,
            "error": None,
            "validate_warnings": None,
            "sandbox_report": None,
            "script_result": None,
        }
        _persist_workbench_session_unlocked(sid)
    task = _facade().asyncio.create_task(
        _facade()._run_all_hands_report_session(sid=sid, user_id=int(user.id), payload=payload)
    )
    task.add_done_callback(_pipeline_task_failsafe(sid))
    return {"session_id": sid, "status": "running"}
