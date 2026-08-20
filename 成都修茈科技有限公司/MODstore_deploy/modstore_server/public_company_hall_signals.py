# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Roster, action, metric, and published-board signals for the company hall."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.public_company_hall_config import (
    DEPARTMENT_ORDER,
)
from modstore_server.public_company_hall_config import WORKING_STATUSES as _WORKING_STATUSES
from modstore_server.public_company_hall_text import _clean, _iso

logger = logging.getLogger(__name__)


def _repo_root() -> Path:
    mono = (os.environ.get("XCMAX_MONOREPO_ROOT") or "").strip()
    if mono:
        return Path(mono).expanduser().resolve()
    return Path(__file__).resolve().parents[3]


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
    except RECOVERABLE_ERRORS:
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

        cutoff = datetime.now(UTC) - timedelta(hours=24)
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
    except RECOVERABLE_ERRORS:
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
            if datetime.now(UTC) - dt <= timedelta(hours=2):
                return "working", str(metric.get("last_task") or "近期刚完成执行")
        except RECOVERABLE_ERRORS:
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
    for raw in (
        "/root/成都修茈科技有限公司",
        "/opt/xcmax/current/成都修茈科技有限公司",
    ):
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
        except RECOVERABLE_ERRORS:
            logger.exception("company_hall: read published action board failed %s", path)
    return None
