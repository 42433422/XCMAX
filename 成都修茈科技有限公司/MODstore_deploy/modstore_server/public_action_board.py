"""官网产品下载页公开行动看板（只读、脱敏）。

把 ``daily_action_items`` 导出为公开 JSON（无源码路径、无内部 ID、无写接口），
供 ``/download/breakpoints`` 与 ``/download/goals`` 同源 fetch ``/download-action-board.json``。

SSOT：``kind=patch`` → 断点清单；``kind=update`` → 工作目标。
digest 落库后 / 部署状态回写后调用 ``write_public_action_board`` 刷新快照。
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from modstore_server.public_strategic_goals import verified_strategic_goal_items

logger = logging.getLogger(__name__)

_STATUS_PUBLIC = {
    "open": "待处理",
    "dispatched": "已派发",
    "in_progress": "进行中",
    "merged": "已闭环",
    "closed": "已关闭",
}
_LINE_PUBLIC = {
    "P-W": "网站线",
    "P-S": "软件线",
    "P-App": "移动发布线",
    "S-R": "归档线",
}
_PATH_TICK = re.compile(r"`([^`]*/[^`]*)`")
_CODE_FENCE = re.compile(r"```[\s\S]*?```")
_PRIORITY_MARK = re.compile(r"\*\*P[0-3]\*\*|\bP[0-3]\b")


def _repo_root() -> Path:
    mono = (os.environ.get("XCMAX_MONOREPO_ROOT") or "").strip()
    if mono:
        return Path(mono).expanduser().resolve()
    return Path(__file__).resolve().parents[3]


def _clean_public_text(text: str) -> str:
    s = str(text or "")
    s = _CODE_FENCE.sub("", s)
    s = _PATH_TICK.sub("", s)
    s = _PRIORITY_MARK.sub("", s)
    s = re.sub(r"\s+", " ", s).strip(" ·:-")
    if len(s) > 180:
        s = s[:177] + "…"
    return s or "（条目摘要）"


def _public_clock(raw: Any) -> str:
    """从 created_at/updated_at 抽出公开可读时刻（HH:MM），无则空串。"""
    s = str(raw or "").strip()
    if not s:
        return ""
    # 常见：2026-07-16T08:15:22+00:00 / 2026-07-16 08:15:22
    m = re.search(r"(\d{2}):(\d{2})", s)
    if m:
        return f"{m.group(1)}:{m.group(2)}"
    return ""


def _public_item(it: Dict[str, Any]) -> Dict[str, Any]:
    status = str(it.get("status") or "open")
    updated = str(it.get("updated_at") or it.get("created_at") or "")
    return {
        "title": _clean_public_text(str(it.get("text") or "")),
        "priority": str(it.get("priority") or "P2"),
        "status": status,
        "status_label": _STATUS_PUBLIC.get(status, status),
        "line": str(it.get("line") or "P-S"),
        "line_label": _LINE_PUBLIC.get(str(it.get("line") or "P-S"), str(it.get("line") or "—")),
        "owner": str(it.get("employee_label") or "AI 员工").strip()[:64] or "AI 员工",
        "employee_id": str(it.get("employee_id") or "").strip()[:80],
        "kind": str(it.get("kind") or ""),
        "day": str(it.get("day") or ""),
        "updated_at": updated[:40],
        "ts": _public_clock(updated),
    }


def _clip_title(title: str, max_len: int = 72) -> str:
    t = (title or "").strip()
    if len(t) <= max_len:
        return t
    return t[: max(0, max_len - 1)] + "…"


def build_trajectory(
    patches: List[Dict[str, Any]],
    updates: List[Dict[str, Any]],
    *,
    limit: int = 24,
) -> List[Dict[str, Any]]:
    """从双看板真实条目生成「世界意志」轨迹；无数据时返回空列表（不造假）。"""
    merged: List[Dict[str, Any]] = []
    for it in patches:
        row = dict(it)
        row["kind"] = row.get("kind") or "patch"
        merged.append(row)
    for it in updates:
        row = dict(it)
        row["kind"] = row.get("kind") or "update"
        merged.append(row)

    if not merged:
        return []

    # 按真实更新时间倒序，避免伪时序
    merged.sort(key=lambda x: str(x.get("updated_at") or x.get("day") or ""), reverse=True)

    out: List[Dict[str, Any]] = []
    n = min(len(merged), max(1, limit))
    for it in merged[:n]:
        kind = str(it.get("kind") or "patch")
        href = "/download/breakpoints" if kind == "patch" else "/download/goals"
        status = str(it.get("status") or "open")
        status_label = str(it.get("status_label") or _STATUS_PUBLIC.get(status, status))
        owner = str(it.get("owner") or "AI 员工")
        line_label = str(it.get("line_label") or "产线")
        title = _clip_title(str(it.get("title") or ""))
        text = f"{status_label} · {owner} · {line_label}：{title}"
        ts = str(it.get("ts") or "") or _public_clock(it.get("updated_at"))
        if not ts and it.get("day"):
            ts = str(it.get("day"))[-5:] if len(str(it.get("day"))) >= 5 else str(it.get("day"))
        out.append(
            {
                "ts": ts or "—",
                "text": text,
                "line": str(it.get("line") or "P-S"),
                "line_label": line_label,
                "status": status,
                "status_label": status_label,
                "kind": kind,
                "href": href,
                "day": str(it.get("day") or ""),
                "owner": owner,
                "employee_id": str(it.get("employee_id") or "").strip()[:80],
                "priority": str(it.get("priority") or "P2"),
                "title": str(it.get("title") or ""),
                "updated_at": str(it.get("updated_at") or "")[:40],
                "goal_id": str(it.get("goal_id") or "")[:128],
                "loop_run_id": str(it.get("loop_run_id") or "")[:128],
                "para_task_id": str(it.get("para_task_id") or "")[:128],
                "source": str(it.get("source") or "daily_action_items")[:64],
            }
        )
    return out


def _calendar_today() -> str:
    """行动板日历日：上海时区，避免 UTC 跨日把大厅 day 粘在昨天。"""
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
    except Exception:  # noqa: BLE001
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def build_public_action_board(*, day: Optional[str] = None) -> Dict[str, Any]:
    """构建官网可读的双看板快照（patch=断点清单，update=工作目标）。"""
    from modstore_server.digest_action_items import latest_day, list_action_items, stats

    calendar_day = _calendar_today()
    day_stale = False
    try:
        strategic_updates = verified_strategic_goal_items(limit=100)
    except Exception:
        logger.exception("public_action_board: verified strategic goals unavailable")
        strategic_updates = []
    strategic_days = sorted(
        {str(item.get("day") or "") for item in strategic_updates if item.get("day")}
    )
    source_day = max(
        [value for value in [latest_day() or "", *strategic_days] if value], default=""
    )
    if day:
        use_day = day
    else:
        # 优先「今天」；今天无条目再回退 latest，并显式标记 stale，禁止静默粘旧日。
        today_any = list_action_items(day=calendar_day, limit=1)
        today_strategic = any(item.get("day") == calendar_day for item in strategic_updates)
        if today_any or today_strategic:
            use_day = calendar_day
        elif source_day:
            use_day = source_day
            day_stale = source_day != calendar_day
        else:
            use_day = calendar_day

    patches_raw = list_action_items(kind="patch", day=use_day, limit=100) if use_day else []
    updates_raw = list_action_items(kind="update", day=use_day, limit=100) if use_day else []
    patches = [_public_item(x) for x in patches_raw]
    updates = [
        *[_public_item(x) for x in updates_raw],
        *[item for item in strategic_updates if item.get("day") == use_day],
    ]
    p_stats = stats(kind="patch", day=use_day) if use_day else {}
    u_stats = stats(kind="update", day=use_day) if use_day else {}

    def _sum(s: Dict[str, Any], extras: List[Dict[str, Any]]) -> Dict[str, Any]:
        by_p = s.get("by_priority") or {}
        extra_done = sum(1 for item in extras if item.get("status") in {"merged", "closed"})
        total = int(s.get("total") or 0) + len(extras)
        done = int(s.get("done") or 0) + extra_done
        by_line = dict(s.get("by_line") or {})
        for item in extras:
            line = str(item.get("line") or "P-S")
            by_line[line] = int(by_line.get(line) or 0) + 1
        return {
            "total": total,
            "done": done,
            "completion_rate": round((done / total) * 100, 1) if total else 0.0,
            "p0": int(by_p.get("P0") or 0)
            + sum(1 for item in extras if item.get("priority") == "P0"),
            "p1_p2": int(by_p.get("P1") or 0)
            + int(by_p.get("P2") or 0)
            + sum(1 for item in extras if item.get("priority") in {"P1", "P2"}),
            "by_line": by_line,
        }

    return {
        "schema": "xcagi.public_action_board/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "day": use_day,
        "calendar_day": calendar_day,
        "day_stale": day_stale,
        "readonly": True,
        "note": "公开只读进度看板；不含源码路径与内部标识。",
        "breakpoints": {
            "title": "断点清单",
            "kind": "patch",
            "summary": _sum(p_stats, []),
            "items": patches,
        },
        "goals": {
            "title": "工作目标",
            "kind": "update",
            "summary": _sum(
                u_stats,
                [item for item in strategic_updates if item.get("day") == use_day],
            ),
            "items": updates,
        },
        "trajectory": build_trajectory(patches, updates),
    }


def public_board_targets() -> List[Path]:
    isolated_output = (os.environ.get("MODSTORE_PUBLIC_OUTPUT_ROOT") or "").strip()
    if isolated_output:
        return [Path(isolated_output).expanduser().resolve() / "download-action-board.json"]
    root = _repo_root()
    targets = [
        root / "成都修茈科技有限公司" / "download-action-board.json",
        root
        / "成都修茈科技有限公司"
        / "MODstore_deploy"
        / "market"
        / "public"
        / "download-action-board.json",
        root / "FHD" / "MODstore" / "market" / "public" / "download-action-board.json",
    ]
    # 生产 nginx live root（常为 /opt/xcmax/current 的 symlink）
    for raw in ("/root/成都修茈科技有限公司", "/opt/xcmax/current/成都修茈科技有限公司"):
        try:
            live = Path(raw)
            if live.is_dir():
                targets.append(live.resolve() / "download-action-board.json")
        except OSError:
            pass
    extra = (os.environ.get("MODSTORE_PUBLIC_ACTION_BOARD_EXTRA") or "").strip()
    if extra:
        for raw in extra.split(os.pathsep):
            raw = raw.strip()
            if raw:
                targets.append(Path(raw).expanduser())
    # 去重保序
    seen: set[str] = set()
    uniq: List[Path] = []
    for t in targets:
        key = str(t)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(t)
    return uniq


def write_public_action_board(*, day: Optional[str] = None) -> Dict[str, Any]:
    """写出公开 JSON；失败不抛（不阻断 digest）。"""
    try:
        payload = build_public_action_board(day=day)
    except Exception as exc:
        logger.exception("public_action_board: build failed")
        return {"ok": False, "error": str(exc), "written": []}

    written: List[str] = []
    body = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    for tgt in public_board_targets():
        try:
            parent = tgt.parent
            if not parent.is_dir():
                continue
            tgt.write_text(body, encoding="utf-8")
            written.append(str(tgt))
        except Exception:  # noqa: BLE001
            logger.exception("public_action_board: write failed %s", tgt)
    logger.info(
        "public_action_board: day=%s patch=%s update=%s written=%s",
        payload.get("day"),
        (payload.get("breakpoints") or {}).get("summary", {}).get("total"),
        (payload.get("goals") or {}).get("summary", {}).get("total"),
        len(written),
    )
    try:
        from modstore_server.public_company_hall import write_public_company_hall

        write_public_company_hall(day=day)
    except Exception:
        logger.exception("public_action_board: company hall refresh failed")
    return {"ok": True, "day": payload.get("day"), "written": written, "payload": payload}
