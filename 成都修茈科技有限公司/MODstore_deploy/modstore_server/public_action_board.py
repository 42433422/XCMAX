"""官网产品下载页公开行动看板（只读、脱敏）。

把 ``daily_action_items`` 导出为公开 JSON（无源码路径、无内部 ID、无写接口），
供 ``download.html`` 同源 fetch ``/download-action-board.json``。
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

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


def _public_item(it: Dict[str, Any]) -> Dict[str, Any]:
    status = str(it.get("status") or "open")
    return {
        "title": _clean_public_text(str(it.get("text") or "")),
        "priority": str(it.get("priority") or "P2"),
        "status": status,
        "status_label": _STATUS_PUBLIC.get(status, status),
        "line": str(it.get("line") or "P-S"),
        "line_label": _LINE_PUBLIC.get(str(it.get("line") or "P-S"), str(it.get("line") or "—")),
        "owner": str(it.get("employee_label") or "AI 员工").strip()[:64] or "AI 员工",
        "kind": str(it.get("kind") or ""),
        "day": str(it.get("day") or ""),
    }


def build_public_action_board(*, day: Optional[str] = None) -> Dict[str, Any]:
    """构建官网可读的双看板快照（patch=断点清单，update=工作目标）。"""
    from modstore_server.digest_action_items import latest_day, list_action_items, stats

    use_day = day or latest_day() or None
    patches_raw = list_action_items(kind="patch", day=use_day, limit=100) if use_day else []
    updates_raw = list_action_items(kind="update", day=use_day, limit=100) if use_day else []
    patches = [_public_item(x) for x in patches_raw]
    updates = [_public_item(x) for x in updates_raw]
    p_stats = stats(kind="patch", day=use_day) if use_day else {}
    u_stats = stats(kind="update", day=use_day) if use_day else {}

    def _sum(s: Dict[str, Any]) -> Dict[str, Any]:
        by_p = s.get("by_priority") or {}
        return {
            "total": int(s.get("total") or 0),
            "done": int(s.get("done") or 0),
            "completion_rate": float(s.get("completion_rate") or 0),
            "p0": int(by_p.get("P0") or 0),
            "p1_p2": int(by_p.get("P1") or 0) + int(by_p.get("P2") or 0),
            "by_line": dict(s.get("by_line") or {}),
        }

    return {
        "schema": "xcagi.public_action_board/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "day": use_day,
        "readonly": True,
        "note": "公开只读进度看板；不含源码路径与内部标识。",
        "breakpoints": {
            "title": "断点清单",
            "kind": "patch",
            "summary": _sum(p_stats),
            "items": patches,
        },
        "goals": {
            "title": "工作目标",
            "kind": "update",
            "summary": _sum(u_stats),
            "items": updates,
        },
    }


def public_board_targets() -> List[Path]:
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
    extra = (os.environ.get("MODSTORE_PUBLIC_ACTION_BOARD_EXTRA") or "").strip()
    if extra:
        for raw in extra.split(os.pathsep):
            raw = raw.strip()
            if raw:
                targets.append(Path(raw).expanduser())
    return targets


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
    return {"ok": True, "day": payload.get("day"), "written": written, "payload": payload}
