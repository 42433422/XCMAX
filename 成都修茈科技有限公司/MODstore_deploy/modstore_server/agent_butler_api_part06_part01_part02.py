# mypy: disable-error-code="attr-defined, misc, no-any-return, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib
from modstore_server.agent_butler_api_part06_part01_part01 import AllHandsReportDTO


def _facade():
    return importlib.import_module("modstore_server.agent_butler_api")


@_facade().router.post("/all-hands-report")
async def butler_all_hands_report(
    body: AllHandsReportDTO,
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """让数字管家召集全员汇报（**仅管理员**）。

    每个员工会按 ``modstore_server.all_hands_report.ALL_HANDS_TASK_TEMPLATE``
    的固定 4 段结构（架构 / 问题与解决 / 联网调研后的优化 / 待办）输出 Markdown，
    并在 prompt 中显式要求"联动其他岗位"，让汇报互相串起来。
    """
    if not getattr(user, "is_admin", False):
        raise _facade().HTTPException(403, "仅管理员可触发全员汇报")
    from modstore_server.all_hands_report import build_all_hands_report

    try:
        uq = (body.user_question or "").strip() if body.user_question else ""
        synth = bool(body.synthesize) and bool(uq)
        report = await build_all_hands_report(
            employee_ids=body.employee_ids,
            max_employees=int(body.max_employees),
            with_research=bool(body.with_research),
            user_id=int(user.id),
            user_question=uq or None,
            synthesize=synth,
            concurrency=int(body.concurrency),
        )
    except RECOVERABLE_ERRORS as exc:
        _facade().logger.exception("all-hands-report failed user=%s", user.id)
        raise _facade().HTTPException(500, f"全员汇报失败：{exc}") from exc
    return report


class DigestVibePrepDTO(_facade().BaseModel):
    """``POST .../daily-digests/{id}/vibe-prep/sessions`` 入参。"""

    mode: str = _facade().Field("auto", description="auto=轻量快照+合成；manual=逐员工汇报后合成")
    employee_ids: _facade().Optional[_facade().List[str]] = None
    max_employees: int = _facade().Field(52, ge=1, le=_facade().MAX_ALL_HANDS_EMPLOYEES)
    concurrency: int = _facade().Field(2, ge=1, le=4)


def _vibe_prep_session_steps() -> _facade().List[_facade().Dict[str, _facade().Any]]:
    return [
        {
            "id": "prepare",
            "label": "准备员工清单",
            "status": "pending",
            "message": None,
        },
        {
            "id": "collect",
            "label": "收集员工快照",
            "status": "pending",
            "message": None,
        },
        {
            "id": "synthesize",
            "label": "生成更新/补丁 Markdown",
            "status": "pending",
            "message": None,
        },
        {"id": "complete", "label": "完成", "status": "pending", "message": None},
    ]


async def _run_digest_vibe_prep_session(
    sid: str,
    user_id: int,
    digest_row: _facade().DailyDigestRecord,
    payload: _facade().Dict[str, _facade().Any],
) -> None:
    from modstore_server.digest_vibe_prep import build_digest_vibe_prep
    from modstore_server.workbench_api import (
        _SESSION_LOCK,
        WORKBENCH_SESSIONS,
        _fail_session,
        _finalize_session_done,
        _persist_workbench_session_unlocked,
        _set_step,
    )

    mode = str(payload.get("mode") or "auto").strip().lower()
    if mode not in ("auto", "manual"):
        mode = "auto"
    employee_ids_raw = payload.get("employee_ids")
    employee_ids = employee_ids_raw if isinstance(employee_ids_raw, list) else None
    max_employees = _facade().clamp_all_hands_max_employees(
        payload.get("max_employees"), default=52
    )
    concurrency = int(payload.get("concurrency") or 2)
    await _set_step(sid, "prepare", "running", f"模式：{('手动' if mode == 'manual' else '自动')}…")
    await _set_step(
        sid,
        "prepare",
        "done",
        f"{('手动逐岗汇报' if mode == 'manual' else '自动轻量快照')} · 最多 {max_employees} 人",
    )
    await _set_step(sid, "collect", "running", "正在汇总各员工上下文…")

    async def _on_progress(evt: _facade().Dict[str, _facade().Any]) -> None:
        stage = str(evt.get("stage") or "collect")
        total = int(evt.get("total") or 0)
        completed = int(evt.get("completed") or 0)
        percent = int(round(completed / total * 100)) if total > 0 else 0
        progress = {
            "stage": stage,
            "mode": str(evt.get("mode") or mode),
            "total": total,
            "completed": completed,
            "percent": max(0, min(percent, 100)),
            "current_employee_id": str(evt.get("employee_id") or ""),
            "current_employee_name": str(evt.get("employee_name") or ""),
            "current_employee_status": str(evt.get("employee_status") or ""),
            "updated_at": _facade().datetime.now(_facade().timezone.utc).isoformat() + "Z",
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
        if stage == "collect":
            await _set_step(
                sid,
                "collect",
                "running",
                f"已收集 {completed}/{max(total, completed)} 名员工",
            )

    try:
        result = await build_digest_vibe_prep(
            digest_day=str(digest_row.day or ""),
            digest_subject=str(digest_row.subject or ""),
            digest_body_html=str(digest_row.body_html or ""),
            digest_body_text=str(digest_row.body_text or ""),
            meeting_minutes_html=str(digest_row.meeting_minutes_html or ""),
            mode=mode,
            employee_ids=employee_ids,
            max_employees=max_employees,
            concurrency=concurrency,
            user_id=user_id,
            record_id=int(digest_row.id or 0),
            progress_cb=_on_progress,
        )
    except RECOVERABLE_ERRORS as exc:
        _facade().logger.exception("digest vibe-prep session failed sid=%s", sid)
        await _fail_session(sid, "collect", f"Vibe 预备文档生成失败：{exc}")
        return
    if not result.get("ok"):
        await _fail_session(sid, "synthesize", str(result.get("error") or "合成失败"))
        return
    n = int(result.get("employee_count") or 0)
    await _set_step(sid, "collect", "done", f"已汇总 {n} 名员工")
    await _set_step(sid, "synthesize", "running", "正在生成更新清单与补丁清单…")
    await _set_step(
        sid,
        "synthesize",
        "done",
        f"已生成双 Markdown（模型 {result.get('model') or '—'}）",
    )
    await _set_step(sid, "complete", "running", "正在整理输出…")
    artifact = {
        "type": "digest_vibe_prep",
        "digest_id": int(digest_row.id),
        "digest_day": digest_row.day,
        "digest_subject": digest_row.subject,
        "vibe_prep": result,
        "updates_markdown": result.get("updates_markdown") or "",
        "patches_markdown": result.get("patches_markdown") or "",
        "completed_at": _facade().datetime.now(_facade().timezone.utc).isoformat() + "Z",
    }
    from modstore_server.digest_vibe_line_dispatch import (
        dispatch_vibe_prep_to_production_lines,
    )
    from modstore_server.digest_vibe_prep import persist_vibe_prep_on_digest_record

    persist_vibe_prep_on_digest_record(int(digest_row.id), result)
    dispatch_vibe_prep_to_production_lines(int(digest_row.id), result)
    await _finalize_session_done(sid, artifact)


class DigestLineExecuteDTO(_facade().BaseModel):
    """``POST .../daily-digests/{id}/line-execute`` 入参（Phase A 或单产线）。"""

    dispatch_line: str = _facade().Field(
        "PHASE-A",
        description="PHASE-A（默认，P-S+P-App 补丁）| P-W | P-S | P-App | S-R",
    )
    force: bool = _facade().Field(False, description="忽略同 base_version 幂等跳过")
    list_kinds: _facade().Optional[_facade().List[str]] = _facade().Field(
        None, description="默认 patches"
    )
    priorities: _facade().Optional[_facade().List[str]] = _facade().Field(
        None, description="如 P0,P1"
    )


@_facade().router.post("/daily-digests/{record_id}/line-execute")
async def butler_digest_line_execute(
    record_id: int,
    body: DigestLineExecuteDTO,
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
    db: _facade().Session = _facade().Depends(_facade().get_db),
):
    """Phase A：消费产线清单并向对应员工派发子任务（不跑 P3–P9）。"""
    if not getattr(user, "is_admin", False):
        raise _facade().HTTPException(403, "仅管理员可触发产线清单执行")
    row = db.get(_facade().DailyDigestRecord, record_id)
    if row is None:
        raise _facade().HTTPException(404, "每日摘要记录不存在")
    import asyncio

    line = str(body.dispatch_line or "PHASE-A").strip().upper().replace("_", "-")
    kinds = body.list_kinds if body.list_kinds else None
    prios = body.priorities if body.priorities else None
    force = bool(body.force)
    if line in ("PHASE-A", "PHASEA", "ALL", "*", ""):
        from modstore_server.digest_daily_line_chain import execute_phase_a_line_chain

        out = await asyncio.to_thread(execute_phase_a_line_chain, int(record_id), force=force)
        return {"success": bool(out.get("ok")), "data": out}
    if line not in ("P-W", "P-S", "P-APP", "S-R"):
        raise _facade().HTTPException(400, "dispatch_line 须为 PHASE-A / P-W / P-S / P-App / S-R")
    if line == "P-APP":
        line = "P-App"
    from modstore_server.digest_line_executor import execute_digest_line_work_units

    out = await asyncio.to_thread(
        execute_digest_line_work_units,
        int(record_id),
        dispatch_line=line,
        list_kinds=kinds,
        priorities=prios,
        mode="manual",
        force=force,
    )
    return {"success": bool(out.get("ok")), "data": out}


@_facade().router.post("/daily-digests/{record_id}/vibe-prep/sessions")
async def butler_digest_vibe_prep_session_start(
    record_id: int,
    body: DigestVibePrepDTO,
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
    db: _facade().Session = _facade().Depends(_facade().get_db),
):
    """基于某条每日摘要存档，生成 Vibe-Coding 预备 Markdown（更新 + 补丁）。"""
    if not getattr(user, "is_admin", False):
        raise _facade().HTTPException(403, "仅管理员可生成 Vibe 预备文档")
    row = db.get(_facade().DailyDigestRecord, record_id)
    if row is None:
        raise _facade().HTTPException(404, "每日摘要记录不存在")
    from modstore_server.workbench_api import (
        _SESSION_LOCK,
        WORKBENCH_SESSIONS,
        _persist_workbench_session_unlocked,
        _pipeline_task_failsafe,
    )

    sid = _facade().uuid.uuid4().hex[:24]
    mode = str(body.mode or "auto").strip().lower()
    if mode not in ("auto", "manual"):
        mode = "auto"
    payload = body.model_dump()
    async with _SESSION_LOCK:
        WORKBENCH_SESSIONS[sid] = {
            "id": sid,
            "user_id": user.id,
            "intent": "digest_vibe_prep",
            "status": "running",
            "steps": _facade()._vibe_prep_session_steps(),
            "planning_record": {
                "digest_id": record_id,
                "mode": mode,
                "max_employees": _facade().clamp_all_hands_max_employees(
                    body.max_employees, default=52
                ),
                "concurrency": int(body.concurrency or 2),
                "progress": {
                    "stage": "prepare",
                    "mode": mode,
                    "total": 0,
                    "completed": 0,
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
        _facade()._run_digest_vibe_prep_session(
            sid=sid, user_id=int(user.id), digest_row=row, payload=payload
        )
    )
    task.add_done_callback(_pipeline_task_failsafe(sid))
    return {"session_id": sid, "status": "running", "digest_id": record_id}
