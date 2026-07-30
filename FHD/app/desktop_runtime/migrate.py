"""Desktop data backup and migration entry points."""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

from app.utils.time import utc_now_naive

from .backup_retention import cleanup_local_backups
from .paths import configure_desktop_environment, ensure_desktop_dirs

logger = logging.getLogger(__name__)

# 启动自检：磁盘剩余空间低于此阈值（字节）时记录警告，但不阻塞启动。
_MIN_DISK_FREE_BYTES = 500 * 1024 * 1024  # 500 MB


def backup_database(
    data_dir: str | os.PathLike[str] | None = None, version: str = "unknown"
) -> Path | None:
    """使用 sqlite3.backup() API 做在线热备份，业务在跑也能备份。

    shutil.copy2 是文件级拷贝，SQLite 在写入时被拷会得到不一致的库。
    sqlite3.backup() 是 SQLite 官方推荐的在线热备份 API，会处理 WAL
    文件合并，保证备份出来的库是一致的。备份后跑 integrity_check 校验，
    校验失败删除备份文件并返回 None。
    """
    dirs = ensure_desktop_dirs(data_dir)
    db = dirs["data"] / "xcagi.db"
    if not db.exists():
        return None
    stamp = utc_now_naive().strftime("%Y%m%d%H%M%S")
    target = dirs["backups"] / f"xcagi-{version}-{stamp}.db"
    target.parent.mkdir(parents=True, exist_ok=True)

    src_conn = None
    dst_conn = None
    try:
        src_conn = sqlite3.connect(str(db))
        dst_conn = sqlite3.connect(str(target))
        src_conn.backup(dst_conn)
    except sqlite3.Error as exc:
        logger.error("backup_database hot backup failed: %s", exc)
        # 清理可能产生的部分文件
        if target.exists():
            try:
                target.unlink()
            except OSError:
                pass
        return None
    finally:
        if dst_conn is not None:
            dst_conn.close()
        if src_conn is not None:
            src_conn.close()

    # 完整性校验：备份出来的库必须能通过 integrity_check 才算成功。
    if not _integrity_check_ok(target):
        logger.error("backup_database integrity_check failed for %s, removing", target)
        try:
            target.unlink()
        except OSError:
            pass
        return None

    # Age-only retention is unsafe for multi-gigabyte desktop databases. Prune
    # immediately after every successful backup, including updater migration
    # snapshots, while explicitly protecting the just-validated recovery point.
    cleanup_local_backups(dirs["backups"], protected=(target,))
    return target


def _integrity_check_ok(db_path: Path) -> bool:
    """跑 PRAGMA integrity_check，返回 True 当且仅当结果为 'ok'。"""
    conn = None
    try:
        conn = sqlite3.connect(str(db_path))
        result = conn.execute("PRAGMA integrity_check").fetchone()
        return bool(result) and result[0] == "ok"
    except sqlite3.Error:
        return False
    finally:
        if conn is not None:
            conn.close()


def _quick_check_ok(db_path: Path) -> bool:
    """跑 PRAGMA quick_check（启动时用，比 integrity_check 快）。"""
    conn = None
    try:
        conn = sqlite3.connect(str(db_path))
        result = conn.execute("PRAGMA quick_check").fetchone()
        return bool(result) and result[0] == "ok"
    except sqlite3.Error:
        return False
    finally:
        if conn is not None:
            conn.close()


def recover_if_corrupt(
    data_dir: str | os.PathLike[str] | None = None,
) -> dict[str, str]:
    """启动自检 + 自动恢复。

    流程：
    1. 检查磁盘剩余空间，低于阈值记录警告（不阻塞）。
    2. 对主库 xcagi.db 跑 PRAGMA quick_check。
    3. 如果损坏：把坏库改名为 .corrupt-{timestamp} 留证据；
       扫描 backups/ 按时间倒序找第一个通过 integrity_check 的备份恢复。
    4. 返回 {"action": "ok"|"restored"|"corrupt_no_backup"|"skipped",
            "detail": str}

    库正常时返回 action=ok，不做任何操作。
    库损坏且能恢复时返回 action=restored，detail 是恢复来源文件名。
    库损坏但没备份时返回 action=corrupt_no_backup，调用方应决定是否阻塞启动。
    主库不存在（首启）时返回 action=skipped。
    """
    dirs = ensure_desktop_dirs(data_dir)
    db = dirs["data"] / "xcagi.db"
    backups_dir = dirs["backups"]

    # 1) 磁盘剩余空间检查（警告不阻塞）
    try:
        usage = shutil.disk_usage(str(dirs["root"]))
        if usage.free < _MIN_DISK_FREE_BYTES:
            logger.warning(
                "desktop disk free low: %d bytes (< %d), write may fail",
                usage.free,
                _MIN_DISK_FREE_BYTES,
            )
    except OSError as exc:
        logger.warning("disk_usage check failed: %s", exc)

    # 2) 主库不存在（首启）—— 跳过自检
    if not db.exists():
        return {"action": "skipped", "detail": "database does not exist yet"}

    # 3) quick_check 通过 = 库健康，直接返回
    if _quick_check_ok(db):
        return {"action": "ok", "detail": ""}

    # 4) 库损坏：改名留证据
    logger.error("database corrupt: %s, attempting recovery from backups", db)
    stamp = utc_now_naive().strftime("%Y%m%d%H%M%S")
    corrupt_path = db.with_name(f"xcagi.db.corrupt-{stamp}")
    try:
        db.rename(corrupt_path)
        logger.warning("renamed corrupt db to %s", corrupt_path)
    except OSError as exc:
        logger.error("failed to rename corrupt db: %s", exc)
        return {"action": "corrupt_no_backup", "detail": f"rename failed: {exc}"}

    # 5) 扫描备份目录找最近的、通过 integrity_check 的备份
    #    同时扫两个目录：
    #    - backups/xcagi-*.db  （定时备份 + migrate.backup_database 产生）
    #    - data/database_backups/*.bak （DatabaseService / API 手动备份产生）
    candidates: list[Path] = []
    if backups_dir.is_dir():
        candidates.extend(backups_dir.glob("xcagi-*.db"))
    legacy_backups_dir = dirs["data"] / "database_backups"
    if legacy_backups_dir.is_dir():
        candidates.extend(legacy_backups_dir.glob("*.bak"))

    if not candidates:
        logger.error("no backups dir, cannot recover")
        return {"action": "corrupt_no_backup", "detail": "no usable backup"}

    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for candidate in candidates:
        if not _integrity_check_ok(candidate):
            logger.warning("skipping bad backup: %s", candidate)
            continue
        try:
            shutil.copy2(candidate, db)
            logger.info("restored db from backup: %s", candidate.name)
            return {"action": "restored", "detail": candidate.name}
        except OSError as exc:
            logger.error("restore from %s failed: %s", candidate, exc)
            continue

    # 6) 所有备份都不行——主库已被改名，需要调用方决定是否阻塞启动
    logger.error("all backups failed integrity check or restore")
    return {"action": "corrupt_no_backup", "detail": "no usable backup"}


def _alembic_root() -> Path:
    """Resolve directory containing alembic.ini (PyInstaller _MEIPASS or FHD repo root)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path.cwd()))
    return Path(__file__).resolve().parents[2]


def _alembic_config():
    from alembic.config import Config

    root = _alembic_root()
    ini = root / "alembic.ini"
    # Older/broken PyInstaller trees nested the file as alembic.ini/alembic.ini.
    if not ini.is_file() and (root / "alembic.ini" / "alembic.ini").is_file():
        ini = root / "alembic.ini" / "alembic.ini"
    if not ini.is_file():
        raise FileNotFoundError(f"alembic.ini not found: {ini}")
    return Config(str(ini))


def _script_revisions() -> tuple[set[str], set[str]]:
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_alembic_config())
    known = {revision.revision for revision in script.walk_revisions()}
    return known, set(script.get_heads())


def _sqlite_current_revisions(
    data_dir: str | os.PathLike[str] | None = None,
) -> set[str] | None:
    """Return desktop SQLite revision rows, or ``None`` for an unversioned DB."""
    db_path = ensure_desktop_dirs(data_dir)["data"] / "xcagi.db"
    if not db_path.exists() or db_path.stat().st_size == 0:
        return set()
    with sqlite3.connect(db_path) as conn:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='alembic_version'"
        ).fetchone()
        if not exists:
            return None
        rows = conn.execute("SELECT version_num FROM alembic_version").fetchall()
    return {str(row[0]) for row in rows if row and row[0]}


def migration_required(data_dir: str | os.PathLike[str] | None = None) -> bool:
    """Return whether the packaged desktop schema is behind the bundled head."""
    configure_desktop_environment(data_dir)
    if _should_bootstrap_sqlite(data_dir):
        return True
    current = _sqlite_current_revisions(data_dir)
    if current is None:
        return True
    known, heads = _script_revisions()
    return bool(current - known) or current != heads


def _run_alembic_cli(*args: str) -> None:
    cfg = _alembic_config()
    ini = Path(cfg.config_file_name or "")
    root = ini.parent
    # PyInstaller 入口不支持 ``exe -m alembic``（参数会进 run_fastapi argparse），须走 API。
    if getattr(sys, "frozen", False):
        from alembic import command

        op = args[0] if args else ""
        target = next((arg for arg in args[1:] if not arg.startswith("--")), "head")
        if op == "upgrade":
            command.upgrade(cfg, target)
        elif op == "stamp":
            command.stamp(cfg, target, purge="--purge" in args)
        else:
            raise ValueError(f"unsupported alembic op: {args!r}")
        return
    cmd = [sys.executable, "-m", "alembic", "-c", str(ini), *args]
    subprocess.run(cmd, check=True, cwd=str(root))


def run_alembic_upgrade(
    data_dir: str | os.PathLike[str] | None = None, version: str = "head"
) -> None:
    configure_desktop_environment(data_dir)
    if _should_bootstrap_sqlite(data_dir):
        bootstrap_sqlite_schema(data_dir)
        _run_alembic_cli("stamp", "head")
        return
    current = _sqlite_current_revisions(data_dir)
    known, _heads = _script_revisions()
    if current is None or current - known:
        # Desktop SQLite historically used create_all without Alembic tracking.
        # Re-baseline the already-existing schema, then replay the idempotent
        # post-baseline migrations so newly added columns are not skipped.
        _run_alembic_cli("stamp", "--purge", "2026_06_22_baseline")
    _run_alembic_cli("upgrade", version)


def _should_bootstrap_sqlite(data_dir: str | os.PathLike[str] | None = None) -> bool:
    db_path = ensure_desktop_dirs(data_dir)["data"] / "xcagi.db"
    if not db_path.exists() or db_path.stat().st_size == 0:
        return True
    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "select name from sqlite_master where type='table' and name not like 'sqlite_%'"
            ).fetchall()
        return not rows
    except sqlite3.DatabaseError:
        return True


def bootstrap_sqlite_schema(data_dir: str | os.PathLike[str] | None = None) -> None:
    configure_desktop_environment(data_dir)
    # Import model modules so Base.metadata contains the full schema.
    import app.db.models  # noqa: F401
    from app.db import dispose_and_recreate_engine, engine
    from app.db.base import Base

    dispose_and_recreate_engine()
    Base.metadata.create_all(bind=engine)


def export_config(data_dir: str | os.PathLike[str] | None = None) -> dict[str, str]:
    dirs = ensure_desktop_dirs(data_dir)
    config = {
        "data_dir": str(dirs["root"]),
        "database": str(dirs["data"] / "xcagi.db"),
        "mods": str(dirs["mods"]),
        "models": str(dirs["models"]),
    }
    return config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="XCAGI desktop migration helper")
    parser.add_argument("--data-dir", default=os.environ.get("XCAGI_DATA_DIR"))
    parser.add_argument("--backup", action="store_true")
    parser.add_argument("--upgrade", default="")
    parser.add_argument("--export-config", action="store_true")
    parser.add_argument("--version", default=os.environ.get("XCAGI_VERSION", "unknown"))
    args = parser.parse_args(argv)

    configure_desktop_environment(args.data_dir)
    if args.backup:
        backup = backup_database(args.data_dir, args.version)
        if backup:
            print(str(backup))
    if args.upgrade:
        run_alembic_upgrade(args.data_dir, args.upgrade)
    if args.export_config:
        print(json.dumps(export_config(args.data_dir), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
