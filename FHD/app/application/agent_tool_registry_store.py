"""SQLite persistence, version snapshots, registry caches, and private tool audit records."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import tempfile
import threading
import uuid
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, TypeVar, cast
from zoneinfo import ZoneInfo

from app.application.agent_tool_contracts import (
    Actor,
    ToolLifecycleError,
    _dumps,
    _redact,
    function_spec,
)
from app.utils.operational_errors import BOUNDARY_ERRORS

logger = logging.getLogger("app.application.agent_tool_lifecycle")

T = TypeVar("T")


_SHANGHAI = ZoneInfo("Asia/Shanghai")


_LOCK = threading.Lock()


_SCHEMA_READY = False


_DB_OVERRIDE: str | None = None


_GENERATION = 0


_CACHE: dict[tuple[Any, ...], str] = {}


_DDL = """
CREATE TABLE IF NOT EXISTS tools (
  id TEXT PRIMARY KEY,
  tenant_id INTEGER NOT NULL,
  tool_key TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT NOT NULL,
  status TEXT NOT NULL,
  scope TEXT,
  employee_id TEXT,
  current_version_id TEXT,
  version_no INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (tenant_id, tool_key)
);
CREATE TABLE IF NOT EXISTS versions (
  id TEXT PRIMARY KEY,
  tool_id TEXT NOT NULL,
  tenant_id INTEGER NOT NULL,
  version_no INTEGER NOT NULL,
  name TEXT NOT NULL,
  description TEXT NOT NULL,
  schema_json TEXT NOT NULL,
  state TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  created_at_shanghai TEXT NOT NULL,
  UNIQUE (tool_id, version_no)
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id INTEGER NOT NULL,
  tool_id TEXT,
  kind TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  actor_role TEXT NOT NULL,
  at TEXT NOT NULL,
  at_shanghai TEXT NOT NULL,
  detail_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS permissions (
  id TEXT PRIMARY KEY,
  tenant_id INTEGER NOT NULL,
  tool_id TEXT NOT NULL,
  subject_type TEXT NOT NULL,
  subject_id TEXT NOT NULL,
  effect TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  created_at_shanghai TEXT NOT NULL,
  revoked_at TEXT,
  revoked_at_shanghai TEXT
);
CREATE TABLE IF NOT EXISTS principals (
  tenant_id INTEGER NOT NULL,
  principal_id TEXT NOT NULL,
  role TEXT NOT NULL,
  PRIMARY KEY (tenant_id, principal_id)
);
CREATE TABLE IF NOT EXISTS calls (
  id TEXT PRIMARY KEY,
  tenant_id INTEGER NOT NULL,
  tool_id TEXT NOT NULL,
  version_id TEXT NOT NULL,
  definition_json TEXT NOT NULL,
  args_json TEXT NOT NULL,
  status TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  employee_id TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  result_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_tools_tenant ON tools(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_calls_tool ON calls(tool_id, started_at);
CREATE INDEX IF NOT EXISTS idx_events_tenant ON events(tenant_id, id);
CREATE INDEX IF NOT EXISTS idx_events_tenant_tool ON events(tenant_id, tool_id, id);
"""


def reset_for_tests(path: str | None = None) -> None:
    """Point the registry at an isolated database and drop caches."""
    global _SCHEMA_READY, _DB_OVERRIDE, _GENERATION
    with _LOCK:
        _DB_OVERRIDE = path
        _SCHEMA_READY = False
        _GENERATION += 1
        _CACHE.clear()


def db_path() -> Path:
    if _DB_OVERRIDE:
        return Path(_DB_OVERRIDE)
    explicit = (os.environ.get("XCAGI_AGENT_TOOL_DB") or "").strip()
    if explicit:
        return Path(explicit)
    data = (os.environ.get("XCAGI_DATA_DIR") or os.environ.get("XCAGI_CONFIG_DIR") or "").strip()
    if data:
        return Path(data) / "agent-tool-lifecycle.sqlite3"
    return Path(tempfile.gettempdir()) / f"xcagi-agent-tool-lifecycle-{os.getpid()}.sqlite3"


def _now() -> tuple[str, str]:
    utc = datetime.now(tz=_SHANGHAI).astimezone(ZoneInfo("UTC")).replace(microsecond=0)
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ"), utc.astimezone(_SHANGHAI).isoformat()


def _connect() -> sqlite3.Connection:
    global _SCHEMA_READY
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    with _LOCK:
        if not _SCHEMA_READY:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_DDL)
            _SCHEMA_READY = True
    return conn


def _bump() -> None:
    global _GENERATION
    with _LOCK:
        _GENERATION += 1
        _CACHE.clear()


def _cached(key: tuple[Any, ...], builder: Callable[[], T]) -> T:
    full = (_GENERATION, key)
    with _LOCK:
        hit = _CACHE.get(full)
    if hit is not None:
        return cast(T, json.loads(hit))
    value = builder()
    encoded = json.dumps(value, ensure_ascii=False)
    with _LOCK:
        if full[0] == _GENERATION:
            _CACHE[full] = encoded
    return cast(T, json.loads(encoded))


@contextmanager
def _tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BOUNDARY_ERRORS:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def _audit(
    conn: sqlite3.Connection,
    actor: Actor,
    kind: str,
    tool_id: str | None,
    detail: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    at, at_sh = _now()
    safe = _redact(dict(detail or {}))
    conn.execute(
        """
        INSERT INTO events (
          tenant_id, tool_id, kind, actor_id, actor_role, at, at_shanghai, detail_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (actor.tenant_id, tool_id, kind, actor.actor_id, actor.role, at, at_sh, _dumps(safe)),
    )
    logger.info(
        "agent_tool_event kind=%s tool=%s actor=%s",
        kind,
        tool_id or "",
        actor.actor_id,
    )
    return {
        "kind": kind,
        "actor_id": actor.actor_id,
        "actor_role": actor.role,
        "at": at,
        "at_shanghai": at_sh,
    }


def _tool_row(conn: sqlite3.Connection, actor: Actor, tool_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM tools WHERE id = ? AND tenant_id = ?", (tool_id, actor.tenant_id)
    ).fetchone()
    if row is None:
        raise ToolLifecycleError("unknown_tool", "工具不存在", 404)
    return cast(sqlite3.Row, row)


def _version_row(conn: sqlite3.Connection, tool_id: str, version_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM versions WHERE id = ? AND tool_id = ?", (version_id, tool_id)
    ).fetchone()
    if row is None:
        raise ToolLifecycleError("unknown_version", "工具版本不存在", 404)
    return cast(sqlite3.Row, row)


def _public_tool(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    version = None
    spec = None
    if row["current_version_id"]:
        version = _version_row(conn, row["id"], row["current_version_id"])
        schema = json.loads(version["schema_json"])
        spec = function_spec(row["tool_key"], version["description"], schema)
    return {
        "id": row["id"],
        "tool_key": row["tool_key"],
        "name": row["name"],
        "description": row["description"],
        "status": row["status"],
        "scope": row["scope"],
        "employee_id": row["employee_id"],
        "tenant_id": row["tenant_id"],
        "version_no": row["version_no"],
        "current_version_id": row["current_version_id"],
        "function": None if spec is None else spec["function"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _insert_version(
    conn: sqlite3.Connection,
    actor: Actor,
    tool_id: str,
    version_id: str,
    version_no: int,
    name: str,
    description: str,
    schema: Mapping[str, Any],
    state: str,
) -> None:
    at, at_sh = _now()
    conn.execute(
        """
        INSERT INTO versions (
          id, tool_id, tenant_id, version_no, name, description, schema_json, state,
          actor_id, created_at, created_at_shanghai
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            version_id,
            tool_id,
            actor.tenant_id,
            version_no,
            name,
            description,
            _dumps(schema),
            state,
            actor.actor_id,
            at,
            at_sh,
        ),
    )


def _snapshot_version(actor: Actor, tool_id: str) -> tuple[Any, ...] | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT version_no, current_version_id, name, description FROM tools WHERE id = ? AND tenant_id = ?",
            (tool_id, actor.tenant_id),
        ).fetchone()
        if row is None:
            return None
        version = conn.execute(
            "SELECT schema_json, state FROM versions WHERE id = ?", (row["current_version_id"],)
        ).fetchone()
        return (
            row["version_no"],
            row["current_version_id"],
            row["name"],
            row["description"],
            None if version is None else version["schema_json"],
            None if version is None else version["state"],
        )
    finally:
        conn.close()


def _audit_outside(actor: Actor, kind: str, tool_id: str | None, detail: Mapping[str, Any]) -> None:
    conn = _connect()
    try:
        with _tx(conn):
            _audit(conn, actor, kind, tool_id, detail)
    finally:
        conn.close()


def _insert_grant(
    conn: sqlite3.Connection,
    actor: Actor,
    tool_id: str,
    scope: str,
    employee_id: str | None,
) -> str:
    at, at_sh = _now()
    if scope == "employee":
        subject_type, subject_id = "employee", employee_id or ""
    else:
        subject_type, subject_id = "role", "employee"
    permission_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO permissions (
          id, tenant_id, tool_id, subject_type, subject_id, effect, actor_id,
          created_at, created_at_shanghai
        ) VALUES (?, ?, ?, ?, ?, 'grant', ?, ?, ?)
        """,
        (
            permission_id,
            actor.tenant_id,
            tool_id,
            subject_type,
            subject_id,
            actor.actor_id,
            at,
            at_sh,
        ),
    )
    return permission_id


def _active_effect(
    conn: sqlite3.Connection, tool_id: str, subject_type: str, subject_id: str, effect: str
) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM permissions
        WHERE tool_id = ? AND subject_type = ? AND subject_id = ? AND effect = ? AND revoked_at IS NULL
        LIMIT 1
        """,
        (tool_id, subject_type, subject_id, effect),
    ).fetchone()
    return row is not None


def _resolve_invoke_row(
    conn: sqlite3.Connection, actor: Actor, tool_id: str, by_key: str | None
) -> sqlite3.Row:
    if by_key:
        row = conn.execute(
            "SELECT * FROM tools WHERE tenant_id = ? AND tool_key = ?",
            (actor.tenant_id, by_key),
        ).fetchone()
        if row is None:
            raise ToolLifecycleError("unknown_tool", "工具不存在", 404)
        return cast(sqlite3.Row, row)
    return _tool_row(conn, actor, tool_id)


def _ensure_principal(conn: sqlite3.Connection, actor: Actor) -> None:
    if actor.role == "admin":
        return
    if not actor.employee_id:
        raise ToolLifecycleError("forged_employee", "员工不存在", 404)
    row = conn.execute(
        "SELECT role FROM principals WHERE tenant_id = ? AND principal_id = ?",
        (actor.tenant_id, actor.employee_id),
    ).fetchone()
    if row is None or row["role"] != actor.role:
        raise ToolLifecycleError("forged_employee", "员工不存在", 404)


def _runtime_spec(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    version = _version_row(conn, row["id"], row["current_version_id"])
    schema = json.loads(version["schema_json"])
    spec = function_spec(row["tool_key"], version["description"], schema)
    spec["tool_id"] = row["id"]
    spec["version_id"] = version["id"]
    return spec
