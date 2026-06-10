"""日更行动条目（Agentic Business OS 数据底座）。

把 Vibe 预备双清单（更新 MD / 补丁 MD）解析为结构化条目并落库 ``daily_action_items``：
- ``kind=patch``  → 驱动「断点清单」页（补丁修断点，带 P0–P2）
- ``kind=update`` → 驱动「实现目标 / 路线图」页（更新推进目标）

设计：
- 纯增量、自包含；表用 CREATE TABLE IF NOT EXISTS 懒建，不动 models.py。
- 同日幂等：``dedupe_key = sha1(day|kind|employee_id|text)`` 唯一约束；重复 upsert 不新增。
- 复用 :mod:`modstore_server.digest_vibe_line_dispatch` 的员工→产线归类，口径与派发一致。
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

KIND_PATCH = "patch"
KIND_UPDATE = "update"
VALID_STATUS = ("open", "dispatched", "in_progress", "merged", "closed")
_STATUS_RANK = {"open": 0, "dispatched": 1, "in_progress": 2, "merged": 3, "closed": 3}

# 章节头：## [employee_id] 显示名 · v{ver}
_SECTION_RE = re.compile(
    r"(?ms)^##\s*\[(?P<eid>[^\]]+)\]\s*(?P<label>[^\n·]*)[^\n]*\n(?P<body>.*?)(?=^##\s*\[|\Z)"
)
# 列表条目：- / * / 1.（捕获缩进以区分父/子 bullet）
_ITEM_RE = re.compile(r"(?m)^(?P<indent>[ \t]*)(?:[-*]|\d+\.)\s+(?P<text>.+?)\s*$")
_PRIORITY_RE = re.compile(r"\bP([0-2])\b")
_PATH_RE = re.compile(r"`([^`]*/[^`]*)`")


def _default_priority(*, kind: str) -> str:
    return "P2" if kind == KIND_PATCH else "P1"


def _is_noise_sub_item(text: str, indent: int) -> bool:
    """子 bullet 元信息（handler/依赖说明），非独立行动条目。"""
    if indent < 2:
        return False
    t = (text or "").strip()
    if t.startswith("handler ") or t.startswith("handler`"):
        return True
    if t.startswith("依赖 ") and ("同步" in t or "契约" in t or "接口" in t):
        return True
    return False


def _infer_priority(text: str, *, kind: str, section_priority: str, indent: int) -> str:
    pm = _PRIORITY_RE.search(text or "")
    if pm:
        return "P" + pm.group(1)
    if indent >= 2 and section_priority:
        return section_priority
    return _default_priority(kind=kind)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dedupe_key(day: str, kind: str, eid: str, text: str) -> str:
    raw = f"{day}|{kind}|{eid}|{text}".encode("utf-8", "replace")
    return hashlib.sha1(raw).hexdigest()


def _engine():
    from modstore_server.models import get_engine  # type: ignore

    return get_engine()


def ensure_table() -> None:
    """懒建 daily_action_items（按方言选用 SQLite / Postgres DDL）。"""
    from sqlalchemy import text as _sql

    cols = """
        day VARCHAR(32) NOT NULL,
        record_id INTEGER,
        kind VARCHAR(16) NOT NULL,
        employee_id VARCHAR(128),
        employee_label VARCHAR(128),
        line VARCHAR(16),
        priority VARCHAR(8),
        scope_path TEXT,
        text TEXT,
        rt_version VARCHAR(32),
        status VARCHAR(16) DEFAULT 'open',
        dedupe_key VARCHAR(64) UNIQUE,
        created_at VARCHAR(40),
        updated_at VARCHAR(40)
    """
    eng = _engine()
    dialect = (eng.dialect.name or "").lower()
    if dialect == "postgresql":
        ddl = f"CREATE TABLE IF NOT EXISTS daily_action_items (id SERIAL PRIMARY KEY, {cols})"
    else:
        ddl = f"CREATE TABLE IF NOT EXISTS daily_action_items (id INTEGER PRIMARY KEY AUTOINCREMENT, {cols})"
    with eng.begin() as conn:
        conn.execute(_sql(ddl))
        for stmt in (
            "CREATE INDEX IF NOT EXISTS ix_dai_day ON daily_action_items (day)",
            "CREATE INDEX IF NOT EXISTS ix_dai_kind ON daily_action_items (kind)",
            "CREATE INDEX IF NOT EXISTS ix_dai_status ON daily_action_items (status)",
        ):
            try:
                conn.execute(_sql(stmt))
            except Exception:
                pass


def _parse_markdown(markdown: str, *, kind: str) -> List[Dict[str, Any]]:
    """解析一份清单 MD → [{employee_id, employee_label, priority, scope_path, text}]。"""
    out: List[Dict[str, Any]] = []
    text = (markdown or "").strip()
    if not text:
        return out
    for m in _SECTION_RE.finditer(text):
        eid = str(m.group("eid") or "").strip()
        label = str(m.group("label") or "").strip()
        body = str(m.group("body") or "")
        if not eid:
            continue
        section_scope = ""
        sp = _PATH_RE.search(body)
        if sp:
            section_scope = sp.group(1).strip()
        section_priority = ""
        for im in _ITEM_RE.finditer(body):
            indent = len(str(im.group("indent") or "").expandtabs(2))
            item_text = str(im.group("text") or "").strip()
            if not item_text or item_text.startswith("|"):
                continue
            # 跳过「职责/scope/版本」这类元信息行
            low = item_text.lower()
            if item_text.startswith(
                ("职责", "员工包版本", "建议 scope", "scope")
            ) or low.startswith(("scope", "pack_version")):
                continue
            if _is_noise_sub_item(item_text, indent):
                continue
            pr = _infer_priority(
                item_text, kind=kind, section_priority=section_priority, indent=indent
            )
            if indent < 2 and _PRIORITY_RE.search(item_text):
                section_priority = pr
            elif indent < 2 and not section_priority:
                section_priority = pr
            ip = _PATH_RE.search(item_text)
            out.append(
                {
                    "employee_id": eid,
                    "employee_label": label,
                    "priority": pr,
                    "scope_path": (ip.group(1).strip() if ip else section_scope),
                    "text": item_text[:1000],
                }
            )
    return out


def parse_and_store_action_items(
    *,
    day: str,
    record_id: int,
    updates_markdown: str = "",
    patches_markdown: str = "",
    rt_version: str = "",
) -> Dict[str, Any]:
    """解析双清单并 upsert 到 daily_action_items；返回计数。失败不抛错（不阻断 digest）。"""
    try:
        ensure_table()
    except Exception:
        logger.exception("action_items: ensure_table failed")
        return {"ok": False, "error": "ensure_table failed", "patch": 0, "update": 0}

    try:
        from modstore_server.digest_vibe_line_dispatch import (
            build_employee_dispatch_map,
            pick_dispatch_line,
        )

        emp_lines = build_employee_dispatch_map()
    except Exception:
        emp_lines = {}

        def pick_dispatch_line(eid, _m, *, list_kind):  # type: ignore
            return "P-S"

    rows: List[Dict[str, Any]] = []
    for kind, md, lk in (
        (KIND_PATCH, patches_markdown, "patches"),
        (KIND_UPDATE, updates_markdown, "updates"),
    ):
        for it in _parse_markdown(md, kind=kind):
            eid = it["employee_id"]
            try:
                line = pick_dispatch_line(eid, emp_lines, list_kind=lk)
            except Exception:
                line = "P-S"
            rows.append(
                {
                    "day": day,
                    "record_id": int(record_id or 0),
                    "kind": kind,
                    "employee_id": eid,
                    "employee_label": it["employee_label"],
                    "line": line,
                    "priority": it["priority"],
                    "scope_path": it["scope_path"],
                    "text": it["text"],
                    "rt_version": rt_version,
                    "status": "open",
                    "dedupe_key": _dedupe_key(day, kind, eid, it["text"]),
                    "created_at": _now(),
                    "updated_at": _now(),
                }
            )

    if not rows:
        return {"ok": True, "patch": 0, "update": 0, "note": "no items parsed"}

    from sqlalchemy import text as _sql

    inserted = {"patch": 0, "update": 0}
    eng = _engine()
    with eng.begin() as conn:
        for r in rows:
            try:
                exists = conn.execute(
                    _sql("SELECT 1 FROM daily_action_items WHERE dedupe_key=:k"),
                    {"k": r["dedupe_key"]},
                ).first()
                if exists:
                    continue
                conn.execute(
                    _sql(
                        "INSERT INTO daily_action_items "
                        "(day, record_id, kind, employee_id, employee_label, line, priority, scope_path, text, rt_version, status, dedupe_key, created_at, updated_at) "
                        "VALUES (:day,:record_id,:kind,:employee_id,:employee_label,:line,:priority,:scope_path,:text,:rt_version,:status,:dedupe_key,:created_at,:updated_at)"
                    ),
                    r,
                )
                inserted[r["kind"]] = inserted.get(r["kind"], 0) + 1
            except Exception:
                logger.exception("action_items: insert failed key=%s", r.get("dedupe_key"))
    logger.info(
        "action_items stored day=%s patch=%s update=%s",
        day,
        inserted.get("patch"),
        inserted.get("update"),
    )
    return {"ok": True, **inserted}


def _normalize_item_row(it: Dict[str, Any]) -> Dict[str, Any]:
    """读时归一：补全空优先级；过滤已入库的 handler/依赖 噪声子项。"""
    text = str(it.get("text") or "").strip()
    if _is_noise_sub_item(text, 2):
        it["_hidden"] = True
        return it
    if not str(it.get("priority") or "").strip():
        kind = str(it.get("kind") or KIND_PATCH)
        pm = _PRIORITY_RE.search(text)
        it["priority"] = ("P" + pm.group(1)) if pm else _default_priority(kind=kind)
    return it


def list_action_items(
    *,
    kind: Optional[str] = None,
    day: Optional[str] = None,
    record_id: Optional[int] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    try:
        ensure_table()
    except Exception:
        return []
    from sqlalchemy import text as _sql

    where = []
    params: Dict[str, Any] = {"lim": max(1, min(int(limit), 2000))}
    if kind:
        where.append("kind=:kind")
        params["kind"] = kind
    if day:
        where.append("day=:day")
        params["day"] = day
    if record_id:
        where.append("record_id=:rid")
        params["rid"] = int(record_id)
    sql = "SELECT id, day, record_id, kind, employee_id, employee_label, line, priority, scope_path, text, rt_version, status, created_at, updated_at FROM daily_action_items"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END, id DESC LIMIT :lim"
    out: List[Dict[str, Any]] = []
    eng = _engine()
    with eng.begin() as conn:
        for row in conn.execute(_sql(sql), params).mappings():
            norm = _normalize_item_row(dict(row))
            if norm.get("_hidden"):
                continue
            norm.pop("_hidden", None)
            out.append(norm)
    return out


def latest_day(*, kind: Optional[str] = None) -> str:
    try:
        ensure_table()
    except Exception:
        return ""
    from sqlalchemy import text as _sql

    sql = "SELECT day FROM daily_action_items"
    params: Dict[str, Any] = {}
    if kind:
        sql += " WHERE kind=:kind"
        params["kind"] = kind
    sql += " ORDER BY day DESC LIMIT 1"
    eng = _engine()
    with eng.begin() as conn:
        row = conn.execute(_sql(sql), params).first()
    return str(row[0]) if row else ""


def _normalize_match_text(text: str) -> str:
    """条目 / WorkUnit 文本归一化，便于跨解析器模糊匹配。"""
    s = str(text or "")
    s = re.sub(r"\*\*P[0-3]\*\*", "", s, flags=re.I)
    s = re.sub(r"\bP[0-3]\b", "", s, flags=re.I)
    s = re.sub(r"`[^`]*`", "", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s[:400]


def _text_matches(item_text: str, task_text: str) -> bool:
    a = _normalize_match_text(item_text)
    b = _normalize_match_text(task_text)
    if not a or not b:
        return False
    if a == b:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) >= 12 and shorter in longer:
        return True
    if len(shorter) >= 6 and shorter in longer and len(longer) - len(shorter) <= 80:
        return True
    return False


def find_matching_item_ids(
    *,
    record_id: int,
    employee_id: str,
    kind: str,
    task_text: str,
    day: Optional[str] = None,
) -> List[int]:
    """按 digest + 员工 + 种类 + 任务摘要匹配行动条目 id（派发回写用）。"""
    items = list_action_items(kind=kind, record_id=int(record_id or 0), limit=500)
    if day:
        items = [it for it in items if str(it.get("day") or "") == day]
    eid = (employee_id or "").strip()
    ids: List[int] = []
    for it in items:
        if eid and str(it.get("employee_id") or "").strip() != eid:
            continue
        if _text_matches(str(it.get("text") or ""), task_text):
            ids.append(int(it["id"]))
    if ids or not eid:
        return ids
    # WorkUnit 可能经 resolve_work_unit_employee 改派，回退为仅文本匹配
    for it in items:
        if _text_matches(str(it.get("text") or ""), task_text):
            iid = int(it["id"])
            if iid not in ids:
                ids.append(iid)
    return ids


def set_status_if_advanced(item_id: int, status: str) -> bool:
    """仅向前推进状态（open→dispatched→…→merged），不降级。"""
    status = str(status or "").strip().lower()
    if status not in VALID_STATUS:
        return False
    from sqlalchemy import text as _sql

    eng = _engine()
    with eng.begin() as conn:
        row = conn.execute(
            _sql("SELECT status FROM daily_action_items WHERE id=:id"),
            {"id": int(item_id)},
        ).first()
        if not row:
            return False
        cur = str(row[0] or "open").strip().lower()
        if _STATUS_RANK.get(status, 0) <= _STATUS_RANK.get(cur, 0):
            return False
        conn.execute(
            _sql("UPDATE daily_action_items SET status=:s, updated_at=:u WHERE id=:id"),
            {"s": status, "u": _now(), "id": int(item_id)},
        )
    return True


def set_status(item_id: int, status: str) -> Dict[str, Any]:
    status = str(status or "").strip().lower()
    if status not in VALID_STATUS:
        return {"ok": False, "error": f"invalid status; allowed={VALID_STATUS}"}
    from sqlalchemy import text as _sql

    eng = _engine()
    with eng.begin() as conn:
        conn.execute(
            _sql("UPDATE daily_action_items SET status=:s, updated_at=:u WHERE id=:id"),
            {"s": status, "u": _now(), "id": int(item_id)},
        )
    return {"ok": True, "id": int(item_id), "status": status}


def sync_dispatched_for_work_units(record_id: int, units: Sequence[Any]) -> Dict[str, Any]:
    """line-execute 派发成功后：匹配条目 → dispatched（已派发）。"""
    updated = 0
    matched: List[int] = []
    for u in units:
        lk = str(
            getattr(u, "list_kind", None)
            or (u.get("list_kind") if isinstance(u, dict) else "")
            or ""
        )
        kind = KIND_PATCH if lk == "patches" else KIND_UPDATE
        eid = str(
            getattr(u, "employee_id", None)
            or (u.get("employee_id") if isinstance(u, dict) else "")
            or ""
        )
        brief = str(
            getattr(u, "task_brief", None)
            or (u.get("task_brief") if isinstance(u, dict) else "")
            or ""
        )
        if not brief:
            continue
        for iid in find_matching_item_ids(
            record_id=int(record_id),
            employee_id=eid,
            kind=kind,
            task_text=brief,
        ):
            if iid in matched:
                continue
            if set_status_if_advanced(iid, "dispatched"):
                updated += 1
                matched.append(iid)
    logger.info("action_items dispatch writeback record=%s updated=%s", record_id, updated)
    return {"ok": True, "updated": updated, "matched_ids": matched}


def sync_merged_on_deploy(
    *, record_id: Optional[int] = None, day: Optional[str] = None
) -> Dict[str, Any]:
    """OpsStagedChange 部署/合并成功后：dispatched|in_progress → merged（已闭环）。"""
    use_day = (day or "").strip() or latest_day()
    items = list_action_items(day=use_day or None, limit=2000)
    if record_id:
        items = [it for it in items if int(it.get("record_id") or 0) == int(record_id)]
    updated = 0
    merged_ids: List[int] = []
    for it in items:
        st = str(it.get("status") or "open")
        if st not in ("dispatched", "in_progress"):
            continue
        iid = int(it["id"])
        if set_status_if_advanced(iid, "merged"):
            updated += 1
            merged_ids.append(iid)
    logger.info("action_items merge writeback day=%s updated=%s", use_day, updated)
    return {"ok": True, "updated": updated, "merged_ids": merged_ids, "day": use_day}


def stats(*, kind: Optional[str] = None, day: Optional[str] = None) -> Dict[str, Any]:
    """完成率/分布指标（Agentic Business OS 趋势用）。"""
    items = list_action_items(kind=kind, day=day, limit=2000)
    total = len(items)
    by_status: Dict[str, int] = {}
    by_line: Dict[str, int] = {}
    by_priority: Dict[str, int] = {}
    for it in items:
        by_status[it["status"]] = by_status.get(it["status"], 0) + 1
        by_line[it["line"]] = by_line.get(it["line"], 0) + 1
        if it.get("priority"):
            by_priority[it["priority"]] = by_priority.get(it["priority"], 0) + 1
    done = by_status.get("merged", 0) + by_status.get("closed", 0)
    return {
        "total": total,
        "done": done,
        "completion_rate": round(done / total * 100, 1) if total else 0.0,
        "by_status": by_status,
        "by_line": by_line,
        "by_priority": by_priority,
    }
