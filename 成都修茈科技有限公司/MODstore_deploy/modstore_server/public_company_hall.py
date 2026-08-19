"""官网「世界意志」公司大厅公开投影（只读、脱敏）。

数据源（均为真实、可复核）：
- 编制：``duty_roster.SIX_LINE_DEPARTMENTS``（约 55 人）
- 中文名：CatalogItem.name（无则回退 employee_id）
- 状态：daily_action_items + EmployeeExecutionMetric（无心跳协议，由任务/执行痕迹推导）
- 动态：公开行动板 trajectory + 近 24h 执行摘要

写出：``/download-company-hall.json``；digest / 状态回写后刷新。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from modstore_server.public_company_hall_config import (
    DEPARTMENT_COLORS as DEPARTMENT_COLORS,
    DEPARTMENT_ORDER as DEPARTMENT_ORDER,
    LINE_TO_DEPT as _LINE_TO_DEPT,
    WORKING_STATUSES as _WORKING_STATUSES,
)
from modstore_server.public_company_hall_signals import (
    _action_signals as _action_signals,
    _catalog_names as _catalog_names,
    _dept_members as _dept_members,
    _load_published_action_board as _load_published_action_board,
    _metric_signals as _metric_signals,
    _presence_for as _presence_for,
    _primary_dept_map as _primary_dept_map,
    _repo_root as _repo_root,
)
from modstore_server.public_company_hall_text import (
    _clean as _clean,
    _feed_occurred_at as _feed_occurred_at,
    _public_ai_driver_snapshot as _public_ai_driver_snapshot,
    _publicize_feed_text as _publicize_feed_text,
    _sort_feed as _sort_feed,
)

logger = logging.getLogger(__name__)


def build_public_company_hall(*, day: Optional[str] = None) -> Dict[str, Any]:
    from modstore_server.duty_roster import SIX_LINE_DEPARTMENTS
    from modstore_server.public_action_board import build_public_action_board

    members = _dept_members()
    primary = _primary_dept_map(members)
    all_ids = sorted(primary.keys())
    names = _catalog_names(all_ids)
    actions = _action_signals(day)
    metrics = _metric_signals(all_ids)

    employees: List[Dict[str, Any]] = []
    counts = {"working": 0, "alert": 0, "idle": 0, "roster": len(all_ids)}

    for eid in all_ids:
        act = actions.get(eid) or {}
        met = metrics.get(eid) or {}
        presence, activity = _presence_for(eid=eid, action=act, metric=met)
        counts[presence] = int(counts.get(presence) or 0) + 1
        dept_id = primary.get(eid) or "prod_software"
        dept = SIX_LINE_DEPARTMENTS.get(dept_id) or {}
        employees.append(
            {
                "employee_id": eid,
                "name": names.get(eid) or eid,
                "dept_id": dept_id,
                "dept_label": str(dept.get("label") or dept_id),
                "dept_color": DEPARTMENT_COLORS.get(dept_id, "#79c0ff"),
                "presence": presence,
                "activity": activity,
                "open_action_items": int(act.get("open") or 0),
                "in_progress_action_items": int(act.get("in_progress") or 0),
                "last_activity_at": act.get("updated_at") or met.get("last_at"),
                "runs_24h": int(met.get("runs_24h") or 0),
            }
        )

    departments: List[Dict[str, Any]] = []
    by_emp = {e["employee_id"]: e for e in employees}
    # 部门卡只计主属部门，避免跨线兼职把 55 编制加总成 70+、状态重复计数。
    for dept_id in DEPARTMENT_ORDER:
        block = SIX_LINE_DEPARTMENTS.get(dept_id) or {}
        emps = [e for e in employees if e.get("dept_id") == dept_id]
        dc = {"working": 0, "alert": 0, "idle": 0}
        for e in emps:
            dc[e["presence"]] = int(dc.get(e["presence"]) or 0) + 1
        departments.append(
            {
                "id": dept_id,
                "label": str(block.get("label") or dept_id),
                "color": DEPARTMENT_COLORS.get(dept_id, "#79c0ff"),
                "employee_count": len(emps),
                "counts": dc,
                "employees": emps,
            }
        )

    board = build_public_action_board(day=day)
    board_empty = not (
        board.get("trajectory")
        or ((board.get("breakpoints") or {}).get("items"))
        or ((board.get("goals") or {}).get("items"))
    )
    if board_empty:
        published = _load_published_action_board()
        if published:
            board = published
            cal = board.get("calendar_day") or board.get("day")
            # 公开板可能粘旧日：抬升 day_stale，顶层 day 仍暴露事实并附 calendar_day
            if not board.get("calendar_day"):
                try:
                    from modstore_server.public_action_board import _calendar_today

                    board["calendar_day"] = _calendar_today()
                except Exception:  # noqa: BLE001
                    board["calendar_day"] = cal
            if (
                board.get("day")
                and board.get("calendar_day")
                and board["day"] != board["calendar_day"]
            ):
                board["day_stale"] = True
            logger.info(
                "company_hall: DB action board empty; using published download-action-board.json day=%s stale=%s",
                board.get("day"),
                board.get("day_stale"),
            )

    # DB 无行动信号时，用公开板条目推导 working/alert（与轨迹同源，不造假心跳）
    if not any(int((actions.get(eid) or {}).get("open") or 0) for eid in all_ids):
        name_to_id = {str(e.get("name") or ""): e["employee_id"] for e in employees}
        changed = False
        for it in (
            list(((board.get("breakpoints") or {}).get("items") or []))
            + list(((board.get("goals") or {}).get("items") or []))
            + list(board.get("trajectory") or [])
        ):
            eid = str(it.get("employee_id") or "").strip()
            if not eid:
                eid = name_to_id.get(str(it.get("owner") or "").strip(), "")
            emp = by_emp.get(eid)
            if not emp:
                continue
            st = str(it.get("status") or "")
            pri = str(it.get("priority") or "").upper()
            title = str(it.get("title") or it.get("text") or "")
            if st in {"merged", "closed", "done", "resolved"}:
                continue
            if pri == "P0" or title.startswith("P0") or st == "blocked":
                if emp.get("presence") != "alert":
                    emp["presence"] = "alert"
                    emp["activity"] = title or emp.get("activity")
                    changed = True
            elif st in _WORKING_STATUSES or st in {"open", "todo", "pending"}:
                if emp.get("presence") == "idle":
                    emp["presence"] = "working"
                    emp["activity"] = title or emp.get("activity")
                    changed = True
        if changed:
            counts = {"working": 0, "alert": 0, "idle": 0, "roster": len(employees)}
            for e in employees:
                counts[e["presence"]] = int(counts.get(e["presence"]) or 0) + 1
            for d in departments:
                dc = {"working": 0, "alert": 0, "idle": 0}
                for e in d.get("employees") or []:
                    dc[e["presence"]] = int(dc.get(e["presence"]) or 0) + 1
                d["counts"] = dc

    feed: List[Dict[str, Any]] = []
    for t in board.get("trajectory") or []:
        owner = str(t.get("owner") or "")
        eid = str(t.get("employee_id") or "")
        if not eid:
            # match by Chinese name
            for e in employees:
                if e["name"] == owner:
                    eid = e["employee_id"]
                    break
        emp = by_emp.get(eid) or {}
        occurred_at = _feed_occurred_at(
            raw=t.get("updated_at"),
            day=t.get("day") or board.get("day"),
            clock=t.get("ts"),
        )
        summary, detail = _publicize_feed_text(str(t.get("title") or t.get("text") or ""))
        href = str(t.get("href") or "").strip()
        if href in {"", "/", "/world-will", "/world-will.html"}:
            href = ""
        feed.append(
            {
                "ts": t.get("ts") or "—",
                "day": t.get("day") or board.get("day"),
                "occurred_at": occurred_at,
                "employee_id": eid,
                "employee_name": emp.get("name") or owner or "AI 员工",
                "dept_id": emp.get("dept_id") or _LINE_TO_DEPT.get(str(t.get("line") or ""), ""),
                "dept_label": emp.get("dept_label") or t.get("line_label") or "",
                "dept_color": emp.get("dept_color")
                or DEPARTMENT_COLORS.get(
                    _LINE_TO_DEPT.get(str(t.get("line") or ""), ""), "#94a3b8"
                ),
                "presence": emp.get("presence")
                or ("working" if t.get("status") in _WORKING_STATUSES else "idle"),
                "status": t.get("status"),
                "status_label": t.get("status_label"),
                "text": summary,
                "detail": detail,
                "href": href,
                "source": "action_board",
            }
        )

    # append metric-only recent successes/fails not already covered (cap)
    for eid, met in metrics.items():
        if not met.get("last_at") or not met.get("last_task"):
            continue
        if any(f.get("employee_id") == eid and f.get("source") == "action_board" for f in feed):
            continue
        emp = by_emp.get(eid) or {}
        mood = "alert" if str(met.get("last_status")) != "success" else "idle"
        occurred_at = _feed_occurred_at(raw=met.get("last_at"))
        raw_task = str(met.get("last_task") or "")
        summary, detail = _publicize_feed_text(raw_task)
        feed.append(
            {
                "ts": (occurred_at[11:16] if occurred_at else "—"),
                "day": (occurred_at[:10] if occurred_at else board.get("day")),
                "occurred_at": occurred_at,
                "employee_id": eid,
                "employee_name": emp.get("name") or eid,
                "dept_id": emp.get("dept_id") or "",
                "dept_label": emp.get("dept_label") or "",
                "dept_color": emp.get("dept_color") or "#94a3b8",
                "presence": mood if mood == "alert" else emp.get("presence") or "idle",
                "status": met.get("last_status"),
                "status_label": "执行失败" if mood == "alert" else "最近执行",
                "text": summary,
                "detail": detail,
                # 执行指标 task 列为 VARCHAR(128)，入库即截断；官网只能展示摘要
                "detail_truncated": True,
                "href": "",
                "source": "execution_metric",
            }
        )

    feed = _sort_feed(feed)[:40]

    busiest = None
    if departments:
        busiest = max(
            departments,
            key=lambda d: (
                int((d.get("counts") or {}).get("working") or 0)
                + int((d.get("counts") or {}).get("alert") or 0)
            ),
        )
    mvp = None
    if employees:
        mvp = max(
            employees,
            key=lambda e: (
                int(e.get("open_action_items") or 0) * 10
                + int(e.get("in_progress_action_items") or 0) * 20
                + int(e.get("runs_24h") or 0)
            ),
        )

    last_activity = None
    if feed:
        f0 = feed[0]
        last_activity = {
            "ts": f0.get("ts"),
            "day": f0.get("day") or board.get("day"),
            "employee_name": f0.get("employee_name"),
            "text": f0.get("text"),
            "source": f0.get("source"),
        }
    bp_items = list(((board.get("breakpoints") or {}).get("items") or [])[:12])
    goal_items = list(((board.get("goals") or {}).get("items") or [])[:12])

    try:
        from modstore_server.runtime_inventory import runtime_inventory_summary

        runtime = runtime_inventory_summary()
    except Exception as exc:  # noqa: BLE001
        logger.warning("company_hall: runtime inventory unavailable: %s", exc)
        runtime = {
            "schema": "xcagi.runtime_inventory/v1",
            "ok": False,
            "failed_must_run": -1,
            "note": f"runtime inventory unavailable: {exc}",
        }

    return {
        "schema": "xcagi.public_company_hall/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "day": board.get("day"),
        "calendar_day": board.get("calendar_day"),
        "day_stale": bool(board.get("day_stale")),
        "readonly": True,
        "note": "公司大厅公开投影：编制为 SSOT；状态由行动条目与执行度量推导，无虚构心跳在线。",
        "cadence": {
            "mode": "event_driven",
            "label": "事件驱动刷新（digest / 派发 / 部署回写后更新快照）",
            "next_window": "通常每日 08:00–08:30 晨报编排窗口（以调度实际触发为准）",
        },
        "presence_model": {
            "working": "有未闭环行动条目，或 2h 内有成功执行",
            "alert": "有未闭环 P0，或 24h 内多次失败且最近一跑仍不健康（不含 burn-in）",
            "idle": "编制内注册、当日无公开活跃任务；含按需触发岗位（非离线）",
        },
        "counts": counts,
        "departments": departments,
        "employees": employees,
        "ai_driver": _public_ai_driver_snapshot(),
        "runtime": runtime,
        "feed": feed,
        "last_activity": last_activity,
        "board": {
            "breakpoints_total": int(
                ((board.get("breakpoints") or {}).get("summary") or {}).get("total") or 0
            ),
            "goals_total": int(((board.get("goals") or {}).get("summary") or {}).get("total") or 0),
            "trajectory_total": len(board.get("trajectory") or []),
            "breakpoints": bp_items,
            "goals": goal_items,
        },
        "report": {
            "busiest_dept": (
                {
                    "id": (busiest or {}).get("id"),
                    "label": (busiest or {}).get("label"),
                    "working": int(((busiest or {}).get("counts") or {}).get("working") or 0),
                    "alert": int(((busiest or {}).get("counts") or {}).get("alert") or 0),
                }
                if busiest
                else None
            ),
            "mvp": (
                {
                    "employee_id": (mvp or {}).get("employee_id"),
                    "name": (mvp or {}).get("name"),
                    "open_action_items": int((mvp or {}).get("open_action_items") or 0),
                    "runs_24h": int((mvp or {}).get("runs_24h") or 0),
                }
                if mvp
                else None
            ),
        },
    }


def public_hall_targets() -> List[Path]:
    isolated_output = (os.environ.get("MODSTORE_PUBLIC_OUTPUT_ROOT") or "").strip()
    if isolated_output:
        return [Path(isolated_output).expanduser().resolve() / "download-company-hall.json"]
    root = _repo_root()
    targets = [
        root / "成都修茈科技有限公司" / "download-company-hall.json",
        root
        / "成都修茈科技有限公司"
        / "MODstore_deploy"
        / "market"
        / "public"
        / "download-company-hall.json",
    ]
    for raw in (
        "/root/成都修茈科技有限公司",
        "/opt/xcmax/current/成都修茈科技有限公司",
    ):
        try:
            live = Path(raw)
            if live.is_dir():
                targets.append(live.resolve() / "download-company-hall.json")
        except OSError:
            pass
    seen: set[str] = set()
    uniq: List[Path] = []
    for t in targets:
        k = str(t)
        if k in seen:
            continue
        seen.add(k)
        uniq.append(t)
    return uniq


def write_public_company_hall(*, day: Optional[str] = None) -> Dict[str, Any]:
    try:
        payload = build_public_company_hall(day=day)
    except Exception as exc:
        logger.exception("public_company_hall: build failed")
        return {"ok": False, "error": str(exc), "written": []}

    body = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    written: List[str] = []
    for tgt in public_hall_targets():
        try:
            if not tgt.parent.is_dir():
                continue
            tgt.write_text(body, encoding="utf-8")
            written.append(str(tgt))
        except Exception:
            logger.exception("public_company_hall: write failed %s", tgt)
    logger.info(
        "public_company_hall: day=%s roster=%s working=%s alert=%s written=%s",
        payload.get("day"),
        (payload.get("counts") or {}).get("roster"),
        (payload.get("counts") or {}).get("working"),
        (payload.get("counts") or {}).get("alert"),
        len(written),
    )
    return {
        "ok": True,
        "day": payload.get("day"),
        "written": written,
        "payload": payload,
    }
