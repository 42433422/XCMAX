"""把每日 loops 的员工工作产出汇报进「员工交流圈」collab feed。

设计要点（见计划 idempotent-dazzling-scroll）：
- collab feed 是单一真相源；loops **进程内**直接调 ``post_collab_message`` 投递（不走 HTTP）。
- 线程按部门常驻：6 个 ``SIX_LINE_DEPARTMENTS`` 部门各一条 + 1 条 ``company``（承载无员工
  归属的大会纪要 / 编排）。线程靠 ``title`` 精确匹配幂等查找/创建（不改 schema，alembic 断的）。
- 消息去重靠 ``payload_json`` 里的 ``report_key``（每源都有天然稳定键）。
- ``post_collab_message`` 在 ``mentions`` 非空时会自动派一条 ``collab_mention`` 建议，故这里
  **必须** ``mentions=[]``，避免汇报误派任务。
- 全部 best-effort：失败只记日志，绝不拖垮调用它的 loop；受 ``MODSTORE_COLLAB_REPORTER_ENABLED`` 开关控制。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

# 跨进程生命周期缓存 dept_key -> thread_id，省去重复查库。
_THREAD_CACHE: Dict[str, int] = {}

# 无员工归属的汇报（大会纪要 / 编排）统一进这条线程。
_COMPANY_KEY = "company"
_COMPANY_LABEL = "公司大会 / 编排"

_TITLE_PREFIX = "[员工交流圈]"


def _enabled() -> bool:
    raw = (os.environ.get("MODSTORE_COLLAB_REPORTER_ENABLED", "1") or "").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _excerpt(text: str, limit: int = 3000) -> str:
    s = str(text or "").strip()
    return s if len(s) <= limit else (s[: limit - 1] + "…")


# ── 部门解析 ───────────────────────────────────────────────────────────────

_DEPT_LABELS: Dict[str, str] = {}
_EMP_TO_DEPT: Dict[str, str] = {}


def _build_dept_index() -> None:
    """从 ``SIX_LINE_DEPARTMENTS`` 构建 dept 标签表 + 员工→部门反查表（按插入序首个命中）。"""
    if _EMP_TO_DEPT:
        return
    from modstore_server.duty_roster import SIX_LINE_DEPARTMENTS

    for dept_key, block in SIX_LINE_DEPARTMENTS.items():
        _DEPT_LABELS[dept_key] = str(block.get("label") or dept_key)
        subzones = block.get("subzones") or {}
        for zone in subzones.values():
            for eid in zone.get("ids") or []:
                _EMP_TO_DEPT.setdefault(str(eid), dept_key)
    _DEPT_LABELS[_COMPANY_KEY] = _COMPANY_LABEL


def _dept_for_employee(employee_id: str) -> str:
    """员工所属部门 key；跨部门取插入序首个；未知/空 → ``company``。"""
    _build_dept_index()
    return _EMP_TO_DEPT.get(str(employee_id or "").strip(), _COMPANY_KEY)


def _dept_label(dept_key: str) -> str:
    _build_dept_index()
    return _DEPT_LABELS.get(dept_key, dept_key)


def _dept_members(dept_key: str) -> List[str]:
    if dept_key == _COMPANY_KEY:
        return []
    from modstore_server.duty_roster import SIX_LINE_DEPARTMENTS

    out: List[str] = []
    block = SIX_LINE_DEPARTMENTS.get(dept_key) or {}
    for zone in (block.get("subzones") or {}).values():
        for eid in zone.get("ids") or []:
            if eid not in out:
                out.append(str(eid))
    return out


def _stable_thread_title(dept_key: str) -> str:
    return f"{_TITLE_PREFIX} {_dept_label(dept_key)} · dept={dept_key}"


# ── 线程解析 + 去重 ─────────────────────────────────────────────────────────


def get_or_create_dept_thread(dept_key: str) -> Optional[int]:
    """幂等取/建部门常驻线程；返回 thread_id，失败返回 ``None``。"""
    cached = _THREAD_CACHE.get(dept_key)
    if cached:
        return cached
    title = _stable_thread_title(dept_key)
    try:
        from modstore_server.models import EmployeeCollabThread, get_session_factory

        sf = get_session_factory()
        with sf() as session:
            row = (
                session.query(EmployeeCollabThread)
                .filter(EmployeeCollabThread.title == title)
                .order_by(EmployeeCollabThread.id.asc())
                .first()
            )
            if row is not None:
                tid = int(row.id)
                _THREAD_CACHE[dept_key] = tid
                return tid
    except Exception:
        logger.exception("collab reporter: lookup dept thread failed dept=%s", dept_key)
        return None

    try:
        from modstore_server.employee_autonomy_service import create_collab_thread

        out = create_collab_thread(
            title=title,
            participants=_dept_members(dept_key),
            created_by_employee_id="collab-reporter",
            context={"kind": "dept_report_thread", "dept_key": dept_key},
            emit_event=False,  # 汇报线程不触发 incident 编排
        )
        if out.get("ok"):
            tid = int(out.get("thread_id") or 0)
            if tid > 0:
                _THREAD_CACHE[dept_key] = tid
                return tid
    except Exception:
        logger.exception("collab reporter: create dept thread failed dept=%s", dept_key)
    return None


def _already_reported(thread_id: int, report_key: str) -> bool:
    """同一 report_key 是否已在该线程投递过（payload_json LIKE 查重，方言安全）。"""
    if not report_key:
        return False
    try:
        from modstore_server.models import EmployeeCollabMessage, get_session_factory

        sf = get_session_factory()
        with sf() as session:
            # 匹配 JSON 编码后的带引号值，兼容紧凑/带空格两种分隔符。
            pattern = f'%"{report_key}"%'
            hit = (
                session.query(EmployeeCollabMessage.id)
                .filter(
                    EmployeeCollabMessage.thread_id == int(thread_id),
                    EmployeeCollabMessage.payload_json.like(pattern),
                )
                .first()
            )
            return hit is not None
    except Exception:
        logger.exception("collab reporter: dedupe check failed key=%s", report_key)
        return False


def _post_report(
    *,
    dept_key: str,
    sender_employee_id: str,
    report_key: str,
    source: str,
    markdown: str,
    payload_extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """解析线程 → 去重 → 投递一条汇报消息（best-effort）。"""
    if not _enabled():
        return {"ok": False, "skipped": True, "disabled": True}
    text = str(markdown or "").strip()
    if not text:
        return {"ok": False, "skipped": True, "error": "empty"}
    tid = get_or_create_dept_thread(dept_key)
    if not tid:
        return {"ok": False, "skipped": True, "error": "no_thread"}
    if _already_reported(tid, report_key):
        return {"ok": True, "skipped": True, "thread_id": tid}
    try:
        from modstore_server.employee_autonomy_service import post_collab_message

        payload: Dict[str, Any] = {"report_key": report_key, "source": source}
        if payload_extra:
            payload.update(payload_extra)
        out = post_collab_message(
            thread_id=tid,
            sender_employee_id=sender_employee_id or "system",
            content=text,
            mentions=[],  # 必须为空：非空会触发 collab_mention 建议自动派发
            payload=payload,
            emit_event=False,  # 汇报不触发 incident 编排/派单（避免高频放大）
        )
        return {
            "ok": bool(out.get("ok")),
            "skipped": False,
            "thread_id": tid,
            "message_id": out.get("message_id"),
            "error": out.get("error", ""),
        }
    except Exception:
        logger.exception("collab reporter: post failed key=%s dept=%s", report_key, dept_key)
        return {"ok": False, "skipped": False, "thread_id": tid, "error": "exception"}


# ── 6 类 loop 产出的汇报入口 ─────────────────────────────────────────────────


def report_meeting_minutes(*, record_id: int, day: str, minutes_html: str) -> Dict[str, Any]:
    """员工大会纪要 → company 线程，sender=meeting-chair。"""
    try:
        from modstore_server.daily_digest import _html_to_text_excerpt

        body = _html_to_text_excerpt(minutes_html or "")
    except Exception:
        body = str(minutes_html or "")
    body = _excerpt(body, 4000)
    if not body.strip():
        return {"ok": False, "skipped": True, "error": "empty_minutes"}
    md = f"📋 **每日员工大会纪要 · {day}**\n\n{body}"
    return _post_report(
        dept_key=_COMPANY_KEY,
        sender_employee_id="meeting-chair",
        report_key=f"minutes|{record_id}",
        source="meeting_minutes",
        markdown=md,
        payload_extra={"record_id": int(record_id), "day": str(day)},
    )


def report_action_items(*, day: str, record_id: int) -> Dict[str, Any]:
    """每日行动条目 → 按员工聚合，每员工一条汇总（sender=该员工，进其部门线程）。"""
    try:
        from modstore_server.digest_action_items import list_action_items

        items = list_action_items(day=day, record_id=record_id, limit=2000)
    except Exception:
        logger.exception("collab reporter: list_action_items failed day=%s rid=%s", day, record_id)
        return {"ok": False, "skipped": True, "error": "query_failed"}

    by_emp: Dict[str, List[Dict[str, Any]]] = {}
    labels: Dict[str, str] = {}
    for it in items:
        eid = str(it.get("employee_id") or "").strip()
        if not eid:
            continue
        by_emp.setdefault(eid, []).append(it)
        if it.get("employee_label"):
            labels.setdefault(eid, str(it.get("employee_label")))

    posted = 0
    skipped = 0
    for eid, rows in by_emp.items():
        lines: List[str] = []
        for it in rows[:40]:
            pri = str(it.get("priority") or "").strip() or "P?"
            kind = str(it.get("kind") or "").strip()
            txt = _excerpt(str(it.get("text") or ""), 200)
            lines.append(f"- **{pri}** [{kind}] {txt}")
        label = labels.get(eid, eid)
        md = f"🗂️ **{label} · 今日行动条目（{day}）** 共 {len(rows)} 项\n\n" + "\n".join(lines)
        res = _post_report(
            dept_key=_dept_for_employee(eid),
            sender_employee_id=eid,
            report_key=f"actions|{day}|{eid}",
            source="action_items",
            markdown=md,
            payload_extra={
                "day": str(day),
                "record_id": int(record_id),
                "count": len(rows),
            },
        )
        if res.get("skipped"):
            skipped += 1
        elif res.get("ok"):
            posted += 1
    return {"ok": True, "posted": posted, "skipped": skipped, "employees": len(by_emp)}


def report_brief_task(*, task_id: int) -> Dict[str, Any]:
    """自治任务完成（pending_brief_tasks 终态）。"""
    try:
        from modstore_server.models import PendingBriefTask, get_session_factory

        sf = get_session_factory()
        with sf() as session:
            row = session.get(PendingBriefTask, int(task_id))
            if row is None:
                return {"ok": False, "skipped": True, "error": "not_found"}
            status = str(row.status or "")
            if status not in ("done", "failed"):
                return {"ok": False, "skipped": True, "error": "not_terminal"}
            owner = str(row.owner_employee_id or "")
            brief = _excerpt(str(row.task_brief or ""), 600)
    except Exception:
        logger.exception("collab reporter: load brief task failed id=%s", task_id)
        return {"ok": False, "skipped": True, "error": "query_failed"}

    icon = "✅" if status == "done" else "❌"
    md = f"{icon} **自治任务{('完成' if status == 'done' else '失败')}**\n\n任务：{brief}"
    return _post_report(
        dept_key=_dept_for_employee(owner),
        sender_employee_id=owner,
        report_key=f"brief|{task_id}",
        source="brief_task",
        markdown=md,
        payload_extra={"task_id": int(task_id), "status": status},
    )


def report_suggestion_dispatched(*, suggestion_id: int) -> Dict[str, Any]:
    """员工建议已派发。"""
    try:
        from modstore_server.models import EmployeeSuggestion, get_session_factory

        sf = get_session_factory()
        with sf() as session:
            row = session.get(EmployeeSuggestion, int(suggestion_id))
            if row is None:
                return {"ok": False, "skipped": True, "error": "not_found"}
            source = str(row.source_employee_id or "")
            kind = str(row.kind or "general")
            summary = _excerpt(str(row.summary or ""), 600)
            targets_raw = str(row.target_employee_ids_json or "[]")
            status = str(row.status or "")
    except Exception:
        logger.exception("collab reporter: load suggestion failed id=%s", suggestion_id)
        return {"ok": False, "skipped": True, "error": "query_failed"}

    try:
        import json

        targets: Sequence[str] = json.loads(targets_raw) or []
    except Exception:
        targets = []
    tgt = "、".join(str(t) for t in targets) if targets else "—"
    md = f"💡 **员工建议已派发** · {kind}（{status}）\n\n{summary}\n\n目标员工：{tgt}"
    return _post_report(
        dept_key=_dept_for_employee(source),
        sender_employee_id=source,
        report_key=f"suggestion|{suggestion_id}",
        source="suggestion",
        markdown=md,
        payload_extra={
            "suggestion_id": int(suggestion_id),
            "kind": kind,
            "status": status,
        },
    )


def report_evolution(*, evolution_record_id: int) -> Dict[str, Any]:
    """员工进化记录（prompt 优化）。"""
    try:
        from modstore_server.models import EmployeeEvolutionRecord, get_session_factory

        sf = get_session_factory()
        with sf() as session:
            row = session.get(EmployeeEvolutionRecord, int(evolution_record_id))
            if row is None:
                return {"ok": False, "skipped": True, "error": "not_found"}
            emp = str(row.employee_id or "")
            fails = int(row.failure_count or 0)
            hours = int(row.lookback_hours or 24)
            status = str(row.status or "")
            diff = _excerpt(str(row.diff_explanation or ""), 1500)
    except Exception:
        logger.exception("collab reporter: load evolution failed id=%s", evolution_record_id)
        return {"ok": False, "skipped": True, "error": "query_failed"}

    md = (
        f"🧬 **员工进化** · 近 {hours}h 失败 {fails} 次（{status}）\n\n"
        f"{diff or '（无 diff 说明）'}"
    )
    return _post_report(
        dept_key=_dept_for_employee(emp),
        sender_employee_id=emp,
        report_key=f"evolution|{evolution_record_id}",
        source="evolution",
        markdown=md,
        payload_extra={
            "evolution_record_id": int(evolution_record_id),
            "status": status,
        },
    )


def report_staged_change(
    *, staged_id: int, branch: str, files: int, pr_url: str = ""
) -> Dict[str, Any]:
    """daily-orchestrator 的代码改动（staged change / PR）→ company 线程。"""
    md = f"🛠️ **daily-orchestrator 自动改动**\n\n" f"分支：`{branch}`\n变更文件：{int(files)} 个"
    if pr_url:
        md += f"\nPR：{pr_url}"
    return _post_report(
        dept_key=_COMPANY_KEY,
        sender_employee_id="daily-orchestrator",
        report_key=f"staged|{staged_id}",
        source="staged_change",
        markdown=md,
        payload_extra={
            "staged_id": int(staged_id),
            "branch": str(branch),
            "pr_url": str(pr_url),
        },
    )
