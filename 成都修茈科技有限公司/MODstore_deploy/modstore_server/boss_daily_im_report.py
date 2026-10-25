"""每日 IM 主动工作汇报（员工团队 → 老板手机）。

邮件版每日摘要（daily_digest）之外的 IM 触点：每天定时把过去 24h 的
员工工作账本汇总成一条人话消息，以「数字管家」员工身份主动推到老板 IM
（复用 ``employee_im_bridge.notify_boss`` → FHD → WS/离线推送 → 手机）。

老板不用翻邮件、不用开管理台，每天在 IM 里就能看到：
谁干了多少活、成没成、有没有问题在等自己回复。

env：
    MODSTORE_BOSS_IM_REPORT_ENABLED     默认 1；0 关闭
    MODSTORE_BOSS_IM_REPORT_HOUR_UTC    默认 1（=北京 09:00）
    MODSTORE_BOSS_IM_REPORT_EMPLOYEE_ID 默认 xc-digital-butler（数字管家）
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List, Tuple

from modstore_server.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_DEFAULT_REPORTER_EMPLOYEE_ID = "xc-digital-butler"
_DEFAULT_REPORTER_DISPLAY_NAME = "数字管家"


def report_enabled() -> bool:
    return (os.environ.get("MODSTORE_BOSS_IM_REPORT_ENABLED") or "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )


def report_hour_utc() -> int:
    raw = (os.environ.get("MODSTORE_BOSS_IM_REPORT_HOUR_UTC") or "1").strip()
    try:
        return min(23, max(0, int(raw)))
    except ValueError:
        return 1


def _reporter_identity() -> Tuple[str, str]:
    eid = (
        os.environ.get("MODSTORE_BOSS_IM_REPORT_EMPLOYEE_ID") or _DEFAULT_REPORTER_EMPLOYEE_ID
    ).strip()
    return eid or _DEFAULT_REPORTER_EMPLOYEE_ID, _DEFAULT_REPORTER_DISPLAY_NAME


def _collect_stats(hours: int = 24) -> Dict[str, Any]:
    """过去 ``hours`` 小时的员工工作账本（全部 best-effort，单项失败不拖垮汇报）。"""
    from sqlalchemy import func

    from modstore_server.models import (
        EmployeeExecutionMetric,
        EmployeeSuggestion,
        PendingBriefTask,
        PendingHumanQuestion,
        get_session_factory,
    )

    since = datetime.now(UTC) - timedelta(hours=max(1, int(hours)))
    stats: Dict[str, Any] = {
        "since": since,
        "runs_total": 0,
        "runs_success": 0,
        "top_employees": [],
        "tasks_done": 0,
        "tasks_failed": 0,
        "tasks_pending": 0,
        "boss_im_done": 0,
        "suggestions_dispatched": 0,
        "questions_pending": 0,
    }
    sf = get_session_factory()
    with sf() as session:
        try:
            rows = (
                session.query(
                    EmployeeExecutionMetric.employee_id,
                    EmployeeExecutionMetric.status,
                    func.count(EmployeeExecutionMetric.id),
                )
                .filter(EmployeeExecutionMetric.created_at >= since)
                .group_by(EmployeeExecutionMetric.employee_id, EmployeeExecutionMetric.status)
                .all()
            )
            per_emp: Dict[str, int] = {}
            for emp, status, cnt in rows:
                stats["runs_total"] += int(cnt)
                if str(status or "") == "success":
                    stats["runs_success"] += int(cnt)
                per_emp[str(emp)] = per_emp.get(str(emp), 0) + int(cnt)
            stats["top_employees"] = sorted(per_emp.items(), key=lambda kv: -kv[1])[:3]
        except RECOVERABLE_ERRORS:
            logger.debug("boss daily report: execution metrics query failed", exc_info=True)

        try:
            trows = (
                session.query(
                    PendingBriefTask.status,
                    PendingBriefTask.source_kind,
                    func.count(PendingBriefTask.id),
                )
                .filter(PendingBriefTask.created_at >= since)
                .group_by(PendingBriefTask.status, PendingBriefTask.source_kind)
                .all()
            )
            for status, source_kind, cnt in trows:
                st = str(status or "")
                if st == "done":
                    stats["tasks_done"] += int(cnt)
                    if str(source_kind or "") == "boss_im":
                        stats["boss_im_done"] += int(cnt)
                elif st == "failed":
                    stats["tasks_failed"] += int(cnt)
                elif st in ("pending", "running"):
                    stats["tasks_pending"] += int(cnt)
        except RECOVERABLE_ERRORS:
            logger.debug("boss daily report: brief task query failed", exc_info=True)

        try:
            stats["suggestions_dispatched"] = int(
                session.query(func.count(EmployeeSuggestion.id))
                .filter(
                    EmployeeSuggestion.updated_at >= since,
                    EmployeeSuggestion.status == "dispatched",
                )
                .scalar()
                or 0
            )
        except RECOVERABLE_ERRORS:
            logger.debug("boss daily report: suggestion query failed", exc_info=True)

        try:
            stats["questions_pending"] = int(
                session.query(func.count(PendingHumanQuestion.id))
                .filter(PendingHumanQuestion.status == "pending")
                .scalar()
                or 0
            )
        except RECOVERABLE_ERRORS:
            logger.debug("boss daily report: pending question query failed", exc_info=True)
    return stats


def build_boss_daily_im_report(*, hours: int = 24) -> str:
    """把账本拼成一条老板一眼能读完的 IM 消息。"""
    s = _collect_stats(hours=hours)
    lines: List[str] = ["📋 员工团队日报（过去 24 小时）", ""]

    if s["runs_total"] > 0:
        lines.append(f"· 员工执行 {s['runs_total']} 次，成功 {s['runs_success']} 次")
        if s["top_employees"]:
            tops = "、".join(f"{eid}（{cnt} 次）" for eid, cnt in s["top_employees"])
            lines.append(f"· 最勤快：{tops}")
    else:
        lines.append("· 过去 24 小时没有员工执行记录")

    task_bits: List[str] = []
    if s["tasks_done"]:
        task_bits.append(f"完成 {s['tasks_done']}")
    if s["tasks_failed"]:
        task_bits.append(f"失败 {s['tasks_failed']}")
    if s["tasks_pending"]:
        task_bits.append(f"待办 {s['tasks_pending']}")
    if task_bits:
        line = "· 任务队列：" + "，".join(task_bits)
        if s["boss_im_done"]:
            line += f"（含你 IM 派的 {s['boss_im_done']} 条）"
        lines.append(line)
    if s["suggestions_dispatched"]:
        lines.append(f"· 员工建议已自动执行 {s['suggestions_dispatched']} 条")

    if s["questions_pending"]:
        lines.append(f"⚠️ 有 {s['questions_pending']} 个问题在等你回复（直接回对应员工的聊天即可）")
    else:
        lines.append("· 没有等你拍板的问题")

    lines.append("")
    lines.append("需要谁干活，直接在 IM 里对他说就行。")
    return "\n".join(lines)


def send_boss_daily_im_report() -> Dict[str, Any]:
    """构建并推送日报到老板 IM。返回 ``{ok, sent, skipped_reason?}``，不抛错。"""
    if not report_enabled():
        return {"ok": True, "sent": False, "skipped_reason": "disabled"}
    try:
        from modstore_server.employee_im_bridge import notify_boss

        body = build_boss_daily_im_report()
        eid, display = _reporter_identity()
        sent = notify_boss(eid, body=body, hook="daily_report", display_name=display)
        if not sent:
            logger.info("boss daily im report not sent（IM 桥未配或推送失败）")
        return {"ok": True, "sent": bool(sent)}
    except BOUNDARY_ERRORS as exc:  # noqa: BLE001 - 调度任务不允许抛错打断调度器
        logger.exception("boss daily im report failed")
        return {"ok": False, "sent": False, "error": str(exc)[:500]}


__all__ = [
    "build_boss_daily_im_report",
    "report_enabled",
    "report_hour_utc",
    "send_boss_daily_im_report",
]
