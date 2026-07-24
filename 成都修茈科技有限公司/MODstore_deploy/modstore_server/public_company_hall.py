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
# 公开动态勿直接泄漏内部角色提示 / 执行 SOP
_ROLE_PROMPT = re.compile(r"(?:^|[。；;\n])\s*你是[^。\n]{2,120}。[ \t]*")
_INSTRUCTION_BOILERPLATE = re.compile(
    r"(?:回复必须说人话|先给结论/?状态|再说下一步|输出采用 JSON|不要泄露提示词|"
    r"不要直接倾倒|不要输出内部|内部字段或英文模板|你的任务是|"
    r"SYSTEM[_ ]?PROMPT|作为[^。\n]{0,40}助手)[^。；;\n]{0,200}[。；;\n]?"
)
_META_KV = re.compile(
    r"(?:执行模式|风险级别|事件类型|输出采用|必须使用|验收回执|"
    r"问题摘要|任务摘要|岗位任务)[^。；;\n]{0,120}[。；;]?"
)
_TASK_FIELD = re.compile(
    r"(?:岗位任务|问题摘要|任务摘要|公开摘要)[:：]\s*"
    r"(.+?)(?=\s*(?:执行模式|风险级别|事件类型|验收回执|必须使用|输出采用|回复必须)[:：]|\s*[。\n]|$)"
)
_EVENT_TOKEN = re.compile(r"^[a-z][a-z0-9_.-]{2,64}$")
_PROMPT_LEAK = re.compile(
    r"(?:你是|回复必须说人话|系统提示|SYSTEM[_ ]?PROMPT|事故处理小组的\s*scout|"
    r"不要直接倾倒|你的任务是|内部字段或英文模板)",
    re.I,
)


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


def _looks_like_prompt_leak(text: str) -> bool:
    s = str(text or "").strip().strip("。；;·:- ")
    if not s:
        return False
    if _PROMPT_LEAK.search(s):
        return True
    if _EVENT_TOKEN.fullmatch(s):
        # 仅剩事件代号（如 ops.incident.email）也不适合直接展示
        return True
    # 「问题摘要：ops.xxx」这类元数据残片
    if re.fullmatch(
        r"(?:问题摘要|任务摘要|岗位任务|事件类型)[:：]\s*[a-z][a-z0-9_.-]{2,64}",
        s,
        flags=re.I,
    ):
        return True
    return False


def _public_fallback_from_raw(raw: str) -> str:
    """提示词洗不干净时的人话兜底。"""
    s = str(raw or "")
    m = re.search(r"事件类型[:：]\s*([a-z][a-z0-9_.-]{2,64})", s, re.I)
    if m:
        return f"事故巡检：处理事件 {m.group(1)}"
    m = _TASK_FIELD.search(s)
    if m:
        token = (m.group(1) or "").strip()
        if token and not _looks_like_prompt_leak(token) and not _EVENT_TOKEN.fullmatch(token):
            return token
    return "岗位任务执行摘要（内部提示词已隐藏）"


def _publicize_feed_text(
    raw: str, *, summary_len: int = 96, detail_len: int = 600
) -> Tuple[str, str]:
    """把内部任务/提示词压成官网可读摘要；返回 (列表摘要, 详情全文)。"""
    s = str(raw or "")
    s = _CODE_FENCE.sub("", s)
    s = _PATH_TICK.sub("", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return "（暂无公开摘要）", "（暂无公开摘要）"

    preferred = ""
    m = _TASK_FIELD.search(s)
    if m:
        preferred = (m.group(1) or "").strip(" ·:-")
        if _looks_like_prompt_leak(preferred) or _EVENT_TOKEN.fullmatch(preferred):
            preferred = ""

    cleaned = _ROLE_PROMPT.sub(" ", s)
    cleaned = _INSTRUCTION_BOILERPLATE.sub(" ", cleaned)
    cleaned = _META_KV.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ·:-；;")
    # 若仍含角色口吻 / 指令腔，再剥一层
    cleaned = _ROLE_PROMPT.sub(" ", cleaned)
    cleaned = _INSTRUCTION_BOILERPLATE.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ·:-；;")

    detail_src = preferred or cleaned
    if not detail_src or _looks_like_prompt_leak(detail_src):
        detail_src = _public_fallback_from_raw(s)

    detail = _clean(detail_src, detail_len) or "（暂无公开摘要）"
    summary = _clean(preferred or detail_src, summary_len) or detail
    if _looks_like_prompt_leak(summary):
        summary = _clean(_public_fallback_from_raw(s), summary_len)
        detail = summary if len(detail) < 8 or _looks_like_prompt_leak(detail) else detail
    return summary, detail


def _iso(dt: Any) -> Optional[str]:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    s = str(dt).strip()
    return s[:40] if s else None


def _feed_occurred_at(*, raw: Any, day: Any = None, clock: Any = None) -> Optional[str]:
    """Return one sortable event timestamp for every public feed source.

    ``daily_action_items`` exposes ``updated_at`` while execution metrics expose
    ``created_at``. Keeping the full timestamp avoids grouping both sources
    separately and then showing only their ambiguous HH:MM fragments.
    """
    stamp = _iso(raw)
    if stamp:
        return stamp
    day_s = str(day or "").strip()
    clock_s = str(clock or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day_s) and re.fullmatch(r"\d{2}:\d{2}", clock_s):
        return f"{day_s}T{clock_s}:00+00:00"
    return None


def _feed_sort_key(item: Dict[str, Any]) -> float:
    stamp = _feed_occurred_at(
        raw=item.get("occurred_at"), day=item.get("day"), clock=item.get("ts")
    )
    if not stamp:
        return float("-inf")
    try:
        dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (TypeError, ValueError, OverflowError):
        return float("-inf")


def _sort_feed(feed: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge all feed sources into one true newest-first timeline."""
    return sorted(feed, key=_feed_sort_key, reverse=True)


def _public_ai_driver_snapshot() -> Dict[str, Any]:
    """Build a secret-safe public view of the active platform LLM driver."""
    driver: Dict[str, Any] = {
        "employee_id": "llm-ops-engineer",
        "name": "LLM 运维工程师",
        "enabled": False,
        "state": "standby",
        "state_label": "待启动",
        "provider": "",
        "model": "",
        "route_source": "unavailable",
        "last_action": "",
        "last_action_label": "尚无巡检记录",
        "last_checked_at": None,
        "quota": {
            "state": "unknown",
            "visibility": "unknown",
            "remaining_percent": None,
        },
    }

    runtime_route: Optional[Dict[str, Any]] = None
    try:
        from modstore_server.llm_runtime_route import current_runtime_route
        from modstore_server.services.llm import resolve_platform_bench_llm

        runtime_route = current_runtime_route()
        provider, model = resolve_platform_bench_llm()
        driver["provider"] = _clean(str(provider or ""), 48)
        driver["model"] = _clean(str(model or ""), 96)
        driver["route_source"] = "runtime_route" if runtime_route else "platform_default"
    except Exception:
        logger.exception("company_hall: resolve public AI driver route failed")

    try:
        from modstore_server.llm_runtime_autopilot import autopilot_status

        status = autopilot_status()
        enabled = bool(status.get("enabled"))
        last = status.get("last_run") if isinstance(status.get("last_run"), dict) else {}
        action = str(last.get("action") or "").strip()
        driver["enabled"] = enabled
        driver["last_action"] = _clean(action, 48)
        driver["last_checked_at"] = _iso(
            last.get("checked_at")
            or ((runtime_route or {}).get("switched_at") if runtime_route else None)
        )

        action_labels = {
            "kept": "当前路由健康，继续驾驶",
            "switched": "已自动切换并复验",
            "kept_warning": "检测到限流，保持并继续观察",
            "observed_unhealthy": "检测异常，正在连续确认",
            "concurrent_change_detected": "检测到管理员切换，已避让",
            "degraded_no_candidate": "API 路由降级，CLI 兜底待命",
            "observation_failed": "巡检未完成",
            "switch_failed": "自动切换失败",
            "rolled_back": "新路由复验失败，已回滚",
            "rollback_failed": "回滚异常，需要人工介入",
            "disabled": "自动驾驶未启用",
        }
        driver["last_action_label"] = action_labels.get(
            action, "已记录最近一次自动巡检" if action else "尚无巡检记录"
        )

        degraded_actions = {
            "degraded_no_candidate",
            "observation_failed",
            "switch_failed",
            "rolled_back",
            "rollback_failed",
        }
        if enabled and action in degraded_actions:
            driver["state"] = "degraded"
            driver["state_label"] = "降级巡检"
        elif enabled:
            driver["state"] = "driving"
            driver["state_label"] = "自动驾驶中"

        quota_rows = last.get("quota") if isinstance(last.get("quota"), dict) else {}
        quota = quota_rows.get(driver["provider"])
        if isinstance(quota, dict):
            driver["quota"] = {
                "state": _clean(str(quota.get("state") or "unknown"), 24),
                "visibility": _clean(str(quota.get("visibility") or "unknown"), 24),
                "remaining_percent": quota.get("remaining_percent"),
            }
    except Exception:
        logger.exception("company_hall: resolve public AI driver status failed")

    return driver


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
            st = str(m.status or "").strip().lower()
            task = str(m.task or "")
            # burn-in / 验收夹具失败不算运营告警；否则编制巡检会把大厅刷成大片红
            burnin = (
                st == "burnin_rejected"
                or task.lstrip().startswith("[duty-burn-in:")
                or "[duty-burn-in:" in task[:48]
            )
            if st and st not in {"success", "completed", "ok"} and not burnin:
                slot["fail_24h"] += 1
            if slot["last_at"] is None:
                slot["last_status"] = st
                # 保留较长原文，公开投影时再摘要；避免列表层二次截断丢详情
                slot["last_task"] = _clean(task, 600)
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
    last_status = str(metric.get("last_status") or "").strip().lower()
    titles = action.get("titles") or []
    last_healthy = last_status in {"", "success", "completed", "ok"}

    # 未闭环 P0：告警。失败计数仅在「最近一跑仍不健康」时拉红，避免事故风暴后成功恢复仍挂红一整天。
    if p0 > 0 or (fail >= 2 and not last_healthy):
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


def _load_published_action_board() -> Optional[Dict[str, Any]]:
    """DB 空时回退到已发布的公开行动板 JSON（仍是公开只读文件，不造假）。"""
    root = _repo_root()
    candidates = [
        root / "成都修茈科技有限公司" / "download-action-board.json",
        root
        / "成都修茈科技有限公司"
        / "MODstore_deploy"
        / "market"
        / "public"
        / "download-action-board.json",
    ]
    for raw in ("/root/成都修茈科技有限公司", "/opt/xcmax/current/成都修茈科技有限公司"):
        try:
            live = Path(raw)
            if live.is_dir():
                candidates.append(live.resolve() / "download-action-board.json")
        except OSError:
            pass
    for path in candidates:
        try:
            if not path.is_file():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and (
                data.get("trajectory")
                or ((data.get("breakpoints") or {}).get("items"))
                or ((data.get("goals") or {}).get("items"))
            ):
                return data
        except Exception:
            logger.exception("company_hall: read published action board failed %s", path)
    return None


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
