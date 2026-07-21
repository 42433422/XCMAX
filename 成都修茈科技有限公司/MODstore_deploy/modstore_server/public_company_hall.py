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
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DEPARTMENT_ORDER = (
    "ops_acquisition",
    "ops_partner",
    "prod_web",
    "prod_mod",
    "prod_software",
    "shared_retention",
)

DEPARTMENT_COLORS = {
    "ops_acquisition": "#22d3ee",
    "ops_partner": "#4ade80",
    "prod_web": "#fb923c",
    "prod_mod": "#a78bfa",
    "prod_software": "#facc15",
    "shared_retention": "#79c0ff",
}

_LINE_TO_DEPT = {
    "P-W": "prod_web",
    "P-S": "prod_software",
    "P-App": "prod_software",
    "P-M": "prod_mod",
    "S-R": "shared_retention",
    "O-A": "ops_acquisition",
    "O-B": "ops_partner",
}

_WORKING_STATUSES = frozenset({"open", "dispatched", "in_progress"})
_DONE_STATUSES = frozenset({"merged", "closed"})
_PATH_TICK = re.compile(r"`([^`]*/[^`]*)`")
_CODE_FENCE = re.compile(r"```[\s\S]*?```")


def _repo_root() -> Path:
    mono = (os.environ.get("XCMAX_MONOREPO_ROOT") or "").strip()
    if mono:
        return Path(mono).expanduser().resolve()
    return Path(__file__).resolve().parents[3]


def _clean(text: str, max_len: int = 120) -> str:
    s = str(text or "")
    s = _CODE_FENCE.sub("", s)
    s = _PATH_TICK.sub("", s)
    s = re.sub(r"\s+", " ", s).strip(" ·:-")
    if len(s) > max_len:
        s = s[: max_len - 1] + "…"
    return s


def _iso(dt: Any) -> Optional[str]:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    s = str(dt).strip()
    return s[:40] if s else None


def _dept_members() -> Dict[str, List[str]]:
    from modstore_server.duty_roster import SIX_LINE_DEPARTMENTS

    out: Dict[str, List[str]] = {}
    for dept_id in DEPARTMENT_ORDER:
        block = SIX_LINE_DEPARTMENTS.get(dept_id) or {}
        subzones = block.get("subzones") if isinstance(block.get("subzones"), dict) else {}
        ids: List[str] = []
        seen: set[str] = set()
        for sz in subzones.values():
            if not isinstance(sz, dict):
                continue
            for eid in sz.get("ids") or []:
                e = str(eid or "").strip()
                if not e or e in seen:
                    continue
                seen.add(e)
                ids.append(e)
        out[dept_id] = ids
    return out


def _primary_dept_map(members: Dict[str, List[str]]) -> Dict[str, str]:
    primary: Dict[str, str] = {}
    for dept_id in DEPARTMENT_ORDER:
        for eid in members.get(dept_id) or []:
            primary.setdefault(eid, dept_id)
    return primary


def _catalog_names(employee_ids: List[str]) -> Dict[str, str]:
    names: Dict[str, str] = {}
    if not employee_ids:
        return names
    try:
        from modstore_server.models import CatalogItem, get_session_factory

        sf = get_session_factory()
        with sf() as session:
            rows = (
                session.query(CatalogItem.pkg_id, CatalogItem.name)
                .filter(CatalogItem.pkg_id.in_(employee_ids))
                .all()
            )
            for pkg_id, name in rows:
                eid = str(pkg_id or "").strip()
                label = str(name or "").strip()
                if eid and label:
                    names[eid] = label[:64]
    except Exception:
        logger.exception("company_hall: catalog names failed")
    return names


def _action_signals(day: Optional[str]) -> Dict[str, Dict[str, Any]]:
    """employee_id -> open counts / titles / priorities from action items."""
    from modstore_server.digest_action_items import latest_day, list_action_items

    use_day = day or latest_day() or None
    items = list_action_items(day=use_day, limit=2000) if use_day else list_action_items(limit=2000)
    by: Dict[str, Dict[str, Any]] = {}
    for it in items:
        eid = str(it.get("employee_id") or "").strip()
        if not eid:
            continue
        slot = by.setdefault(
            eid,
            {
                "open": 0,
                "in_progress": 0,
                "p0_open": 0,
                "titles": [],
                "statuses": [],
                "updated_at": None,
                "day": str(it.get("day") or use_day or ""),
            },
        )
        st = str(it.get("status") or "open")
        if st in _WORKING_STATUSES:
            slot["open"] += 1
            if st == "in_progress":
                slot["in_progress"] += 1
            if str(it.get("priority") or "") == "P0":
                slot["p0_open"] += 1
            title = _clean(str(it.get("text") or ""), 72)
            if title and len(slot["titles"]) < 3:
                slot["titles"].append(title)
            slot["statuses"].append(st)
        ua = str(it.get("updated_at") or it.get("created_at") or "")
        if ua and (not slot["updated_at"] or ua > str(slot["updated_at"])):
            slot["updated_at"] = ua
    return by


def _metric_signals(employee_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """Recent execution metrics (24h window)."""
    out: Dict[str, Dict[str, Any]] = {}
    if not employee_ids:
        return out
    try:
        from modstore_server.models import EmployeeExecutionMetric, get_session_factory

        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        sf = get_session_factory()
        with sf() as session:
            rows = (
                session.query(EmployeeExecutionMetric)
                .filter(
                    EmployeeExecutionMetric.employee_id.in_(employee_ids),
                    EmployeeExecutionMetric.created_at >= cutoff,
                )
                .order_by(EmployeeExecutionMetric.created_at.desc())
                .limit(500)
                .all()
            )
        for m in rows:
            eid = str(m.employee_id or "").strip()
            if not eid:
                continue
            slot = out.setdefault(
                eid,
                {
                    "last_status": None,
                    "last_task": None,
                    "last_at": None,
                    "runs_24h": 0,
                    "fail_24h": 0,
                },
            )
            slot["runs_24h"] += 1
            st = str(m.status or "")
            if st and st != "success":
                slot["fail_24h"] += 1
            if slot["last_at"] is None:
                slot["last_status"] = st
                slot["last_task"] = _clean(str(m.task or ""), 80)
                slot["last_at"] = _iso(m.created_at)
    except Exception:
        logger.exception("company_hall: metric signals failed")
    return out


def _presence_for(
    *,
    eid: str,
    action: Dict[str, Any],
    metric: Dict[str, Any],
) -> Tuple[str, str]:
    """Return (presence, activity_label).

    working | alert | idle
    （编制内全员至少 idle=编制待命；不做虚构 online/offline 心跳）
    """
    open_n = int(action.get("open") or 0)
    p0 = int(action.get("p0_open") or 0)
    fail = int(metric.get("fail_24h") or 0)
    last_status = str(metric.get("last_status") or "")
    titles = action.get("titles") or []

    if p0 > 0 or fail >= 2 or last_status in {"failed", "error", "fail"}:
        label = titles[0] if titles else (metric.get("last_task") or "近期执行异常")
        return "alert", str(label)

    if open_n > 0 or int(action.get("in_progress") or 0) > 0:
        label = titles[0] if titles else "处理公开行动条目中"
        return "working", str(label)

    # recent successful work within 2h → still working signal from metrics
    last_at = metric.get("last_at")
    if last_at and last_status == "success":
        try:
            dt = datetime.fromisoformat(str(last_at).replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - dt <= timedelta(hours=2):
                return "working", str(metric.get("last_task") or "近期刚完成执行")
        except Exception:
            pass

    if metric.get("last_task"):
        return "idle", f"待命 · 最近：{metric['last_task']}"
    return "idle", "编制待命"


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
    for dept_id in DEPARTMENT_ORDER:
        block = SIX_LINE_DEPARTMENTS.get(dept_id) or {}
        ids = members.get(dept_id) or []
        emps = [by_emp[i] for i in ids if i in by_emp]
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
        feed.append(
            {
                "ts": t.get("ts") or "—",
                "day": t.get("day") or board.get("day"),
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
                "text": t.get("title") or t.get("text") or "",
                "href": t.get("href") or "/world-will",
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
        feed.append(
            {
                "ts": (str(met.get("last_at") or "")[11:16] if met.get("last_at") else "—"),
                "day": board.get("day"),
                "employee_id": eid,
                "employee_name": emp.get("name") or eid,
                "dept_id": emp.get("dept_id") or "",
                "dept_label": emp.get("dept_label") or "",
                "dept_color": emp.get("dept_color") or "#94a3b8",
                "presence": mood if mood == "alert" else emp.get("presence") or "idle",
                "status": met.get("last_status"),
                "status_label": "执行失败" if mood == "alert" else "最近执行",
                "text": met.get("last_task"),
                "href": "/world-will",
                "source": "execution_metric",
            }
        )

    feed = feed[:40]

    busiest = None
    if departments:
        busiest = max(
            departments,
            key=lambda d: int((d.get("counts") or {}).get("working") or 0)
            + int((d.get("counts") or {}).get("alert") or 0),
        )
    mvp = None
    if employees:
        mvp = max(
            employees,
            key=lambda e: int(e.get("open_action_items") or 0) * 10
            + int(e.get("in_progress_action_items") or 0) * 20
            + int(e.get("runs_24h") or 0),
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

    return {
        "schema": "xcagi.public_company_hall/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "day": board.get("day"),
        "readonly": True,
        "note": "公司大厅公开投影：编制为 SSOT；状态由行动条目与执行度量推导，无虚构心跳在线。",
        "cadence": {
            "mode": "event_driven",
            "label": "事件驱动刷新（digest / 派发 / 部署回写后更新快照）",
            "next_window": "通常每日 08:00–08:30 晨报编排窗口（以调度实际触发为准）",
        },
        "presence_model": {
            "working": "有未闭环行动条目，或 2h 内有成功执行",
            "alert": "有未闭环 P0，或 24h 内多次执行失败",
            "idle": "编制内注册、当日无公开活跃任务；含按需触发岗位（非离线）",
        },
        "counts": counts,
        "departments": departments,
        "employees": employees,
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
    for raw in ("/root/成都修茈科技有限公司", "/opt/xcmax/current/成都修茈科技有限公司"):
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
    return {"ok": True, "day": payload.get("day"), "written": written, "payload": payload}
