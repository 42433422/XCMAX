"""按需快照：交叉升级 / 门禁回滚前抓取 modstore.db + release_train SSOT。

与 ``daily_backup_job`` 共用备份逻辑，写入 ``backups/ondemand/`` 子目录，
并派发 ``backup.ondemand_completed`` / ``backup.ondemand_failed`` 事件链。
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    return (os.environ.get("MODSTORE_ONDEMAND_BACKUP_ENABLED", "1") or "").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _backup_dir() -> Path:
    try:
        from modstore_server.daily_backup_job import _backup_dir as daily_dir

        return daily_dir() / "ondemand"
    except Exception:
        raw = (os.environ.get("MODSTORE_BACKUP_DIR") or "").strip()
        if raw:
            return Path(raw).expanduser().resolve() / "ondemand"
        return Path(__file__).resolve().parent / "backups" / "ondemand"


def run_ondemand_backup(
    *,
    trigger: str,
    reason: str = "",
) -> Dict[str, Any]:
    """执行一次按需快照。``trigger`` 如 ``auto_rollback`` / ``FASTGATE`` / ``manual``。"""
    if not _enabled():
        return {"ok": True, "skipped": True, "reason": "MODSTORE_ONDEMAND_BACKUP_ENABLED=0"}

    from modstore_server.daily_backup_job import _backup_release_train, _backup_sqlite, _keep

    dst_dir = _backup_dir()
    dst_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    keep = _keep()
    tag = str(trigger or "manual").replace("/", "_")[:32]
    prefix = f"ondemand_{tag}_{stamp}"

    out: Dict[str, Any] = {
        "ok": True,
        "trigger": tag,
        "reason": str(reason)[:500],
        "backup_dir": str(dst_dir),
        "stamp": stamp,
        "db": _backup_sqlite(dst_dir, prefix, keep),
        "release_train": _backup_release_train(dst_dir, prefix, keep),
    }
    out["ok"] = bool(out["db"].get("ok")) and bool(out["release_train"].get("ok"))
    logger.info(
        "ondemand backup done ok=%s trigger=%s dir=%s",
        out["ok"],
        tag,
        dst_dir,
    )

    from modstore_server.backup_event_subscriber import emit_backup_event

    event_type = "backup.ondemand_completed" if out["ok"] else "backup.ondemand_failed"
    payload = {
        **out,
        "trigger": tag,
    }
    emit_backup_event(event_type, payload)
    if out["ok"]:
        # 通用 completed 事件让只订 scheduled 路径的下游也能感知（subscriber 会去重 ondemand）
        emit_backup_event(
            "backup.completed",
            {**payload, "trigger": tag},
        )
    return out
