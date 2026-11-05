"""Legacy observations and explicit fresh-owner SQLite source epochs.

Observations never authorize execution. Only newly created owned sources can use
the original-epoch protocol with target ownership and a durable worker lease.
Existing shared databases, receipts and old executables are never adopted.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import sys
import tempfile
from contextlib import ExitStack, closing, contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import UUID, uuid4


class GenerationObservationError(RuntimeError):
    """An identity or authorization could not be established."""


@dataclass(frozen=True)
class GenerationObservation:
    user_id: str
    tenant_id: str
    mod_id: str
    generation: str
    path_digest: str
    device: int
    inode: int


def _main_file(db: sqlite3.Connection) -> tuple[str, int, int]:
    rows = db.execute("PRAGMA database_list").fetchall()
    main = [row[2] for row in rows if row[1] == "main"]
    if len(main) != 1 or not main[0]:
        raise GenerationObservationError("ordinary file database required")
    path = Path(main[0])
    info = path.lstat()
    if not path.is_absolute() or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise GenerationObservationError("database path is not a regular unlinked file")
    return str(path.resolve(strict=True)), info.st_dev, info.st_ino


def _generation(db: sqlite3.Connection) -> str:
    # Provisioning is intentionally separate. Never infer or create a generation.
    rows = db.execute("SELECT generation_id FROM main.etl_database_generation").fetchall()
    if len(rows) != 1 or not isinstance(rows[0][0], str):
        raise GenerationObservationError("database generation is unavailable")
    value = rows[0][0]
    parsed = UUID(value)
    if parsed.version != 4 or str(parsed) != value:
        raise GenerationObservationError("database generation is invalid")
    return value


def _scope(context: dict) -> tuple[str, str, str]:
    from app.infrastructure.auth.agent_mod_scope import validate_actor_context
    from app.request_active_mod_ctx import normalize_active_mod_id

    if validate_actor_context(context) is not None:
        raise GenerationObservationError("actor authorization is unavailable")
    user, tenant, mod = context.get("user_id"), context.get("tenant_id"), context.get("mod_id")
    if (
        not isinstance(user, str)
        or not user.isdecimal()
        or int(user) <= 0
        or not isinstance(tenant, str)
        or not tenant.isdecimal()
        or int(tenant) <= 0
        or not isinstance(mod, str)
        or not mod
        or normalize_active_mod_id(mod) != mod
    ):
        raise GenerationObservationError("actor or Mod scope is unavailable")
    return user, tenant, mod


def _validate_registry(db: sqlite3.Connection) -> None:
    columns = db.execute('PRAGMA main.table_xinfo("etl_generation_observations")').fetchall()
    expected = [
        ("user_id", "TEXT", 1, 1),
        ("tenant_id", "TEXT", 1, 2),
        ("mod_id", "TEXT", 1, 3),
        ("generation", "TEXT", 1, 0),
        ("path_digest", "TEXT", 1, 0),
        ("device", "INTEGER", 1, 0),
        ("inode", "INTEGER", 1, 0),
    ]
    if (
        [(row[1], row[2].upper(), row[3], row[5]) for row in columns] != expected
        or any(row[4] is not None or row[6] != 0 for row in columns)
        or db.execute('PRAGMA main.foreign_key_list("etl_generation_observations")').fetchall()
    ):
        raise GenerationObservationError("host observation schema is incompatible")
    indexes = db.execute('PRAGMA main.index_list("etl_generation_observations")').fetchall()
    if len(indexes) != 1 or indexes[0][2:5] != (1, "pk", 0):
        raise GenerationObservationError("host observation schema is incompatible")
    quoted_index = '"' + indexes[0][1].replace('"', '""') + '"'
    key_columns = [row for row in db.execute(f"PRAGMA main.index_xinfo({quoted_index})") if row[5]]
    if [(row[2], row[3], row[4]) for row in key_columns] != [
        ("user_id", 0, "BINARY"),
        ("tenant_id", 0, "BINARY"),
        ("mod_id", 0, "BINARY"),
    ]:
        raise GenerationObservationError("host observation schema is incompatible")
    definition = db.execute(
        "SELECT sql FROM main.sqlite_master WHERE type='table' AND name=?",
        ("etl_generation_observations",),
    ).fetchone()
    if not definition or re.search(
        r"\bCHECK\s*\(|\bON\s+CONFLICT\b", definition[0] or "", re.IGNORECASE
    ):
        raise GenerationObservationError("host observation schema is incompatible")
    objects = db.execute(
        "SELECT name FROM main.sqlite_master WHERE type='trigger' AND tbl_name=? "
        "UNION ALL SELECT name FROM temp.sqlite_master WHERE "
        "(type='trigger' AND tbl_name=?) OR (type='table' AND name=?) LIMIT 1",
        ("etl_generation_observations",) * 3,
    ).fetchone()
    if objects:
        raise GenerationObservationError("host observation schema is incompatible")


def observe_generation(
    host: sqlite3.Connection, target: sqlite3.Connection, context: dict
) -> GenerationObservation:
    """Record a first observation or require the exact previously recorded tuple.

    Both arguments must be private connections with no active transaction. The
    target marker comes from the target connection itself. This is not proof of
    deployment fencing, atomicity with target writes, or a valid execution receipt.
    """
    started = False
    try:
        user, tenant, mod = _scope(context)
        if host.in_transaction or target.in_transaction:
            raise GenerationObservationError("private idle connections required")
        host_file, target_file = _main_file(host), _main_file(target)
        if host_file[1:] == target_file[1:]:
            raise GenerationObservationError("host and business databases must be separate")
        generation = _generation(target)
        identity = GenerationObservation(
            user,
            tenant,
            mod,
            generation,
            hashlib.sha256(os.fsencode(target_file[0])).hexdigest(),
            target_file[1],
            target_file[2],
        )
        host.execute("BEGIN IMMEDIATE")
        started = True
        _validate_registry(host)
        existing = host.execute(
            "SELECT generation, path_digest, device, inode FROM main.etl_generation_observations "
            "WHERE user_id=? AND tenant_id=? AND mod_id=?",
            (user, tenant, mod),
        ).fetchone()
        expected = (identity.generation, identity.path_digest, identity.device, identity.inode)
        if existing is None:
            host.execute(
                "INSERT INTO main.etl_generation_observations "
                "(user_id,tenant_id,mod_id,generation,path_digest,device,inode) VALUES (?,?,?,?,?,?,?)",
                (user, tenant, mod, *expected),
            )
        elif tuple(existing) != expected:
            raise GenerationObservationError("observed generation or database file changed")
        if (
            _main_file(host) != host_file
            or _main_file(target) != target_file
            or _generation(target) != generation
        ):
            raise GenerationObservationError("database changed during observation")
        host.commit()
        return identity
    except (sqlite3.Error, OSError, ValueError, GenerationObservationError) as exc:
        if started and host.in_transaction:
            host.rollback()
        if isinstance(exc, GenerationObservationError):
            raise
        raise GenerationObservationError("generation observation unavailable") from None


# V1 only invalidates trust; V2 is reserved for explicitly enrolled fresh sources.
# The permanent cooperative lock is separate from the atomically replaced JSON.
_active_restores: ContextVar[frozenset[str]] = ContextVar(
    "etl_active_restore_epochs", default=frozenset()
)


def _sync_epoch_directory(path: Path):
    # Windows directory power-loss durability is not established by this stage.
    if os.name != "nt":
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _ensure_epoch_directory(path: Path):
    if not path.parent.exists():
        _ensure_epoch_directory(path.parent)
    path.mkdir(exist_ok=True, mode=0o700)
    if not stat.S_ISDIR(path.lstat().st_mode):
        raise GenerationObservationError("recovery control directory is not regular")
    # Also sync a concurrently created directory's entry before trusting it.
    _sync_epoch_directory(path.parent)


def _epoch_paths(target: Path, data_root, *, create: bool):
    from app.desktop_runtime.desktop_runtime_paths import get_desktop_data_dir

    if not isinstance(target, Path) or not target.is_absolute():
        raise GenerationObservationError("absolute recovery target required")
    # data_root is selected by host bootstrap/configuration, never a receipt or request.
    root = get_desktop_data_dir(data_root)
    if _owned_profile is not None and root != _owned_profile[0]:
        raise GenerationObservationError("host lifecycle root differs from the factory profile")
    directory = root / "config" / "etl-recovery"
    try:
        target_info = target.lstat()
    except FileNotFoundError:
        pass  # A missing target may be restored, but is never adopted as trusted.
    else:
        if not stat.S_ISREG(target_info.st_mode) or target_info.st_nlink != 1:
            raise GenerationObservationError("recovery target must be one regular file")
    target = target.resolve()
    if target.is_relative_to(root / "config"):
        raise GenerationObservationError("recovery target overlaps control state")
    for folder in (root, root / "config", directory):
        if create:
            _ensure_epoch_directory(folder)
        info = folder.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise GenerationObservationError("recovery control directory is not regular")
    key = hashlib.sha256(os.fsencode(os.path.normcase(str(target)))).hexdigest()
    return directory / (key + ".json"), directory / (key + ".lock"), key


def _read_closed_epoch(path: Path, key: str) -> dict | None:
    def pairs(rows):
        result = {}
        for name, value in rows:
            if name in result:
                raise ValueError("duplicate recovery field")
            result[name] = value
        return result

    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise GenerationObservationError("recovery epoch file is not regular")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        return None
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        if (before.st_dev, before.st_ino) != (info.st_dev, info.st_ino) or info.st_size > 4096:
            raise GenerationObservationError("recovery epoch file is not regular")
        raw = source.read(4097)
    value = json.loads(raw, object_pairs_hook=pairs)
    if isinstance(value, dict) and value.get("version") == 2:
        _owned_record(value, key)
        return value
    if (
        len(raw) > 4096
        or not isinstance(value, dict)
        or set(value) != {"version", "state", "target_path_digest", "epoch", "previous_epoch"}
        or type(value["version"]) is not int
        or value["version"] != 1
        or value["state"] != "closed"
        or value["target_path_digest"] != key
    ):
        raise GenerationObservationError("recovery epoch is unavailable")
    for field in ("epoch", "previous_epoch"):
        marker = value[field]
        if field == "previous_epoch" and marker is None:
            continue
        if not isinstance(marker, str) or str(UUID(marker)) != marker or UUID(marker).version != 4:
            raise GenerationObservationError("invalid recovery epoch")
    return value


def read_recovery_epoch(target: Path, *, data_root=None) -> dict:
    """Read an existing CLOSED marker; absence never initializes or adopts a store."""
    try:
        path, _lock, key = _epoch_paths(target, data_root, create=False)
        value = _read_closed_epoch(path, key)
        if value is None:
            raise GenerationObservationError("recovery epoch is absent")
        return value
    except (OSError, ValueError) as exc:
        raise GenerationObservationError("recovery epoch unavailable") from exc


@contextmanager
def target_database_lock(target: Path, *, data_root=None, lock_timeout=0):
    """Cooperative target ownership, shared by participating SQL and restores.

    Control paths come only from trusted host configuration. The lock is permanent;
    unlike the epoch JSON it must never be replaced. It does not fence old writers.
    """
    from app.utils.process_lock import exclusive_file_lock

    if (
        isinstance(lock_timeout, bool)
        or not isinstance(lock_timeout, (int, float))
        or not 0 <= lock_timeout <= 5
    ):
        raise GenerationObservationError("invalid bounded target wait")
    with ExitStack() as stack:
        try:
            path, lock, key = _epoch_paths(target, data_root, create=True)
            if str(lock) in _active_restores.get():
                raise GenerationObservationError("recursive target ownership is unavailable")
            if lock.exists() or lock.is_symlink():
                info = lock.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise GenerationObservationError("recovery lock is not regular")
            stack.enter_context(
                exclusive_file_lock(
                    lock, blocking=lock_timeout > 0, timeout=lock_timeout, reject_symlink=True
                )
            )
        except (OSError, ValueError) as exc:
            raise GenerationObservationError("target ownership unavailable") from exc
        token = _active_restores.set(_active_restores.get() | {str(lock)})
        try:
            yield path, key
        finally:
            _active_restores.reset(token)


@contextmanager
def legacy_sql_write_guard(target: Path):
    """Compatibility only: absence permits ordinary writes, never recovery trust.

    Any existing marker, including a modern OPEN marker, blocks legacy writes;
    unconverted writers remain outside this boundary.
    The caller must finish commit/rollback before releasing this guard.
    """
    with target_database_lock(target) as (path, key):
        try:
            _require_no_restore_intent(path)
            if _read_closed_epoch(path, key) is not None:
                raise GenerationObservationError("target is closed for recovery")
        except (OSError, ValueError) as exc:
            raise GenerationObservationError("recovery epoch unavailable") from exc
        yield "legacy-unverified"


@contextmanager
def close_generation_for_restore(target: Path, *, data_root=None):
    """Rotate CLOSED before mutation while excluding participating Batch SQL.

    First use does not adopt a database or receipt. Success remains closed.
    Other writers and desktop rollback helpers are NOT yet fenced.
    """
    try:
        with target_database_lock(target, data_root=data_root) as (path, key):
            _require_no_restore_intent(path)
            previous = _read_closed_epoch(path, key)
            if previous and previous["version"] == 2:
                raise GenerationObservationError("owned source requires its bound restore protocol")
            value = {
                "version": 1,
                "state": "closed",
                "target_path_digest": key,
                "epoch": str(uuid4()),
                "previous_epoch": previous["epoch"] if previous else None,
            }
            _publish_epoch(path, value)
            yield value
    except (OSError, ValueError) as exc:
        raise GenerationObservationError("recovery epoch could not be closed") from exc


def _restore_intent_path(epoch_path: Path) -> Path:
    return epoch_path.with_suffix(".restore-intent.json")


def _require_no_restore_intent(epoch_path: Path):
    try:
        _restore_intent_path(epoch_path).lstat()
    except FileNotFoundError:
        return
    # Even partial/corrupt/link records represent an unresolved attempt. Neither
    # an available OS lock nor an absent PID proves its child tree has exited.
    raise GenerationObservationError("restore outcome unknown; independent review required")


def record_restore_intent(target: Path, request_sha256: str, *, data_root=None):
    """Candidate guardian boundary: persist UNKNOWN while its target lock is held.

    No production launcher calls this yet. There is intentionally no automatic
    clear API: assembly must first prove native Job quiescence AND the matching
    completed receipt. This record is external to database restore snapshots.
    """
    if not isinstance(request_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", request_sha256):
        raise GenerationObservationError("invalid restore request digest")
    try:
        path, lock, key = _epoch_paths(target, data_root, create=False)
        if str(lock) not in _active_restores.get():
            raise GenerationObservationError("restore intent requires held target ownership")
        epoch = _read_closed_epoch(path, key)
        if epoch is None or epoch["state"] != "closed":
            raise GenerationObservationError("restore intent requires closed epoch")
        _require_no_restore_intent(path)
        intent = _restore_intent_path(path)
        fd = os.open(
            intent, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600
        )
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(
                {
                    "version": 1,
                    "state": "unknown",
                    "target_path_digest": key,
                    "epoch": epoch["epoch"],
                    "request_sha256": request_sha256,
                },
                output,
                sort_keys=True,
            )
            output.flush()
            os.fsync(output.fileno())
        _sync_epoch_directory(intent.parent)
        return intent
    except (OSError, ValueError) as exc:
        # Never remove a possibly published intent on failure.
        raise GenerationObservationError("restore intent could not be persisted") from exc


@dataclass(frozen=True)
class OwnedSource:
    owner_id: str
    tenant_id: str
    mod_id: str
    source_id: str
    epoch: str
    path_digest: str
    device: int
    inode: int


_owned_profile = None


def _validate_owned_host_schema(db):
    from app.db.models.agent_business_action import validate_ledger_storage
    from app.db.models.product_edit_claim import validate_product_edit_claim_schema
    from app.db.schema_migrations.owned_source_host import validate_owned_host_runtime_schema

    validate_product_edit_claim_schema(db.connection())
    validate_ledger_storage(db)
    validate_owned_host_runtime_schema(db.connection())


def _validate_owned_repository_schema(connection):
    """The serving run repository also needs pre-existing task/control storage."""
    from sqlalchemy.schema import CreateIndex, CreateTable

    from app.db.models.agent import AgentTaskCommandRecord, AgentTaskRecord

    compact = lambda sql: re.sub(r"\s+", "", str(sql or "")).lower()
    for model in (AgentTaskRecord, AgentTaskCommandRecord):
        table = model.__table__
        expected = {
            ("table", table.name): compact(CreateTable(table).compile(dialect=connection.dialect))
        }
        expected.update(
            {
                ("index", index.name): compact(
                    CreateIndex(index).compile(dialect=connection.dialect)
                )
                for index in table.indexes
            }
        )
        actual = {
            (kind, name): compact(sql)
            for kind, name, sql in connection.exec_driver_sql(
                "SELECT type,name,sql FROM main.sqlite_master WHERE tbl_name=? AND sql IS NOT NULL",
                (table.name,),
            )
        }
        if (
            actual != expected
            or connection.exec_driver_sql(
                "SELECT 1 FROM temp.sqlite_master WHERE name=? OR tbl_name=? LIMIT 1",
                (table.name, table.name),
            ).first()
        ):
            raise GenerationObservationError(f"owned repository schema differs: {table.name}")


def _existing_profile_file(path, *, limit=None):
    """Read an existing authority file without following links or creating anything."""
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise GenerationObservationError("guarded profile file is not regular")
    if limit is None:
        return str(path), before.st_dev, before.st_ino
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as source:
        info = os.fstat(source.fileno())
        if (
            (info.st_dev, info.st_ino) != (before.st_dev, before.st_ino)
            or not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_size > limit
        ):
            raise GenerationObservationError("guarded profile authority changed")
        raw = source.read(limit + 1)
    if len(raw) > limit or _existing_profile_file(path) != (
        str(path),
        before.st_dev,
        before.st_ino,
    ):
        raise GenerationObservationError("guarded profile authority changed")
    return raw


def validate_existing_owned_profile(config):
    """Stage serving readiness; never publish, enroll, migrate or repair storage.

    The caller owns process/app admission and publishes the returned immutable
    candidate only after all startup checks succeed. Normal SQLite-managed WAL/
    SHM sidecars may appear on a read-only WAL connection after a clean shutdown;
    no host, source, authority, directory or cooperative lock file is created.
    """
    from sqlalchemy import URL, create_engine
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import SQLAlchemyError
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import NullPool

    from app.desktop_runtime.desktop_runtime_paths import get_desktop_data_dir, is_desktop_mode

    declared = getattr(config, "OWNED_SOURCE_PROFILE", "") or os.environ.get(
        "XCAGI_OWNED_SOURCE_PROFILE", ""
    )
    if (
        declared != "guarded-host-v1"
        or sys.platform != "linux"
        or is_desktop_mode()
        or getattr(config, "DESKTOP_MODE", False)
        or any(
            not os.path.isabs(os.environ.get(key, ""))
            for key in ("XCAGI_DATA_DIR", "WORKSPACE_ROOT")
        )
    ):
        raise GenerationObservationError("existing guarded Linux server profile required")

    from app.db import _resolve_host_database_url

    try:
        # HOST selection is process-owned, not the factory Config or an Active-Mod
        # request. Compare both before any engine/DBAPI connection can create a DB.
        configured = make_url(getattr(config, "DATABASE_URL", ""))
        effective = make_url(_resolve_host_database_url())
        for url in (configured, effective):
            if (
                url.drivername not in {"sqlite", "sqlite+pysqlite"}
                or not url.database
                or not Path(url.database).is_absolute()
                or url.query
                or any((url.host, url.username, url.password, url.port))
            ):
                raise GenerationObservationError("ordinary absolute guarded HOST URL required")
        target = Path(configured.database)
        if target != Path(effective.database) or target.resolve(strict=True) != target:
            raise GenerationObservationError("configured and effective guarded HOST differ")
        identity = _existing_profile_file(target)
        root = get_desktop_data_dir()
        for directory in (Path(os.environ["XCAGI_DATA_DIR"]), root / "config"):
            if directory.resolve(strict=True) != directory or not stat.S_ISDIR(
                directory.lstat().st_mode
            ):
                raise GenerationObservationError("existing guarded control directory required")
        anchor, marker = owned_host_anchor(target), root / "config" / "owned-source-protocol.json"
        anchor_raw = _existing_profile_file(anchor, limit=4096)
        marker_raw = _existing_profile_file(marker, limit=100)
        if _read_host_anchor(anchor) != str(root) or json.loads(marker_raw) != {
            "version": 2,
            "state": "owned_sources_enrolled",
        }:
            raise GenerationObservationError("existing owned-source authority is unavailable")
        # A pre-existing alias must not turn SQLite's own sidecars into an alternate
        # target. Missing sidecars are normal after the last WAL connection closes.
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = Path(str(target) + suffix)
            try:
                _existing_profile_file(sidecar)
            except FileNotFoundError:
                pass
        engine = create_engine(
            URL.create(
                "sqlite+pysqlite", database=target.as_uri(), query={"mode": "ro", "uri": "true"}
            ),
            poolclass=NullPool,
        )
        try:
            with Session(engine) as db:
                connection = db.connection()
                connection.exec_driver_sql("PRAGMA query_only=ON")
                connection.exec_driver_sql("BEGIN")
                raw = connection.connection.driver_connection
                if _main_file(raw) != identity or raw.execute("PRAGMA journal_mode").fetchone() != (
                    "wal",
                ):
                    raise GenerationObservationError("preconfigured guarded HOST WAL required")
                _validate_owned_host_schema(db)
                _validate_owned_repository_schema(connection)
                from app.db.bootstrap.guarded import validate_auth_schema

                validate_auth_schema(connection)
                if (
                    _main_file(raw) != identity
                    or _existing_profile_file(anchor, limit=4096) != anchor_raw
                    or _existing_profile_file(marker, limit=100) != marker_raw
                ):
                    raise GenerationObservationError("guarded HOST authority changed")
        finally:
            engine.dispose()
        return root, identity
    except (OSError, ValueError, sqlite3.Error, SQLAlchemyError) as exc:
        raise GenerationObservationError("existing guarded profile unavailable") from exc


def configure_owned_source_profile(config):
    """Factory readiness for a pre-migrated isolated server, never a request opt-in."""
    global _owned_profile
    _owned_profile = None
    declared = getattr(config, "OWNED_SOURCE_PROFILE", "") or os.environ.get(
        "XCAGI_OWNED_SOURCE_PROFILE", ""
    )
    if not declared:
        return
    from sqlalchemy.engine import make_url

    from app.db import HostSessionLocal
    from app.desktop_runtime.desktop_runtime_paths import get_desktop_data_dir, is_desktop_mode

    if (
        declared != "guarded-host-v1"
        or sys.platform != "linux"
        or is_desktop_mode()
        or getattr(config, "DESKTOP_MODE", False)
        or any(
            not os.path.isabs(os.environ.get(k, "")) for k in ("XCAGI_DATA_DIR", "WORKSPACE_ROOT")
        )
    ):
        raise GenerationObservationError(
            "owned sources require the explicit guarded Linux server profile"
        )
    configured = make_url(config.DATABASE_URL)
    with HostSessionLocal() as db:
        if db.get_bind().dialect.name != "sqlite" or configured.drivername not in {
            "sqlite",
            "sqlite+pysqlite",
        }:
            raise GenerationObservationError("guarded host requires ordinary SQLite")
        connection = db.connection().connection.driver_connection
        if connection.execute("PRAGMA journal_mode").fetchone() != ("wal",):
            raise GenerationObservationError(
                "guarded host requires preconfigured WAL; no mode was changed"
            )
        _validate_owned_host_schema(db)
        identity = _main_file(connection)
        required = {
            "agent_runs",
            "agent_task_executions",
            "agent_business_actions",
            "agent_approval_consumptions",
            "agent_product_edit_claims",
        }
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if (
            not configured.database
            or configured.query
            or Path(configured.database).resolve() != Path(identity[0])
            or not required <= tables
        ):
            raise GenerationObservationError("guarded host migration or identity is unavailable")
    with owned_source_lifecycle(host_target=Path(identity[0])):
        _owned_profile = (get_desktop_data_dir(), identity)


def require_owned_source_profile(*, data_root=None):
    from app.db import HostSessionLocal
    from app.desktop_runtime.desktop_runtime_paths import get_desktop_data_dir, is_desktop_mode

    if (
        _owned_profile is None
        or sys.platform != "linux"
        or is_desktop_mode()
        or get_desktop_data_dir(data_root) != _owned_profile[0]
        or get_desktop_data_dir() != _owned_profile[0]
    ):
        raise GenerationObservationError("factory-verified guarded source profile is unavailable")
    path, device, inode = _owned_profile[1]
    info = Path(path).lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or (info.st_dev, info.st_ino) != (device, inode)
    ):
        raise GenerationObservationError("guarded host database identity changed")
    with HostSessionLocal() as db:
        validate_owned_host_session(db)


def validate_owned_host_session(db):
    from sqlalchemy.orm import Session

    if (
        _owned_profile is None
        or type(db).get_bind is not Session.get_bind
        or getattr(db, "binds", None)
        or getattr(db, "_Session__binds", None)
        or db.get_bind().dialect.name != "sqlite"
        or _main_file(db.connection().connection.driver_connection) != _owned_profile[1]
        or db.connection().exec_driver_sql("PRAGMA journal_mode").scalar() != "wal"
    ):
        raise GenerationObservationError("actual host authority connection changed")
    _validate_owned_host_schema(db)


def owned_host_anchor(target):
    target = Path(target).resolve()
    return target.with_name("." + target.name + ".owned-source-host.json")


def _read_host_anchor(anchor):
    try:
        info = anchor.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 4096:
        raise GenerationObservationError("host lifecycle anchor is unavailable")
    value = json.loads(anchor.read_text())
    if (
        not isinstance(value, dict)
        or set(value) != {"version", "control_root"}
        or type(value["version"]) is not int
        or value["version"] != 2
        or not isinstance(value["control_root"], str)
        or not Path(value["control_root"]).is_absolute()
        or str(Path(value["control_root"]).resolve()) != value["control_root"]
    ):
        raise GenerationObservationError("host lifecycle anchor is invalid")
    return value["control_root"]


@contextmanager
def owned_source_lifecycle(*, data_root=None, host_target=None, legacy_restore=False):
    """Serialize fresh enrollment against legacy host/audit database replacement."""
    from app.desktop_runtime.desktop_runtime_paths import get_desktop_data_dir
    from app.utils.process_lock import exclusive_file_lock

    root = get_desktop_data_dir(data_root)
    if (
        _owned_profile is not None
        or os.environ.get("XCAGI_OWNED_SOURCE_PROFILE") == "guarded-host-v1"
    ) and root != get_desktop_data_dir():
        raise GenerationObservationError("host lifecycle root is configuration-owned")
    config = root / "config"
    if host_target is None and _owned_profile is not None:
        host_target = _owned_profile[1][0]
    anchor = owned_host_anchor(host_target) if host_target is not None else None
    if anchor is None:
        _ensure_epoch_directory(config)
    marker = config / "owned-source-protocol.json"
    lock = anchor.with_suffix(".lock") if anchor else config / "owned-source-protocol.lock"
    if lock.exists() and (not stat.S_ISREG(lock.lstat().st_mode) or lock.stat().st_nlink != 1):
        raise GenerationObservationError("host lifecycle lock is not regular")
    with exclusive_file_lock(lock, blocking=False, reject_symlink=True):
        historical_root = _read_host_anchor(anchor) if anchor else None
        if historical_root is not None and historical_root != str(root):
            raise GenerationObservationError(
                "host control root changed; preserve original authority"
            )
        _ensure_epoch_directory(config)
        unknown = False
        if legacy_restore and not marker.exists():
            directory = config / "etl-recovery"
            try:
                info = directory.lstat()
                if (
                    not stat.S_ISDIR(info.st_mode)
                    or not info.st_mode & 0o444
                    or not info.st_mode & 0o111
                ):
                    raise OSError("source inventory directory is unavailable")
                records = list(directory.iterdir())
            except FileNotFoundError:
                records = []
            except OSError:
                records, unknown = [], True
            for record in records:
                if record.suffix != ".json":
                    continue
                try:
                    info = record.lstat()
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 4096:
                        raise ValueError("unknown source inventory")
                    with record.open("rb") as stream:
                        value = json.loads(stream.read(4097))
                    unknown |= value.get("version") != 1 or value.get("state") != "closed"
                except (OSError, ValueError, AttributeError):
                    unknown = True
        if legacy_restore and (
            historical_root is not None or marker.exists() or marker.is_symlink() or unknown
        ):
            raise GenerationObservationError(
                "legacy host restore would rewind owned-source authority"
            )
        yield marker


def _require_owned_lifecycle(data_root):
    from app.desktop_runtime.desktop_runtime_paths import get_desktop_data_dir

    root = get_desktop_data_dir(data_root)
    if _owned_profile is None or _read_host_anchor(owned_host_anchor(_owned_profile[1][0])) != str(
        root
    ):
        raise GenerationObservationError("owned host anchor is unavailable")
    marker = root / "config" / "owned-source-protocol.json"
    info = marker.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_size > 100
        or json.loads(marker.read_text()) != {"version": 2, "state": "owned_sources_enrolled"}
    ):
        raise GenerationObservationError("owned-source lifecycle authority is unavailable")


OWNED_SOURCE_SCHEMA = """CREATE TABLE etl_owned_source (
    owner_id TEXT NOT NULL, tenant_id TEXT NOT NULL, mod_id TEXT NOT NULL,
    source_id TEXT NOT NULL, epoch TEXT NOT NULL
)"""


def _owned_record(value, key) -> OwnedSource:
    fields = set(OwnedSource.__dataclass_fields__)
    if (
        set(value) != fields | {"version", "state"}
        or type(value["version"]) is not int
        or value["version"] != 2
        or value["state"] not in {"open", "closed"}
        or value["path_digest"] != key
        or not re.fullmatch(r"[1-9][0-9]*", str(value["tenant_id"]))
        or value["owner_id"] != "tenant:" + str(value["tenant_id"])
        or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,95}", str(value["mod_id"]))
        or any(type(value[k]) is not int or value[k] < 0 for k in ("device", "inode"))
    ):
        raise GenerationObservationError("owned source record is invalid")
    for name in ("source_id", "epoch"):
        marker = value[name]
        if not isinstance(marker, str) or str(UUID(marker)) != marker or UUID(marker).version != 4:
            raise GenerationObservationError("owned source UUID is invalid")
    if any(not isinstance(value[k], str) for k in fields - {"device", "inode"}):
        raise GenerationObservationError("owned source field is invalid")
    return OwnedSource(**{k: value[k] for k in fields})


def _owned_lock(target, data_root):
    path, lock, key = _epoch_paths(target, data_root, create=False)
    if str(lock) not in _active_restores.get():
        raise GenerationObservationError("owned source requires held target ownership")
    return path, key


def _publish_epoch(path, value):
    fd, temporary = tempfile.mkstemp(prefix=".epoch-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(value, output, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        _sync_epoch_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_owned_source(target: Path, *, data_root=None, allow_closed=False) -> OwnedSource:
    require_owned_source_profile(data_root=data_root)
    _require_owned_lifecycle(data_root)
    path, _lock, key = _epoch_paths(target, data_root, create=False)
    value = _read_closed_epoch(path, key)
    if not value or value["version"] != 2:
        raise GenerationObservationError("source was not enrolled by its owner")
    if not allow_closed:
        _require_no_restore_intent(path)
        if value["state"] != "open":
            raise GenerationObservationError("owned source is closed")
    return _owned_record(value, key)


def validate_owned_database(conn, target: Path, expected: OwnedSource, *, data_root=None):
    """Validate on the effect connection; no writer may outlive target ownership."""
    require_owned_source_profile(data_root=data_root)
    _path, key = _owned_lock(target, data_root)
    _owned_record({"version": 2, "state": "open", **asdict(expected)}, key)
    actual = _main_file(conn)
    rows = conn.execute("PRAGMA database_list").fetchall()
    definitions = dict(
        conn.execute(
            "SELECT name,sql FROM main.sqlite_master WHERE type='table' "
            "AND name IN ('etl_owned_source','etl_database_generation')"
        ).fetchall()
    )
    compact = lambda sql: re.sub(r"\s+", "", sql).lower()
    if {name: compact(sql) for name, sql in definitions.items()} != {
        "etl_owned_source": compact(OWNED_SOURCE_SCHEMA),
        "etl_database_generation": compact(
            "CREATE TABLE etl_database_generation (generation_id TEXT NOT NULL)"
        ),
    }:
        raise GenerationObservationError("owned source schema changed")
    if (
        actual != (str(target.resolve(strict=True)), expected.device, expected.inode)
        or any(row[1] not in {"main", "temp"} for row in rows)
        or _generation(conn) != expected.epoch
        or conn.execute("SELECT * FROM main.etl_owned_source").fetchall()
        != [
            (
                expected.owner_id,
                expected.tenant_id,
                expected.mod_id,
                expected.source_id,
                expected.epoch,
            )
        ]
        or conn.execute(
            "SELECT 1 FROM main.sqlite_master WHERE type='trigger' AND tbl_name IN "
            "('etl_owned_source','etl_database_generation') UNION ALL "
            "SELECT 1 FROM temp.sqlite_master WHERE type IN ('table','trigger') AND "
            "(name IN ('etl_owned_source','etl_database_generation') OR "
            "tbl_name IN ('etl_owned_source','etl_database_generation')) LIMIT 1"
        ).fetchone()
    ):
        raise GenerationObservationError("owned database identity changed")


def validate_owned_source(conn, target: Path, expected: OwnedSource, *, data_root=None):
    if read_owned_source(target, data_root=data_root) != expected:
        raise GenerationObservationError("original dispatch source epoch changed")
    validate_owned_database(conn, target, expected, data_root=data_root)


def write_owned_source_epoch(target, expected, replacement, *, state, data_root=None):
    """Private coordinator CAS; OPEN requires its separately verified completed intent."""
    require_owned_source_profile(data_root=data_root)
    path, key = _owned_lock(target, data_root)
    current = _read_closed_epoch(path, key)
    if not current or _owned_record(current, key) != expected:
        raise GenerationObservationError("owned source epoch compare-and-swap failed")
    if any(
        getattr(expected, k) != getattr(replacement, k)
        for k in ("owner_id", "tenant_id", "mod_id", "source_id", "path_digest", "device", "inode")
    ):
        raise GenerationObservationError("restore cannot change source ownership")
    value = {"version": 2, "state": state, **asdict(replacement)}
    _owned_record(value, key)
    _publish_epoch(path, value)


def enroll_owned_source(
    target, context, statements, *, data_root=None, validate_schema=None
) -> OwnedSource:
    """Host-only explicit creation. Existing files/markers are never adopted or removed."""
    require_owned_source_profile(data_root=data_root)
    profile = _owned_profile
    if profile is None:
        raise GenerationObservationError("owned source profile is unavailable")
    _user, tenant, mod = _scope(context)
    with (
        owned_source_lifecycle(data_root=data_root) as lifecycle,
        target_database_lock(target, data_root=data_root) as (path, key),
    ):
        _require_no_restore_intent(path)
        if _read_closed_epoch(path, key) is not None:
            raise GenerationObservationError("source already has control history")
        if lifecycle.exists():
            _require_owned_lifecycle(data_root)
        elif any(path.parent.glob("*.json")):
            raise GenerationObservationError(
                "missing lifecycle authority requires independent review"
            )
        if any(parent.is_symlink() for parent in target.parents):
            raise GenerationObservationError("source parent aliases are unsupported")
        fd = os.open(
            target, os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600
        )
        info = os.fstat(fd)
        os.close(fd)
        _publish_epoch(
            owned_host_anchor(profile[1][0]),
            {"version": 2, "control_root": str(profile[0])},
        )
        _publish_epoch(lifecycle, {"version": 2, "state": "owned_sources_enrolled"})
        source = OwnedSource(
            "tenant:" + tenant,
            tenant,
            mod,
            str(uuid4()),
            str(uuid4()),
            key,
            info.st_dev,
            info.st_ino,
        )
        # A failed initializer leaves both the file and CLOSED evidence; never retry by adoption.
        _publish_epoch(path, {"version": 2, "state": "closed", **asdict(source)})
        with closing(sqlite3.connect(target.as_uri() + "?mode=rw", uri=True)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(OWNED_SOURCE_SCHEMA)
            conn.execute(
                "INSERT INTO etl_owned_source VALUES (?,?,?,?,?)",
                (source.owner_id, tenant, mod, source.source_id, source.epoch),
            )
            conn.execute("CREATE TABLE etl_database_generation (generation_id TEXT NOT NULL)")
            conn.execute("INSERT INTO etl_database_generation VALUES (?)", (source.epoch,))
            for statement, parameters in statements:
                conn.execute(statement, parameters)
            conn.commit()
            validate_owned_database(conn, target, source, data_root=data_root)
            if validate_schema is not None:
                validate_schema(conn)
        write_owned_source_epoch(target, source, source, state="open", data_root=data_root)
        return source
