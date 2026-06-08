"""日级容灾备份：modstore.db（SQLite online backup）+ release_train SSOT/历史。

环境：
- ``MODSTORE_DAILY_BACKUP_ENABLED``（默认 ``1``）：设 ``0`` 关闭。
- ``MODSTORE_BACKUP_DIR``：备份根目录（默认 ``<db 同级>/backups``）。
- ``MODSTORE_BACKUP_KEEP``（默认 ``14``）：每类保留最近 N 份，超出删除最旧。
- ``MODSTORE_DAILY_BACKUP_HOUR`` / ``MINUTE`` / ``TZ``：cron 时刻（默认 03:05 北京时间，早于 03:15 归档）。

仅 SQLite 走文件级在线备份；Postgres 由外部托管/外部备份策略负责，这里跳过。
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    return (os.environ.get("MODSTORE_DAILY_BACKUP_ENABLED", "1") or "").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _keep() -> int:
    try:
        return max(1, int(os.environ.get("MODSTORE_BACKUP_KEEP", "14")))
    except ValueError:
        return 14


def _backup_dir() -> Path:
    raw = (os.environ.get("MODSTORE_BACKUP_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    try:
        from modstore_server.models_db import default_db_path

        return default_db_path().parent / "backups"
    except Exception:
        return Path(__file__).resolve().parent / "backups"


def _prune(dir_path: Path, prefix: str, keep: int) -> int:
    files = sorted(dir_path.glob(f"{prefix}*"), key=lambda p: p.name)
    removed = 0
    while len(files) > keep:
        victim = files.pop(0)
        try:
            victim.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def _backup_sqlite(dst_dir: Path, stamp: str, keep: int) -> Dict[str, Any]:
    try:
        from modstore_server.models_db import database_url, default_db_path
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "skipped": True, "reason": f"models_db import failed: {exc}"}

    url = database_url()
    if not url.startswith("sqlite:///"):
        return {
            "ok": True,
            "skipped": True,
            "reason": "non-sqlite backend; external backup expected",
        }

    src = default_db_path()
    if not src.is_file():
        return {"ok": False, "error": f"db not found: {src}"}

    dst = dst_dir / f"modstore_{stamp}.db"
    try:
        # SQLite 在线备份 API：跑库时也安全（不直接 cp，避免写半截）
        with sqlite3.connect(str(src)) as src_conn, sqlite3.connect(str(dst)) as dst_conn:
            src_conn.backup(dst_conn)
        pruned = _prune(dst_dir, "modstore_", keep)
        return {"ok": True, "path": str(dst), "bytes": dst.stat().st_size, "pruned": pruned}
    except Exception as exc:  # noqa: BLE001
        logger.exception("db backup failed")
        return {"ok": False, "error": str(exc)[:300]}


def _backup_release_train(dst_dir: Path, stamp: str, keep: int) -> Dict[str, Any]:
    try:
        from modstore_server.release_train import ssot_path

        src = ssot_path()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"ssot_path failed: {exc}"}
    if not src.is_file():
        return {"ok": True, "skipped": True, "reason": "release_train.json not found yet"}
    dst = dst_dir / f"release_train_{stamp}.json"
    try:
        shutil.copy2(src, dst)
        pruned = _prune(dst_dir, "release_train_", keep)
        return {"ok": True, "path": str(dst), "pruned": pruned}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:300]}


def _trigger_dr_failure(out: Dict[str, Any]) -> Dict[str, Any]:
    """DRFAIL 降级：备份失败 → 告警 + 守卫当日 release_train 不递增（保留上一份快照）。"""
    reason = (
        (out.get("db") or {}).get("error")
        or (out.get("release_train") or {}).get("error")
        or "daily backup failed"
    )
    degrade: Dict[str, Any] = {"alerted": False, "guard": None}
    try:
        from modstore_server.release_train import set_backup_guard

        degrade["guard"] = set_backup_guard(f"daily backup failed: {str(reason)[:300]}")
    except Exception:  # noqa: BLE001
        logger.exception("daily backup: set release_train backup guard failed")
    try:
        from modstore_server.incident_bus import publish

        degrade["alerted"] = bool(
            publish(
                "log.anomaly",
                {
                    "title": "容灾备份失败 → 降级（跳过当日 release_train bump）",
                    "stamp": out.get("stamp"),
                    "backup_dir": out.get("backup_dir"),
                    "db": out.get("db"),
                    "release_train_backup": out.get("release_train"),
                    "reason": str(reason)[:500],
                },
                source="daily-backup",
            )
        )
    except Exception:  # noqa: BLE001
        logger.exception("daily backup: publish DR failure alert failed")
    return degrade


def _clear_dr_guard() -> None:
    """备份恢复正常 → 解除灾备守卫，日更恢复递增。"""
    try:
        from modstore_server.release_train import clear_backup_guard

        clear_backup_guard(reason="daily backup recovered")
    except Exception:  # noqa: BLE001
        logger.exception("daily backup: clear release_train backup guard failed")


def run_daily_backup_job() -> Dict[str, Any]:
    """执行一次容灾备份；返回结构化结果（供日志/可视化）。"""
    if not _enabled():
        return {"ok": True, "skipped": True, "reason": "MODSTORE_DAILY_BACKUP_ENABLED=0"}
    dst_dir = _backup_dir()
    dst_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    keep = _keep()
    out = {
        "ok": True,
        "backup_dir": str(dst_dir),
        "stamp": stamp,
        "db": _backup_sqlite(dst_dir, stamp, keep),
        "release_train": _backup_release_train(dst_dir, stamp, keep),
    }
    out["ok"] = bool(out["db"].get("ok")) and bool(out["release_train"].get("ok"))
    logger.info("daily backup done: ok=%s dir=%s", out["ok"], dst_dir)
    if out["ok"]:
        _clear_dr_guard()
    else:
        out["degrade"] = _trigger_dr_failure(out)
    return out


def list_backups(*, limit: int = 30) -> List[Dict[str, Any]]:
    dst_dir = _backup_dir()
    if not dst_dir.is_dir():
        return []
    rows: List[Dict[str, Any]] = []
    for p in sorted(dst_dir.glob("*"), key=lambda x: x.name, reverse=True)[: max(1, int(limit))]:
        try:
            rows.append(
                {
                    "name": p.name,
                    "bytes": p.stat().st_size,
                    "mtime": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(),
                }
            )
        except OSError:
            continue
    return rows


def cron_trigger_for_backup():
    from apscheduler.triggers.cron import CronTrigger

    hour = int(os.environ.get("MODSTORE_DAILY_BACKUP_HOUR", "3"))
    minute = int(os.environ.get("MODSTORE_DAILY_BACKUP_MINUTE", "5"))
    tz = os.environ.get("MODSTORE_DAILY_BACKUP_TZ", "Asia/Shanghai")
    try:
        from zoneinfo import ZoneInfo

        return CronTrigger(hour=hour, minute=minute, timezone=ZoneInfo(tz))
    except Exception:
        return CronTrigger(hour=hour, minute=minute)
