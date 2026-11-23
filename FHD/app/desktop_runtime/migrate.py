"""Desktop data backup and migration entry points."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Iterator

from app.utils.process_lock import exclusive_file_lock
from app.utils.time import utc_now_naive

from .backup_retention import cleanup_local_backups
from .database_profile import configured_remote_database_url
from .db import check_database as _check_database
from .db import integrity_check_ok as _integrity_check_ok
from .desktop_runtime_paths import (
    clear_database_recovery_marker,
    configure_desktop_environment,
    ensure_desktop_dirs,
    mark_database_recovery_required,
)

logger = logging.getLogger(__name__)

# 启动自检：磁盘剩余空间低于此阈值（字节）时记录警告，但不阻塞启动。
_MIN_DISK_FREE_BYTES = 500 * 1024 * 1024  # 500 MB

# 迁移互斥：两个后端进程（或后端 + ``--migrate-only`` CLI）并发迁移同一个
# SQLite 库会交叉 Alembic 事务、互相覆盖备份，必须串行化。锁由操作系统在
# 进程退出时释放，不会遗留死锁；超时则失败退出，不静默带病迁移。
_MIGRATION_LOCK_NAME = ".xcagi-migration.lock"
_MIGRATION_LOCK_TIMEOUT_SECONDS = 600.0


def _quick_check_ok(path: Path) -> bool:
    """Compatibility query; recovery uses the non-boolean check result directly."""
    return _check_database(path).state == "healthy"


@contextmanager
def migration_lock(data_dir: str | os.PathLike[str] | None = None) -> Iterator[None]:
    """串行化同一 data_dir 下的 schema 迁移与迁移前备份。"""
    lock_dir = ensure_desktop_dirs(data_dir)["data"]
    with exclusive_file_lock(
        lock_dir / _MIGRATION_LOCK_NAME,
        blocking=True,
        timeout=_MIGRATION_LOCK_TIMEOUT_SECONDS,
        reject_symlink=True,
    ):
        yield


def backup_database(
    data_dir: str | os.PathLike[str] | None = None, version: str = "unknown"
) -> Path | None:
    """使用 sqlite3.backup() API 做在线热备份，业务在跑也能备份。

    shutil.copy2 是文件级拷贝，SQLite 在写入时被拷会得到不一致的库。
    sqlite3.backup() 是 SQLite 官方推荐的在线热备份 API，会处理 WAL
    文件合并，保证备份出来的库是一致的。备份后跑 integrity_check 校验，
    校验失败删除备份文件并返回 None。
    """
    if configured_remote_database_url(data_dir):
        raise RuntimeError("remote PostgreSQL requires the server backup workflow")
    dirs = ensure_desktop_dirs(data_dir)
    db = dirs["data"] / "xcagi.db"
    if not db.exists():
        return None
    if version in {"", "unknown", "startup"}:
        from app.build_identity import build_identity

        version = build_identity().get("product_version") or version or "unknown"
    stamp = utc_now_naive().strftime("%Y%m%d%H%M%S")
    with tempfile.NamedTemporaryFile(
        dir=dirs["backups"], prefix=f"xcagi-{version}-{stamp}-", suffix=".db", delete=False
    ) as snapshot:
        target = Path(snapshot.name)

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
            except OSError as cleanup_exc:
                logger.debug("failed to remove partial backup %s: %s", target, cleanup_exc)
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
        except OSError as cleanup_exc:
            logger.debug("failed to remove invalid backup %s: %s", target, cleanup_exc)
        return None

    # Age-only retention is unsafe for multi-gigabyte desktop databases. Prune
    # immediately after every successful backup, including updater migration
    # snapshots, while explicitly protecting the just-validated recovery point.
    cleanup_local_backups(dirs["backups"], protected=(target,))
    return target


def recover_if_corrupt(
    data_dir: str | os.PathLike[str] | None = None,
) -> dict[str, str]:
    """启动自检 + 自动恢复。

    流程：
    1. 检查磁盘剩余空间，低于阈值记录警告（不阻塞）。
    2. 对主库 xcagi.db 跑 PRAGMA quick_check。
    3. 如果损坏：把坏库改名为 .corrupt-{timestamp} 留证据；
       扫描 backups/ 按时间倒序找第一个通过 integrity_check 的备份恢复。
    4. 返回 {"action": "ok"|"restored"|"corrupt_no_backup"|"skipped"|"unavailable",
            "detail": str}

    库正常时返回 action=ok，不做任何操作。
    库损坏且能恢复时返回 action=restored，detail 是恢复来源文件名。
    库损坏但没备份时返回 action=corrupt_no_backup，调用方应决定是否阻塞启动。
    锁定或不可读时返回 unavailable，原库与备份均保持不变。
    主库不存在（首启）时返回 action=skipped。
    """
    # Startup self-check runs before Alembic; share its existing reentrant lock
    # so another startup/migration cannot replace the image being inspected.
    try:
        with migration_lock(data_dir):
            return _recover_if_corrupt_locked(data_dir)
    except (OSError, sqlite3.Error) as exc:
        # Lock or storage access may fail before any corruption is established.
        # That cannot create a persistent corruption marker or authorize restore.
        logger.warning("database recovery check unavailable: %s", exc)
        return {"action": "unavailable", "detail": f"recovery check failed: {exc}"}


def _recover_if_corrupt_locked(data_dir: str | os.PathLike[str] | None) -> dict[str, str]:
    dirs = ensure_desktop_dirs(data_dir)
    db = dirs["data"] / "xcagi.db"

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

    # An inconclusive check cannot authorize replacing committed customer data.
    health = _check_database(db)
    if health.state == "healthy":
        return {"action": "ok", "detail": ""}
    if health.state == "unavailable":
        logger.warning("database check unavailable; preserving database: %s", health.detail)
        return {"action": "unavailable", "detail": health.detail}

    try:
        return _restore_corrupt_database(dirs)
    except (OSError, sqlite3.Error) as exc:
        # Corruption is now established. Keep its durable warning if quarantine,
        # backup enumeration or publication cannot complete under the same lock.
        logger.error("database recovery could not complete safely: %s", exc)
        return {"action": "corrupt_no_backup", "detail": f"recovery failed: {exc}"}


def _restore_corrupt_database(dirs: dict[str, Path]) -> dict[str, str]:
    db = dirs["data"] / "xcagi.db"
    backups_dir = dirs["backups"]
    # 4) 库损坏：改名留证据
    logger.error("database corrupt: %s, attempting recovery from backups", db)
    # A crash after quarantine must not make the next startup treat the missing
    # database as a first install. Keep the existing persistent warning until
    # the replacement has been verified and published under this same lock.
    mark_database_recovery_required(dirs["root"])
    stamp = utc_now_naive().strftime("%Y%m%d%H%M%S")
    corrupt_path = db.with_name(f"xcagi.db.corrupt-{stamp}")
    # Windows rename refuses an existing target; a second corruption within the
    # same second must keep both copies as evidence instead of aborting recovery.
    sidecars = ("", "-wal", "-shm", "-journal")
    suffix = 1
    while any(os.path.lexists(f"{corrupt_path}{extension}") for extension in sidecars):
        corrupt_path = db.with_name(f"xcagi.db.corrupt-{stamp}-{suffix}")
        suffix += 1
    try:
        # A crashed WAL/rollback journal belongs to the damaged image. Reusing
        # it with the replacement can silently overwrite the restored snapshot.
        for extension in sidecars:
            original = Path(f"{db}{extension}")
            if os.path.lexists(original):
                original.rename(Path(f"{corrupt_path}{extension}"))
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
        published = False
        try:
            # Stage a complete SQLite snapshot (including any committed WAL),
            # verify that exact image, then publish it on the same filesystem.
            with tempfile.TemporaryDirectory(prefix="xcagi-recovery-", dir=db.parent) as work:
                restored = Path(work) / "restored.db"
                with (
                    closing(
                        sqlite3.connect(candidate.resolve().as_uri() + "?mode=ro", uri=True)
                    ) as source,
                    closing(sqlite3.connect(restored)) as target,
                ):
                    source.backup(target)
                    if (
                        target.execute(
                            "SELECT 1 FROM sqlite_schema WHERE type = 'table' "
                            "AND name NOT GLOB 'sqlite_*' LIMIT 1"
                        ).fetchone()
                        is None
                    ):
                        logger.warning(
                            "skipping empty backup without database tables: %s", candidate
                        )
                        continue
                if not _integrity_check_ok(restored):
                    logger.error("restored snapshot failed integrity check: %s", candidate)
                    continue
                shutil.copystat(candidate, restored)
                restored.replace(db)
                published = True
            if not clear_database_recovery_marker(dirs["root"]):
                return {"action": "corrupt_no_backup", "detail": "recovery marker cleanup failed"}
            logger.info("restored db from backup: %s", candidate.name)
            return {"action": "restored", "detail": candidate.name}
        except (OSError, sqlite3.Error) as exc:
            logger.error("restore from %s failed: %s", candidate, exc)
            if published:
                return {"action": "corrupt_no_backup", "detail": f"restore cleanup failed: {exc}"}
            continue

    # 6) 所有备份都不行——主库已被改名，需要调用方决定是否阻塞启动
    logger.error("all backups failed integrity check or restore")
    return {"action": "corrupt_no_backup", "detail": "no usable backup"}


def _alembic_root() -> Path:
    """Resolve directory containing alembic.ini (PyInstaller _MEIPASS or FHD repo root)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path.cwd()))
    return Path(__file__).resolve().parents[2]


def _resolve_alembic_ini() -> Path:
    root = _alembic_root()
    ini = root / "alembic.ini"
    # Older/broken PyInstaller trees nested the file as alembic.ini/alembic.ini.
    if not ini.is_file() and (root / "alembic.ini" / "alembic.ini").is_file():
        ini = root / "alembic.ini" / "alembic.ini"
    return ini


def _run_alembic_cli(*args: str) -> None:
    ini = _resolve_alembic_ini()
    if not ini.is_file():
        raise FileNotFoundError(f"alembic.ini not found: {ini}")
    root = ini.parent
    # PyInstaller 入口不支持 ``exe -m alembic``（参数会进 run_fastapi argparse），须走 API。
    if getattr(sys, "frozen", False):
        from alembic.config import Config

        from alembic import command

        cfg = Config(str(ini))
        op = args[0] if args else ""
        target = args[1] if len(args) > 1 else "head"
        if op == "upgrade":
            command.upgrade(cfg, target)
        elif op == "stamp":
            command.stamp(cfg, target)
        else:
            raise ValueError(f"unsupported alembic op: {args!r}")
        return
    cmd = [sys.executable, "-m", "alembic", "-c", str(ini), *args]
    subprocess.run(cmd, check=True, cwd=str(root))


# 仓库迁移脚本命名规范：YYYY_MM_DD_<slug>（见 alembic/versions/）。
_REVISION_DATE_RE = re.compile(r"^(\d{4}_\d{2}_\d{2})_")


def _read_stamped_revision(db_path: Path) -> str | None:
    """读取 alembic_version 中的当前版本戳；表缺失或为空返回 None。"""
    conn = None
    try:
        conn = sqlite3.connect(str(db_path))
        row = conn.execute("select version_num from alembic_version").fetchone()
    except sqlite3.Error:
        return None
    finally:
        if conn is not None:
            conn.close()
    return row[0] if row and row[0] else None


def _known_alembic_revisions() -> set[str]:
    """当前包迁移链中的全部 revision id（ScriptDirectory 解析，不依赖数据库）。"""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    ini = _resolve_alembic_ini()
    if not ini.is_file():
        raise FileNotFoundError(f"alembic.ini not found: {ini}")
    script = ScriptDirectory.from_config(Config(str(ini)))
    return {rev.revision for rev in script.walk_revisions()}


def _pick_recovery_revision(stamped: str, known: frozenset[str] | set[str]) -> str:
    """为链外版本戳选择恢复点。

    启发式：revision id 前缀是日期（YYYY_MM_DD）。取已知链中日期 <= 丢失戳
    日期的最近一个，尽量少重放迁移；解析不出日期或没有更早节点时退回链中
    最早的日期节点（迁移普遍用 if_not_exists / add_column_if_missing 写法，
    重放幂等）。
    """
    dated: list[tuple[str, str]] = []
    for rev in known:
        match = _REVISION_DATE_RE.match(rev)
        if match:
            dated.append((match.group(1), rev))
    if not dated:
        raise RuntimeError(
            f"cannot recover unknown alembic revision {stamped!r}: "
            "packaged chain has no date-prefixed revisions"
        )
    dated.sort()
    stamped_match = _REVISION_DATE_RE.match(stamped)
    if stamped_match:
        candidates = [rev for key, rev in dated if key <= stamped_match.group(1)]
        if candidates:
            return candidates[-1]
    return dated[0][1]


def _restamp_direct(db_path: Path, target: str) -> None:
    """直接覆写 alembic_version 表。

    不能走 ``alembic stamp``：该命令在线模式下会先解析当前版本戳，
    当前戳本身就是链外未知 revision 时同样抛 ``Can't locate revision``
    （2026-09-03 E2E 实测）。桌面端是单行线性链，覆写等价于 stamp。
    """
    conn = None
    try:
        conn = sqlite3.connect(str(db_path))
        with conn:
            conn.execute("delete from alembic_version")
            conn.execute("insert into alembic_version (version_num) values (?)", (target,))
    finally:
        if conn is not None:
            conn.close()
    logger.warning("alembic version table rewritten to %s", target)


def repair_unknown_stamped_revision(
    data_dir: str | os.PathLike[str] | None = None,
) -> dict[str, str] | None:
    """升级前兜底：库内版本戳不在当前包迁移链中时自动修复。

    背景：桌面端已发布迁移是不可变契约；历史上 squash/删迁移导致已装用户库
    的 alembic_version 指向链外 revision，upgrade 直接抛
    ``Can't locate revision`` 中断自动更新（2026-09-03 实测事故，
    丢失节点 2026_08_24_erp_hr_attendance）。
    处理：先做在线热备份留恢复点，再按日期启发式把戳重打到链内最近祖先。
    库内戳合法（或无 alembic_version）时不做任何操作，返回 None。
    """
    dirs = ensure_desktop_dirs(data_dir)
    db = dirs["data"] / "xcagi.db"
    if not db.exists():
        return None
    stamped = _read_stamped_revision(db)
    if not stamped:
        return None
    known = _known_alembic_revisions()
    if stamped in known:
        return None
    # 库内戳比当前包的迁移链更新：说明该库来自更新版本的安装包。
    # 此时把它回退（restamp）到旧链头会导致后续升级重复/漏跑迁移，
    # 必须保持原戳并跳过 upgrade，等用户装回较新版本时再继续。
    stamped_date = _REVISION_DATE_RE.match(stamped)
    dated_known = [
        (match.group(1), rev) for rev in known if (match := _REVISION_DATE_RE.match(rev))
    ]
    if stamped_date and dated_known:
        newest_date, newest_rev = max(dated_known)
        if stamped_date.group(1) > newest_date:
            logger.warning(
                "alembic revision %s is newer than packaged chain head %s; "
                "keeping stamp and skipping upgrade instead of downgrading",
                stamped,
                newest_rev,
            )
            return {"action": "newer_than_package", "from": stamped, "to": newest_rev}
    target = _pick_recovery_revision(stamped, known)
    logger.warning(
        "alembic revision %s missing from packaged chain; "
        "snapshotting database and restamping to %s before upgrade",
        stamped,
        target,
    )
    backup_database(data_dir, version="pre-revfix")
    _restamp_direct(db, target)
    logger.warning(
        "alembic version restamped %s -> %s; upgrade will replay migrations from there",
        stamped,
        target,
    )
    return {"from": stamped, "to": target}


def run_alembic_upgrade(
    data_dir: str | os.PathLike[str] | None = None, version: str = "heads"
) -> None:
    configure_desktop_environment(data_dir)
    _require_local_migration(data_dir)
    # 迁移会改写 schema 契约，必须与并发启动的其它进程互斥（见 migration_lock）。
    with migration_lock(data_dir):
        if _should_bootstrap_sqlite(data_dir):
            bootstrap_sqlite_schema(data_dir)
            _run_alembic_cli("stamp", "heads")
            return
        repair = repair_unknown_stamped_revision(data_dir)
        if repair and repair.get("action") == "newer_than_package":
            logger.warning(
                "skip alembic upgrade: database stamped %s belongs to a newer build "
                "than this package (packaged head %s)",
                repair.get("from"),
                repair.get("to"),
            )
            return
        heads = _known_alembic_heads()
        if len(heads) > 1:
            logger.warning(
                "alembic has %d heads (%s); upgrading all of them instead of a single head",
                len(heads),
                ", ".join(sorted(heads)),
            )
        _run_alembic_cli("upgrade", version)


def _known_alembic_heads() -> list[str]:
    """当前包迁移链的 head 列表；多 head 时由 upgrade 一次性合并推进。"""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    ini = _resolve_alembic_ini()
    if not ini.is_file():
        raise FileNotFoundError(f"alembic.ini not found: {ini}")
    return list(ScriptDirectory.from_config(Config(str(ini))).get_heads())


def _current_head_revision() -> str | None:
    """当前包迁移链的 head revision（ScriptDirectory 解析，不依赖数据库）。

    多 head 分支并存时返回第一个 head；调用方如需严格单 head 请用 get_heads()。
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    ini = _resolve_alembic_ini()
    if not ini.is_file():
        raise FileNotFoundError(f"alembic.ini not found: {ini}")
    script = ScriptDirectory.from_config(Config(str(ini)))
    heads = script.get_heads()
    return heads[0] if heads else None


def is_schema_current(data_dir: str | os.PathLike[str] | None = None) -> bool | None:
    """判断存量库 schema 是否已在 head。

    返回 True 表示已在 head（可零开销跳过）；False 表示需要升级（含首启、
    链外版本戳待修复、版本戳缺失三种情况，均交给 run_alembic_upgrade 处理）。
    """
    if configured_remote_database_url(data_dir):
        return _remote_schema_is_current()
    dirs = ensure_desktop_dirs(data_dir)
    db = dirs["data"] / "xcagi.db"
    if not db.exists() or db.stat().st_size == 0:
        return False
    stamped = _read_stamped_revision(db)
    if not stamped:
        return False
    if stamped not in _known_alembic_revisions():
        return False
    # 多 head 分支并存时，只要 stamp 在任一 head 上即视为 current，避免启动即崩。
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    ini = _resolve_alembic_ini()
    if ini.is_file():
        script = ScriptDirectory.from_config(Config(str(ini)))
        heads = script.get_heads()
        if stamped in heads:
            return True
    return stamped == _current_head_revision()


def _remote_schema_is_current() -> bool:
    """Inspect the shared schema without bootstrapping, restamping or migrating it."""
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy.exc import SQLAlchemyError

    from app.db import get_host_engine

    try:
        with get_host_engine().connect() as connection:
            current = set(MigrationContext.configure(connection).get_current_heads())
    except SQLAlchemyError as exc:
        raise RuntimeError(
            "remote PostgreSQL schema unavailable; refusing desktop startup"
        ) from exc
    return current == set(_known_alembic_heads())


def _require_local_migration(data_dir: str | os.PathLike[str] | None) -> None:
    if configured_remote_database_url(data_dir):
        raise RuntimeError(
            "remote PostgreSQL requires the explicit server migration workflow; "
            "desktop bootstrap, restamp and local backup are not applicable"
        )
    if os.environ.get("XCAGI_DESKTOP_DB_RECOVERY") in {"unavailable", "corrupt_no_backup"}:
        raise RuntimeError("desktop database recovery is unresolved; refusing migration")


def ensure_startup_migration(
    data_dir: str | os.PathLike[str] | None = None, version: str = "startup"
) -> dict[str, str]:
    """桌面每次启动的 schema 兜底：已在 head 直接跳过，否则热备份后补迁移。

    背景：Electron 仅在更新安装流程执行 ``--migrate-only``；常规启动从不
    迁移。存量库停在旧迁移版本时，新代码按新 ORM 查询即 500（2026-09-10
    实测：老库缺 ``products.base_uom_id`` / ``inventory_transactions.ordered_quantity``
    导致产品/库存页整页不可用）。

    失败时抛出异常让调用方（run_fastapi / Electron）捕获退出码引导用户，
    而不是带病启动后静默 500。
    """
    configure_desktop_environment(data_dir)
    if configured_remote_database_url(data_dir):
        if not _remote_schema_is_current():
            raise RuntimeError(
                "remote PostgreSQL schema requires explicit server migration; refusing desktop startup"
            )
        return {"action": "skipped", "detail": "remote schema already at head"}
    _require_local_migration(data_dir)
    if is_schema_current(data_dir):
        return {"action": "skipped", "detail": "schema already at head"}
    with migration_lock(data_dir):
        # 拿到锁后再确认一次：并发启动的另一个进程可能刚完成迁移，无需重复备份。
        if is_schema_current(data_dir):
            return {"action": "skipped", "detail": "schema already at head"}
        dirs = ensure_desktop_dirs(data_dir)
        db = dirs["data"] / "xcagi.db"
        if db.exists() and db.stat().st_size > 0:
            backup = backup_database(data_dir, os.environ.get("XCAGI_VERSION", version))
            if backup is None:
                # 与 --migrate-only 的备份门禁保持一致：宁可不启动，不做无备份迁移
                raise RuntimeError("migration backup failed; refusing to continue")
        run_alembic_upgrade(data_dir)
    return {"action": "upgraded", "detail": "schema migrated at startup"}


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
    _require_local_migration(data_dir)
    # Import model modules so Base.metadata contains the full schema.
    import app.db.models  # noqa: F401
    from app.db import dispose_and_recreate_engine, get_runtime_engine
    from app.db.db_base import Base

    dispose_and_recreate_engine()
    Base.metadata.create_all(bind=get_runtime_engine())


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
