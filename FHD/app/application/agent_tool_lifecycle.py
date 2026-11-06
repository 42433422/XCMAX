"""Tenant-scoped AI tool register, publish, discovery, and invoke.

Global publish means every employee of the owning tenant. It never crosses
tenants. The tenant id always comes from the server auth context.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import tempfile
import threading
import uuid
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator
from zoneinfo import ZoneInfo

from app.utils.operational_errors import BOUNDARY_ERRORS

logger = logging.getLogger(__name__)

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_SCHEMA_TYPES = {"string", "integer", "number", "boolean", "array", "object"}
_SECRET_KEYS = {
    "api_key",
    "apikey",
    "api_token",
    "access_token",
    "refresh_token",
    "authorization",
    "password",
    "secret",
    "token",
}
_SECRET_TEXT = re.compile(
    r"(?i)(sk-[a-z0-9]{8,}|bearer\s+[a-z0-9._\-]{8,}"
    r"|api[_-]?key\s*[:=]\s*\S+|token\s*[:=]\s*\S+)"
)
_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_PRINCIPAL_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_ROLES = {"admin", "employee", "readonly"}
_SCOPES = {"global", "tenant", "employee"}
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
"""


class ToolLifecycleError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.extra = extra


@dataclass(frozen=True)
class Actor:
    actor_id: str
    role: str
    employee_id: str | None
    tenant_id: int


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


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower().replace("-", "_") in _SECRET_KEYS:
                out[str(key)] = "[redacted]"
            else:
                out[str(key)] = _redact(item)
        return out
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _SECRET_TEXT.sub("[redacted]", value)
    return value


def _dumps(value: Any) -> str:
    return json.dumps(_redact(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


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


def _cached(key: tuple[Any, ...], builder: Callable[[], Any]) -> Any:
    full = (_GENERATION, key)
    with _LOCK:
        hit = _CACHE.get(full)
    if hit is not None:
        return json.loads(hit)
    value = builder()
    encoded = json.dumps(value, ensure_ascii=False)
    with _LOCK:
        if full[0] == _GENERATION:
            _CACHE[full] = encoded
    return json.loads(encoded)


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
        "agent_tool_event kind=%s tool=%s actor=%s detail=%s",
        kind,
        tool_id or "",
        actor.actor_id,
        _dumps(safe),
    )
    return {
        "kind": kind,
        "actor_id": actor.actor_id,
        "actor_role": actor.role,
        "at": at,
        "at_shanghai": at_sh,
    }


def _require_admin(actor: Actor) -> None:
    if actor.role != "admin":
        raise ToolLifecycleError("admin_required", "只有管理员可以修改工具注册信息", 403)


def _require_text(body: Mapping[str, Any], field: str) -> str:
    value = body.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ToolLifecycleError("field_required", f"缺少必填字段 {field}", 400, field=field)
    return value.strip()


def validate_input_schema(schema: Any) -> dict[str, Any]:
    if isinstance(schema, str):
        try:
            schema = json.loads(schema)
        except json.JSONDecodeError as exc:
            raise ToolLifecycleError(
                "invalid_json_schema", "JSON Schema 不是合法 JSON", 400
            ) from exc
    if not isinstance(schema, dict):
        raise ToolLifecycleError("invalid_json_schema", "JSON Schema 必须是对象", 400)
    if schema.get("type") != "object":
        raise ToolLifecycleError("invalid_json_schema", "JSON Schema 的 type 必须是 object", 400)
    props = schema.get("properties")
    if not isinstance(props, dict):
        raise ToolLifecycleError("invalid_json_schema", "JSON Schema 缺少 properties 对象", 400)
    for name, spec in props.items():
        _validate_property(str(name), spec)
    required = schema.get("required", [])
    if not isinstance(required, list) or any(
        not isinstance(item, str) or item not in props for item in required
    ):
        raise ToolLifecycleError("invalid_json_schema", "required 含有未声明的字段", 400)
    additional = schema.get("additionalProperties", False)
    if not isinstance(additional, bool):
        raise ToolLifecycleError("invalid_json_schema", "additionalProperties 必须是布尔值", 400)
    cleaned = {
        "type": "object",
        "properties": {str(key): _clean_property(value) for key, value in props.items()},
        "required": list(required),
        "additionalProperties": additional,
    }
    return _redact(cleaned)


def _validate_property(name: str, spec: Any) -> None:
    if not isinstance(spec, dict) or spec.get("type") not in _SCHEMA_TYPES:
        raise ToolLifecycleError(
            "invalid_json_schema", f"字段 {name} 的类型不在允许范围内", 400, field=name
        )
    kind = spec["type"]
    if kind == "array":
        items = spec.get("items")
        if not isinstance(items, dict) or items.get("type") not in _SCHEMA_TYPES:
            raise ToolLifecycleError("invalid_json_schema", f"字段 {name} 的数组元素类型无效", 400)
        if items.get("type") == "object":
            _validate_object_fields(f"{name}.items", items)
    if kind == "object":
        _validate_object_fields(name, spec)


def _validate_object_fields(name: str, spec: Mapping[str, Any]) -> None:
    props = spec.get("properties", {})
    if props is None:
        props = {}
    if not isinstance(props, dict):
        raise ToolLifecycleError("invalid_json_schema", f"字段 {name} 的 properties 无效", 400)
    for child, child_spec in props.items():
        _validate_property(f"{name}.{child}", child_spec)
    required = spec.get("required", [])
    if not isinstance(required, list) or any(item not in props for item in required):
        raise ToolLifecycleError("invalid_json_schema", f"字段 {name} 的 required 无效", 400)


def _clean_property(spec: Mapping[str, Any]) -> dict[str, Any]:
    kind = str(spec["type"])
    cleaned: dict[str, Any] = {"type": kind}
    if "description" in spec:
        cleaned["description"] = spec.get("description")
    if "default" in spec:
        cleaned["default"] = spec.get("default")
    if kind == "array":
        cleaned["items"] = _clean_property(spec["items"])
    if kind == "object":
        props = spec.get("properties") or {}
        cleaned["properties"] = {str(key): _clean_property(value) for key, value in props.items()}
        cleaned["required"] = list(spec.get("required") or [])
        cleaned["additionalProperties"] = bool(spec.get("additionalProperties", False))
    return cleaned


def function_spec(name: str, description: str, schema: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": json.loads(_dumps(dict(schema))),
        },
    }


def _tool_row(conn: sqlite3.Connection, actor: Actor, tool_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM tools WHERE id = ? AND tenant_id = ?", (tool_id, actor.tenant_id)
    ).fetchone()
    if row is None:
        raise ToolLifecycleError("unknown_tool", "工具不存在", 404)
    return row


def _version_row(conn: sqlite3.Connection, tool_id: str, version_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM versions WHERE id = ? AND tool_id = ?", (version_id, tool_id)
    ).fetchone()
    if row is None:
        raise ToolLifecycleError("unknown_version", "工具版本不存在", 404)
    return row


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


def register_principal(actor: Actor, body: Mapping[str, Any]) -> dict[str, Any]:
    _require_admin(actor)
    principal_id = _require_text(body, "principal_id")
    role = _require_text(body, "role")
    if not _PRINCIPAL_RE.fullmatch(principal_id):
        raise ToolLifecycleError("invalid_principal", "员工标识不合法", 400)
    if role not in {"employee", "readonly"}:
        raise ToolLifecycleError("invalid_role", "只能登记员工或只读身份", 400)
    conn = _connect()
    try:
        with _tx(conn):
            conn.execute(
                """
                INSERT INTO principals (tenant_id, principal_id, role)
                VALUES (?, ?, ?)
                ON CONFLICT(tenant_id, principal_id) DO UPDATE SET role = excluded.role
                """,
                (actor.tenant_id, principal_id, role),
            )
            _audit(
                conn,
                actor,
                "register_principal",
                None,
                {"principal_id": principal_id, "role": role},
            )
    finally:
        conn.close()
    _bump()
    return {"principal_id": principal_id, "role": role, "tenant_id": actor.tenant_id}


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


def create_tool(actor: Actor, body: Mapping[str, Any]) -> dict[str, Any]:
    _require_admin(actor)
    tool_key = _require_text(body, "tool_key")
    name = _require_text(body, "name")
    description = _require_text(body, "description")
    if "input_schema" not in body or body.get("input_schema") in (None, "", {}):
        raise ToolLifecycleError(
            "field_required", "缺少必填字段 input_schema", 400, field="input_schema"
        )
    if not _KEY_RE.fullmatch(tool_key):
        raise ToolLifecycleError("invalid_tool_key", "工具键不合法", 400, field="tool_key")
    schema = validate_input_schema(body.get("input_schema"))
    description = str(_redact(description))
    name = str(_redact(name))
    conn = _connect()
    try:
        with _tx(conn):
            existing = conn.execute(
                "SELECT id, name FROM tools WHERE tenant_id = ? AND tool_key = ?",
                (actor.tenant_id, tool_key),
            ).fetchone()
            if existing is not None:
                raise ToolLifecycleError(
                    "duplicate_tool_key", "工具键已存在，未覆盖已有工具", 409, field="tool_key"
                )
            tool_id = uuid.uuid4().hex
            version_id = uuid.uuid4().hex
            at, _at_sh = _now()
            conn.execute(
                """
                INSERT INTO tools (
                  id, tenant_id, tool_key, name, description, status, scope, employee_id,
                  current_version_id, version_no, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'draft', NULL, NULL, ?, 1, ?, ?)
                """,
                (tool_id, actor.tenant_id, tool_key, name, description, version_id, at, at),
            )
            _insert_version(
                conn, actor, tool_id, version_id, 1, name, description, schema, "stable"
            )
            _audit(conn, actor, "create", tool_id, {"tool_key": tool_key, "version_id": version_id})
            row = _tool_row(conn, actor, tool_id)
            payload = _public_tool(conn, row)
    except sqlite3.IntegrityError as exc:
        raise ToolLifecycleError(
            "duplicate_tool_key", "工具键已存在，未覆盖已有工具", 409, field="tool_key"
        ) from exc
    finally:
        conn.close()
    _bump()
    return payload


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


def validate_tool_schema(actor: Actor, tool_id: str, body: Mapping[str, Any]) -> dict[str, Any]:
    _require_admin(actor)
    schema = validate_input_schema(body.get("input_schema"))
    conn = _connect()
    try:
        row = _tool_row(conn, actor, tool_id)
        expected = int(row["version_no"])
    finally:
        conn.close()
    payload = update_tool(actor, tool_id, {"expected_version": expected, "input_schema": schema})
    _audit_outside(actor, "validate", tool_id, {"version_id": payload["current_version_id"]})
    return payload


def update_tool(actor: Actor, tool_id: str, body: Mapping[str, Any]) -> dict[str, Any]:
    _require_admin(actor)
    if "expected_version" not in body:
        raise ToolLifecycleError(
            "field_required", "缺少必填字段 expected_version", 400, field="expected_version"
        )
    try:
        expected = int(body.get("expected_version"))
    except (TypeError, ValueError) as exc:
        raise ToolLifecycleError(
            "field_required", "缺少必填字段 expected_version", 400, field="expected_version"
        ) from exc
    has_schema = "input_schema" in body and body.get("input_schema") not in (None, "")
    schema: dict[str, Any] | None = None
    if has_schema:
        try:
            schema = validate_input_schema(body.get("input_schema"))
        except ToolLifecycleError as exc:
            _record_failed_update(actor, tool_id, exc)
            raise
    name = body.get("name")
    description = body.get("description")
    if name is not None:
        name = _require_text({"name": name}, "name")
        name = str(_redact(name))
    if description is not None:
        description = _require_text({"description": description}, "description")
        description = str(_redact(description))
    if schema is None and name is None and description is None:
        raise ToolLifecycleError("empty_update", "更新没有可保存的字段", 400)
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = _tool_row(conn, actor, tool_id)
            if int(row["version_no"]) != expected:
                conn.execute("ROLLBACK")
                _audit_outside(actor, "version_conflict", tool_id, {"expected_version": expected})
                raise ToolLifecycleError(
                    "version_conflict", "工具版本已变化，未覆盖他人的更新", 409
                )
            if row["status"] == "offline":
                conn.execute("ROLLBACK")
                raise ToolLifecycleError("tool_offline", "已下线工具不能更新", 409)
            current = _version_row(conn, row["id"], row["current_version_id"])
            next_name = name or row["name"]
            next_description = description or current["description"]
            next_schema = schema if schema is not None else json.loads(current["schema_json"])
            version_id = uuid.uuid4().hex
            version_no = int(row["version_no"]) + 1
            at, _at_sh = _now()
            _insert_version(
                conn,
                actor,
                tool_id,
                version_id,
                version_no,
                next_name,
                next_description,
                next_schema,
                "stable",
            )
            conn.execute(
                """
                UPDATE tools
                SET name = ?, description = ?, current_version_id = ?, version_no = ?, updated_at = ?
                WHERE id = ? AND tenant_id = ? AND version_no = ?
                """,
                (
                    next_name,
                    next_description,
                    version_id,
                    version_no,
                    at,
                    tool_id,
                    actor.tenant_id,
                    expected,
                ),
            )
            if conn.execute("SELECT changes()").fetchone()[0] != 1:
                conn.execute("ROLLBACK")
                _audit_outside(actor, "version_conflict", tool_id, {"expected_version": expected})
                raise ToolLifecycleError(
                    "version_conflict", "工具版本已变化，未覆盖他人的更新", 409
                )
            _audit(
                conn,
                actor,
                "update",
                tool_id,
                {"version_id": version_id, "version_no": version_no, "expected_version": expected},
            )
            conn.execute("COMMIT")
            saved = _tool_row(conn, actor, tool_id)
            payload = _public_tool(conn, saved)
        except BOUNDARY_ERRORS:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.OperationalError:
                pass
            raise
    finally:
        conn.close()
    _bump()
    return payload


def _record_failed_update(actor: Actor, tool_id: str, exc: ToolLifecycleError) -> None:
    before = _snapshot_version(actor, tool_id)
    _audit_outside(actor, "update_failed", tool_id, {"code": exc.code, "message": exc.message})
    after = _snapshot_version(actor, tool_id)
    if before != after:
        raise ToolLifecycleError("update_rollback_failed", "失败的更新改动了上一稳定版本", 500)


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


def publish_tool(actor: Actor, tool_id: str, body: Mapping[str, Any]) -> dict[str, Any]:
    _require_admin(actor)
    scope = _require_text(body, "scope")
    if scope not in _SCOPES:
        raise ToolLifecycleError("invalid_scope", "发布范围必须是 global、tenant 或 employee", 400)
    employee_id = str(body.get("employee_id") or "").strip() or None
    if scope == "employee" and not employee_id:
        raise ToolLifecycleError(
            "field_required", "缺少必填字段 employee_id", 400, field="employee_id"
        )
    conn = _connect()
    try:
        with _tx(conn):
            row = _tool_row(conn, actor, tool_id)
            if row["status"] == "offline":
                raise ToolLifecycleError(
                    "tool_offline", "已下线工具请使用重新上架，而不是再次注册", 409
                )
            if row["status"] == "published":
                raise ToolLifecycleError("already_published", "工具已发布", 409)
            prior = conn.execute(
                "SELECT 1 FROM events WHERE tool_id = ? AND kind IN ('publish', 'republish') LIMIT 1",
                (tool_id,),
            ).fetchone()
            kind = "republish" if prior else "publish"
            if scope == "employee":
                found = conn.execute(
                    """
                    SELECT role FROM principals
                    WHERE tenant_id = ? AND principal_id = ? AND role = 'employee'
                    """,
                    (actor.tenant_id, employee_id),
                ).fetchone()
                if found is None:
                    raise ToolLifecycleError("forged_employee", "员工不存在", 404)
            at, _at_sh = _now()
            conn.execute(
                """
                UPDATE tools
                SET status = 'published', scope = ?, employee_id = ?, updated_at = ?
                WHERE id = ? AND tenant_id = ?
                """,
                (scope, employee_id if scope == "employee" else None, at, tool_id, actor.tenant_id),
            )
            grant_id = _insert_grant(conn, actor, tool_id, scope, employee_id)
            saved = _tool_row(conn, actor, tool_id)
            record = _audit(
                conn,
                actor,
                kind,
                tool_id,
                {"scope": scope, "employee_id": employee_id if scope == "employee" else None},
            )
            payload = _public_tool(conn, saved)
            payload["publish_record"] = record
            payload["grant_id"] = grant_id
    finally:
        conn.close()
    _bump()
    return payload


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


def unpublish_tool(actor: Actor, tool_id: str) -> dict[str, Any]:
    _require_admin(actor)
    conn = _connect()
    try:
        with _tx(conn):
            row = _tool_row(conn, actor, tool_id)
            if row["status"] != "published":
                raise ToolLifecycleError("not_published", "只有已发布工具可以取消发布", 409)
            at, at_sh = _now()
            conn.execute(
                """
                UPDATE tools SET status = 'draft', updated_at = ? WHERE id = ? AND tenant_id = ?
                """,
                (at, tool_id, actor.tenant_id),
            )
            conn.execute(
                """
                UPDATE permissions
                SET revoked_at = ?, revoked_at_shanghai = ?
                WHERE tool_id = ? AND tenant_id = ? AND effect = 'grant' AND revoked_at IS NULL
                """,
                (at, at_sh, tool_id, actor.tenant_id),
            )
            saved = _tool_row(conn, actor, tool_id)
            record = _audit(conn, actor, "unpublish", tool_id, {})
            payload = _public_tool(conn, saved)
            payload["unpublish_record"] = record
    finally:
        conn.close()
    _bump()
    return payload


def offline_tool(actor: Actor, tool_id: str) -> dict[str, Any]:
    _require_admin(actor)
    return _set_availability(actor, tool_id, "offline", "offline", ("published", "draft"))


def relist_tool(actor: Actor, tool_id: str) -> dict[str, Any]:
    _require_admin(actor)
    conn = _connect()
    try:
        with _tx(conn):
            row = _tool_row(conn, actor, tool_id)
            if row["status"] != "offline":
                raise ToolLifecycleError("not_offline", "只有已下线工具可以重新上架", 409)
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM tools WHERE tenant_id = ? AND tool_key = ?",
                (actor.tenant_id, row["tool_key"]),
            ).fetchone()["n"]
            if int(count) != 1:
                raise ToolLifecycleError(
                    "duplicate_tool_key", "重新上架不能再次注册同一工具键", 409
                )
            at, _at_sh = _now()
            conn.execute(
                "UPDATE tools SET status = 'published', updated_at = ? WHERE id = ? AND tenant_id = ?",
                (at, tool_id, actor.tenant_id),
            )
            saved = _tool_row(conn, actor, tool_id)
            record = _audit(conn, actor, "relist", tool_id, {"tool_key": row["tool_key"]})
            payload = _public_tool(conn, saved)
            payload["relist_record"] = record
    finally:
        conn.close()
    _bump()
    return payload


def _set_availability(
    actor: Actor, tool_id: str, status: str, kind: str, allowed_from: tuple[str, ...]
) -> dict[str, Any]:
    conn = _connect()
    try:
        with _tx(conn):
            row = _tool_row(conn, actor, tool_id)
            if row["status"] not in allowed_from:
                raise ToolLifecycleError("invalid_transition", "当前状态不能执行该操作", 409)
            at, _at_sh = _now()
            conn.execute(
                "UPDATE tools SET status = ?, updated_at = ? WHERE id = ? AND tenant_id = ?",
                (status, at, tool_id, actor.tenant_id),
            )
            saved = _tool_row(conn, actor, tool_id)
            record = _audit(conn, actor, kind, tool_id, {})
            payload = _public_tool(conn, saved)
            payload["record"] = record
    finally:
        conn.close()
    _bump()
    return payload


def rollback_tool(actor: Actor, tool_id: str, body: Mapping[str, Any]) -> dict[str, Any]:
    _require_admin(actor)
    version_id = _require_text(body, "version_id")
    conn = _connect()
    try:
        with _tx(conn):
            row = _tool_row(conn, actor, tool_id)
            version = _version_row(conn, tool_id, version_id)
            if version["state"] == "deprecated":
                raise ToolLifecycleError("version_deprecated", "已废弃版本不能回滚为当前版本", 409)
            if version["tenant_id"] != actor.tenant_id:
                raise ToolLifecycleError("unknown_version", "工具版本不存在", 404)
            at, _at_sh = _now()
            conn.execute(
                """
                UPDATE tools
                SET current_version_id = ?, name = ?, description = ?, updated_at = ?
                WHERE id = ? AND tenant_id = ?
                """,
                (version_id, version["name"], version["description"], at, tool_id, actor.tenant_id),
            )
            saved = _tool_row(conn, actor, tool_id)
            _audit(
                conn,
                actor,
                "rollback",
                tool_id,
                {"version_id": version_id, "from": row["current_version_id"]},
            )
            payload = _public_tool(conn, saved)
    finally:
        conn.close()
    _bump()
    return payload


def deprecate_version(actor: Actor, tool_id: str, body: Mapping[str, Any]) -> dict[str, Any]:
    _require_admin(actor)
    version_id = _require_text(body, "version_id")
    conn = _connect()
    try:
        with _tx(conn):
            row = _tool_row(conn, actor, tool_id)
            version = _version_row(conn, tool_id, version_id)
            if version["id"] == row["current_version_id"]:
                raise ToolLifecycleError("cannot_deprecate_current", "不能废弃当前稳定版本", 409)
            conn.execute("UPDATE versions SET state = 'deprecated' WHERE id = ?", (version_id,))
            _audit(conn, actor, "deprecate", tool_id, {"version_id": version_id})
            payload = _public_tool(conn, _tool_row(conn, actor, tool_id))
    finally:
        conn.close()
    _bump()
    return payload


def list_tools(actor: Actor, query: Mapping[str, Any]) -> dict[str, Any]:
    _ensure_actor_known(actor)
    page, page_size, status, scope, text = _list_args(query)
    key = (
        "list",
        actor.tenant_id,
        actor.role,
        actor.employee_id,
        text,
        status,
        scope,
        page,
        page_size,
    )

    def build() -> dict[str, Any]:
        return _list_uncached(actor, text, status, scope, page, page_size)

    return _cached(key, build)


def _list_args(query: Mapping[str, Any]) -> tuple[int, int, str, str, str]:
    try:
        page = int(query.get("page") or 1)
        page_size = int(query.get("page_size") or 20)
    except (TypeError, ValueError) as exc:
        raise ToolLifecycleError("invalid_page", "分页参数不合法", 400) from exc
    if page < 1 or page_size < 1 or page_size > 100:
        raise ToolLifecycleError("invalid_page", "分页参数不合法", 400)
    status = str(query.get("status") or "").strip()
    scope = str(query.get("scope") or "").strip()
    if status and status not in {"draft", "published", "offline"}:
        raise ToolLifecycleError("invalid_filter", "状态过滤不合法", 400)
    if scope and scope not in _SCOPES:
        raise ToolLifecycleError("invalid_filter", "范围过滤不合法", 400)
    return page, page_size, status, scope, str(query.get("q") or "").strip()


def _list_uncached(
    actor: Actor, text: str, status: str, scope: str, page: int, page_size: int
) -> dict[str, Any]:
    clauses = ["tenant_id = ?"]
    params: list[Any] = [actor.tenant_id]
    if actor.role != "admin":
        clauses.append("status = 'published'")
    if status:
        clauses.append("status = ?")
        params.append(status)
    if scope:
        clauses.append("scope = ?")
        params.append(scope)
    if text:
        escaped = text.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{escaped}%"
        clauses.append(
            "(lower(tool_key) LIKE ? ESCAPE '\\' OR lower(name) LIKE ? ESCAPE '\\' OR lower(description) LIKE ? ESCAPE '\\')"
        )
        params.extend([like, like, like])
    where = " AND ".join(clauses)
    conn = _connect()
    try:
        total = int(
            conn.execute(f"SELECT COUNT(*) AS n FROM tools WHERE {where}", params).fetchone()["n"]
        )
        rows = conn.execute(
            f"""
            SELECT * FROM tools WHERE {where}
            ORDER BY updated_at DESC, id ASC
            LIMIT ? OFFSET ?
            """,
            [*params, page_size, (page - 1) * page_size],
        ).fetchall()
        items = []
        for row in rows:
            if actor.role != "admin" and not _can_invoke(conn, actor, row, quiet=True):
                continue
            items.append(_public_tool(conn, row))
    finally:
        conn.close()
    return {"page": page, "page_size": page_size, "total": total, "items": items}


def get_tool(actor: Actor, tool_id: str) -> dict[str, Any]:
    _ensure_actor_known(actor)
    conn = _connect()
    try:
        row = _tool_row(conn, actor, tool_id)
        if actor.role != "admin" and (
            row["status"] != "published" or not _can_invoke(conn, actor, row, quiet=True)
        ):
            raise ToolLifecycleError("unknown_tool", "工具不存在", 404)
        versions = conn.execute(
            """
            SELECT id, version_no, state, actor_id, created_at, created_at_shanghai, schema_json, description
            FROM versions WHERE tool_id = ? ORDER BY version_no ASC
            """,
            (tool_id,),
        ).fetchall()
        payload = _public_tool(conn, row)
        if actor.role == "admin":
            payload["calls"] = [
                {
                    "id": call["id"],
                    "version_id": call["version_id"],
                    "definition": json.loads(call["definition_json"]),
                    "status": call["status"],
                    "started_at": call["started_at"],
                }
                for call in conn.execute(
                    "SELECT * FROM calls WHERE tenant_id = ? AND tool_id = ? ORDER BY started_at ASC",
                    (actor.tenant_id, tool_id),
                ).fetchall()
            ]
        payload["versions"] = [
            {
                "id": item["id"],
                "version_no": item["version_no"],
                "state": item["state"],
                "actor_id": item["actor_id"],
                "at": item["created_at"],
                "at_shanghai": item["created_at_shanghai"],
                "description": item["description"],
                "parameters": json.loads(item["schema_json"]),
            }
            for item in versions
        ]
        return payload
    finally:
        conn.close()


def _ensure_actor_known(actor: Actor) -> None:
    conn = _connect()
    try:
        _ensure_principal(conn, actor)
    finally:
        conn.close()


def discovery(actor: Actor) -> dict[str, Any]:
    _ensure_actor_known(actor)
    key = ("discovery", actor.tenant_id, actor.role, actor.employee_id)

    def build() -> dict[str, Any]:
        conn = _connect()
        try:
            rows = conn.execute(
                """
                SELECT * FROM tools
                WHERE tenant_id = ? AND status = 'published'
                ORDER BY tool_key ASC
                """,
                (actor.tenant_id,),
            ).fetchall()
            tools = []
            for row in rows:
                if _can_invoke(conn, actor, row, quiet=True):
                    tools.append(_runtime_spec(conn, row))
            return {"tools": tools}
        finally:
            conn.close()

    return _cached(key, build)


def _runtime_spec(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    version = _version_row(conn, row["id"], row["current_version_id"])
    schema = json.loads(version["schema_json"])
    spec = function_spec(row["tool_key"], version["description"], schema)
    spec["tool_id"] = row["id"]
    spec["version_id"] = version["id"]
    return spec


def discovery_for_runtime(employee_id: str) -> list[dict[str, Any]]:
    from app.infrastructure.tenant_scope import current_tenant_id

    tenant = current_tenant_id()
    if tenant is None or not str(employee_id or "").strip():
        return []
    actor = Actor(
        actor_id=str(employee_id),
        role="employee",
        employee_id=str(employee_id),
        tenant_id=int(tenant),
    )
    conn = _connect()
    try:
        _ensure_principal(conn, actor)
    except ToolLifecycleError:
        conn.close()
        return []
    else:
        conn.close()
    try:
        return list(discovery(actor)["tools"])
    except ToolLifecycleError:
        return []


def _can_invoke(conn: sqlite3.Connection, actor: Actor, row: sqlite3.Row, *, quiet: bool) -> bool:
    try:
        _assert_invoke(conn, actor, row, None)
    except ToolLifecycleError:
        if quiet:
            return False
        raise
    return True


def _assert_invoke(
    conn: sqlite3.Connection, actor: Actor, row: sqlite3.Row, version: sqlite3.Row | None
) -> None:
    if row["status"] == "offline":
        raise ToolLifecycleError("tool_offline", "工具已下线，拒绝调用", 409)
    if row["status"] != "published":
        raise ToolLifecycleError("tool_not_published", "未发布的工具不能调用", 403)
    if version is not None and version["state"] == "deprecated":
        raise ToolLifecycleError("version_deprecated", "该版本已废弃，拒绝调用", 409)
    if actor.role == "readonly":
        raise ToolLifecycleError("invoke_forbidden", "只读角色不能调用工具", 403)
    if actor.role == "admin":
        return
    if actor.role != "employee":
        raise ToolLifecycleError("invoke_forbidden", "当前角色不能调用工具", 403)
    _ensure_principal(conn, actor)
    if _active_effect(
        conn, row["id"], "employee", actor.employee_id or "", "deny"
    ) or _active_effect(conn, row["id"], "role", "employee", "deny"):
        raise ToolLifecycleError("invoke_denied", "调用已被拒绝", 403)
    if row["scope"] == "employee" and row["employee_id"] != actor.employee_id:
        raise ToolLifecycleError("invoke_forbidden", "工具未授权给该员工", 403)
    subject_type = "employee" if row["scope"] == "employee" else "role"
    subject_id = row["employee_id"] if row["scope"] == "employee" else "employee"
    if not _active_effect(conn, row["id"], subject_type, str(subject_id or ""), "grant"):
        raise ToolLifecycleError("invoke_forbidden", "没有调用授权", 403)


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


def invoke_tool(
    actor: Actor,
    tool_id: str,
    body: Mapping[str, Any],
    *,
    by_key: str | None = None,
) -> dict[str, Any]:
    args = (
        body.get("arguments") if isinstance(body.get("arguments"), dict) else body.get("arguments")
    )
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise ToolLifecycleError("invalid_arguments", "arguments 必须是对象", 400)
    version_id = str(body.get("version_id") or "").strip() or None
    conn = _connect()
    try:
        with _tx(conn):
            row = _resolve_invoke_row(conn, actor, tool_id, by_key)
            version = _version_row(conn, row["id"], version_id or row["current_version_id"])
            if version["tenant_id"] != actor.tenant_id:
                raise ToolLifecycleError("unknown_version", "工具版本不存在", 404)
            _assert_invoke(conn, actor, row, version)
            schema = json.loads(version["schema_json"])
            try:
                validated = apply_arguments(schema, args)
            except ToolLifecycleError as exc:
                if version_id and exc.code in {
                    "type_mismatch",
                    "unexpected_property",
                    "field_required",
                }:
                    raise ToolLifecycleError(
                        "incompatible_params",
                        "参数与指定版本的 Schema 不兼容",
                        400,
                        field=exc.extra.get("field", ""),
                    ) from exc
                raise
            spec = function_spec(row["tool_key"], version["description"], schema)
            call_id = uuid.uuid4().hex
            at, _at_sh = _now()
            result = {
                "ok": True,
                "success": True,
                "call_id": call_id,
                "tool_id": row["id"],
                "version_id": version["id"],
                "validated": validated,
                "definition": spec,
            }
            conn.execute(
                """
                INSERT INTO calls (
                  id, tenant_id, tool_id, version_id, definition_json, args_json, status,
                  actor_id, employee_id, started_at, finished_at, result_json
                ) VALUES (?, ?, ?, ?, ?, ?, 'ok', ?, ?, ?, ?, ?)
                """,
                (
                    call_id,
                    actor.tenant_id,
                    row["id"],
                    version["id"],
                    _dumps(spec),
                    _dumps(validated),
                    actor.actor_id,
                    actor.employee_id,
                    at,
                    at,
                    _dumps(result),
                ),
            )
    finally:
        conn.close()
    return result


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
        return row
    return _tool_row(conn, actor, tool_id)


def apply_arguments(schema: Mapping[str, Any], args: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(args, dict):
        raise ToolLifecycleError("invalid_arguments", "arguments 必须是对象", 400)
    return _apply_object(schema, args, "")


def _apply_object(schema: Mapping[str, Any], args: Mapping[str, Any], path: str) -> dict[str, Any]:
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    additional = bool(schema.get("additionalProperties", False))
    unknown = [key for key in args if key not in props]
    if unknown and not additional:
        raise ToolLifecycleError(
            "unexpected_property", f"不允许的字段 {unknown[0]}", 400, field=str(unknown[0])
        )
    filled: dict[str, Any] = {}
    for name, spec in props.items():
        if name not in args:
            if "default" in spec:
                filled[name] = _check_type(spec, spec.get("default"), _join(path, name))
            elif name in required:
                raise ToolLifecycleError("field_required", f"缺少必填参数 {name}", 400, field=name)
            continue
        filled[name] = _check_type(spec, args[name], _join(path, name))
    if additional:
        for name in unknown:
            if str(name).lower().replace("-", "_") in _SECRET_KEYS:
                continue
            filled[name] = args[name]
    return filled


def _join(path: str, name: str) -> str:
    return name if not path else f"{path}.{name}"


def _check_type(spec: Mapping[str, Any], value: Any, path: str) -> Any:
    kind = spec.get("type")
    if kind == "string":
        if not isinstance(value, str):
            raise ToolLifecycleError("type_mismatch", f"{path} 必须是字符串", 400, field=path)
        return value
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ToolLifecycleError("type_mismatch", f"{path} 必须是整数", 400, field=path)
        return value
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ToolLifecycleError("type_mismatch", f"{path} 必须是数字", 400, field=path)
        return value
    if kind == "boolean":
        if not isinstance(value, bool):
            raise ToolLifecycleError("type_mismatch", f"{path} 必须是布尔值", 400, field=path)
        return value
    if kind == "array":
        if not isinstance(value, list):
            raise ToolLifecycleError("type_mismatch", f"{path} 必须是数组", 400, field=path)
        return [
            _check_type(spec.get("items") or {"type": "string"}, item, f"{path}[]")
            for item in value
        ]
    if kind == "object":
        if not isinstance(value, dict):
            raise ToolLifecycleError("type_mismatch", f"{path} 必须是对象", 400, field=path)
        nested = {
            "properties": spec.get("properties") or {},
            "required": spec.get("required") or [],
            "additionalProperties": spec.get("additionalProperties", False),
        }
        return _apply_object(nested, value, path)
    raise ToolLifecycleError("type_mismatch", f"{path} 类型不受支持", 400, field=path)


def begin_call(actor: Actor, tool_id: str, body: Mapping[str, Any]) -> dict[str, Any]:
    result = invoke_tool(actor, tool_id, body)
    conn = _connect()
    try:
        with _tx(conn):
            conn.execute(
                "UPDATE calls SET status = 'inflight', finished_at = NULL WHERE id = ?",
                (result["call_id"],),
            )
    finally:
        conn.close()
    result["status"] = "inflight"
    return result


def finish_call(actor: Actor, call_id: str) -> dict[str, Any]:
    conn = _connect()
    try:
        with _tx(conn):
            row = conn.execute(
                "SELECT * FROM calls WHERE id = ? AND tenant_id = ?", (call_id, actor.tenant_id)
            ).fetchone()
            if row is None or row["status"] not in {"inflight", "ok"}:
                raise ToolLifecycleError("unknown_call", "调用不存在", 404)
            if actor.role != "admin" and row["actor_id"] != actor.actor_id:
                raise ToolLifecycleError("unknown_call", "调用不存在", 404)
            at, _at_sh = _now()
            definition = json.loads(row["definition_json"])
            validated = json.loads(row["args_json"])
            result = {
                "ok": True,
                "success": True,
                "call_id": row["id"],
                "tool_id": row["tool_id"],
                "version_id": row["version_id"],
                "validated": validated,
                "definition": definition,
                "status": "ok",
            }
            conn.execute(
                "UPDATE calls SET status = 'ok', finished_at = ?, result_json = ? WHERE id = ?",
                (at, _dumps(result), call_id),
            )
    finally:
        conn.close()
    return result


def set_permission(actor: Actor, body: Mapping[str, Any]) -> dict[str, Any]:
    _require_admin(actor)
    tool_id = _require_text(body, "tool_id")
    subject_type = _require_text(body, "subject_type")
    subject_id = _require_text(body, "subject_id")
    effect = _require_text(body, "effect")
    if subject_type not in {"employee", "role"} or effect not in {"grant", "deny"}:
        raise ToolLifecycleError("invalid_permission", "授权参数不合法", 400)
    conn = _connect()
    try:
        with _tx(conn):
            _tool_row(conn, actor, tool_id)
            if subject_type == "employee":
                found = conn.execute(
                    "SELECT 1 FROM principals WHERE tenant_id = ? AND principal_id = ?",
                    (actor.tenant_id, subject_id),
                ).fetchone()
                if found is None:
                    raise ToolLifecycleError("forged_employee", "员工不存在", 404)
            elif subject_id not in _ROLES:
                raise ToolLifecycleError("invalid_permission", "角色不存在", 400)
            existing = conn.execute(
                """
                SELECT id FROM permissions
                WHERE tenant_id = ? AND tool_id = ? AND subject_type = ? AND subject_id = ?
                  AND effect = ? AND revoked_at IS NULL
                """,
                (actor.tenant_id, tool_id, subject_type, subject_id, effect),
            ).fetchone()
            if existing is not None:
                raise ToolLifecycleError("duplicate_permission", "相同授权已存在，未覆盖", 409)
            permission_id = uuid.uuid4().hex
            at, at_sh = _now()
            conn.execute(
                """
                INSERT INTO permissions (
                  id, tenant_id, tool_id, subject_type, subject_id, effect, actor_id,
                  created_at, created_at_shanghai
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    permission_id,
                    actor.tenant_id,
                    tool_id,
                    subject_type,
                    subject_id,
                    effect,
                    actor.actor_id,
                    at,
                    at_sh,
                ),
            )
            record = _audit(
                conn,
                actor,
                effect,
                tool_id,
                {
                    "permission_id": permission_id,
                    "subject_type": subject_type,
                    "subject_id": subject_id,
                },
            )
    finally:
        conn.close()
    _bump()
    return {"permission_id": permission_id, "effect": effect, "record": record}


def revoke_permission(actor: Actor, permission_id: str) -> dict[str, Any]:
    _require_admin(actor)
    conn = _connect()
    try:
        with _tx(conn):
            row = conn.execute(
                "SELECT * FROM permissions WHERE id = ? AND tenant_id = ?",
                (permission_id, actor.tenant_id),
            ).fetchone()
            if row is None:
                raise ToolLifecycleError("unknown_permission", "授权记录不存在", 404)
            if row["revoked_at"]:
                raise ToolLifecycleError("already_revoked", "授权已经撤销", 409)
            at, at_sh = _now()
            conn.execute(
                "UPDATE permissions SET revoked_at = ?, revoked_at_shanghai = ? WHERE id = ?",
                (at, at_sh, permission_id),
            )
            record = _audit(
                conn,
                actor,
                "revoke",
                row["tool_id"],
                {"permission_id": permission_id, "effect": row["effect"]},
            )
    finally:
        conn.close()
    _bump()
    return {"permission_id": permission_id, "record": record}


def list_audit(actor: Actor, tool_id: str | None = None) -> dict[str, Any]:
    _require_admin(actor)
    conn = _connect()
    try:
        if tool_id:
            _tool_row(conn, actor, tool_id)
            rows = conn.execute(
                """
                SELECT * FROM events
                WHERE tenant_id = ? AND tool_id = ?
                ORDER BY id ASC
                """,
                (actor.tenant_id, tool_id),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM events WHERE tenant_id = ? ORDER BY id ASC", (actor.tenant_id,)
            ).fetchall()
        return {
            "events": [
                {
                    "id": row["id"],
                    "tool_id": row["tool_id"],
                    "kind": row["kind"],
                    "actor_id": row["actor_id"],
                    "actor_role": row["actor_role"],
                    "at": row["at"],
                    "at_shanghai": row["at_shanghai"],
                    "detail": json.loads(row["detail_json"]),
                }
                for row in rows
            ]
        }
    finally:
        conn.close()


def execute_if_registered(
    name: str, args: Any, runtime_context: Mapping[str, Any] | None
) -> str | None:
    from app.infrastructure.tenant_scope import current_tenant_id

    tenant = current_tenant_id()
    if tenant is None or not str(name or "").strip():
        return None
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id FROM tools WHERE tenant_id = ? AND tool_key = ?",
            (int(tenant), str(name)),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    context = dict(runtime_context or {})
    employee_id = str(context.get("employee_id") or "")
    if isinstance(args, str):
        try:
            args = json.loads(args or "{}")
        except json.JSONDecodeError:
            args = {}
    actor = Actor(
        actor_id=employee_id or "employee",
        role="employee",
        employee_id=employee_id or None,
        tenant_id=int(tenant),
    )
    body = {
        "arguments": args if isinstance(args, dict) else {},
        "version_id": context.get("version_id"),
    }
    try:
        result = invoke_tool(actor, row["id"], body)
    except ToolLifecycleError as exc:
        result = {
            "ok": False,
            "success": False,
            "error": {"code": exc.code, "message": exc.message},
        }
    return json.dumps(result, ensure_ascii=False)


def calls_for(actor: Actor, tool_id: str) -> list[dict[str, Any]]:
    _require_admin(actor)
    conn = _connect()
    try:
        _tool_row(conn, actor, tool_id)
        rows = conn.execute(
            "SELECT * FROM calls WHERE tenant_id = ? AND tool_id = ? ORDER BY started_at ASC",
            (actor.tenant_id, tool_id),
        ).fetchall()
        return [
            {
                "id": row["id"],
                "version_id": row["version_id"],
                "definition": json.loads(row["definition_json"]),
                "arguments": json.loads(row["args_json"]),
                "status": row["status"],
                "started_at": row["started_at"],
            }
            for row in rows
        ]
    finally:
        conn.close()
