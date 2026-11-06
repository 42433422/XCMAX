"""Tenant-scoped AI tool register, publish, discovery, and invoke.

Global publish means every employee of the owning tenant. It never crosses
tenants. The tenant id always comes from the server auth context.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from collections.abc import Mapping
from typing import Any

from app.application.agent_tool_contracts import (
    Actor as Actor,
)
from app.application.agent_tool_contracts import (
    ToolLifecycleError as ToolLifecycleError,
)
from app.application.agent_tool_contracts import (
    _dumps,
    _redact,
    _require_text,
)
from app.application.agent_tool_contracts import (
    apply_arguments as apply_arguments,
)
from app.application.agent_tool_contracts import (
    function_spec as function_spec,
)
from app.application.agent_tool_contracts import (
    validate_input_schema as validate_input_schema,
)
from app.application.agent_tool_history import read_audit, read_calls, tool_history
from app.application.agent_tool_registry_store import (
    _DDL as _DDL,
)
from app.application.agent_tool_registry_store import (
    _active_effect,
    _audit,
    _audit_outside,
    _bump,
    _cached,
    _connect,
    _ensure_principal,
    _insert_grant,
    _insert_version,
    _now,
    _public_tool,
    _resolve_invoke_row,
    _runtime_spec,
    _snapshot_version,
    _tool_row,
    _tx,
    _version_row,
)
from app.application.agent_tool_registry_store import (
    db_path as db_path,
)
from app.application.agent_tool_registry_store import (
    logger as logger,
)
from app.application.agent_tool_registry_store import (
    reset_for_tests as reset_for_tests,
)
from app.utils.operational_errors import BOUNDARY_ERRORS

_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")


_PRINCIPAL_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


_ROLES = {"admin", "employee", "readonly"}


_SCOPES = {"global", "tenant", "employee"}


def _require_admin(actor: Actor) -> None:
    if actor.role != "admin":
        raise ToolLifecycleError("admin_required", "只有管理员可以修改工具注册信息", 403)


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
        expected = int(body["expected_version"])
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
            conn.execute("SELECT COUNT(*) AS n FROM tools WHERE " + where, params).fetchone()["n"]
        )
        rows = conn.execute(
            "SELECT * FROM tools WHERE "
            + where
            + " ORDER BY updated_at DESC, id ASC LIMIT ? OFFSET ?",
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


def get_tool(actor: Actor, tool_id: str, query: Mapping[str, Any] | None = None) -> dict[str, Any]:
    page, page_size, *_ = _list_args({"page_size": 100, **(query or {})})
    _ensure_actor_known(actor)
    conn = _connect()
    try:
        row = _tool_row(conn, actor, tool_id)
        if actor.role != "admin" and (
            row["status"] != "published" or not _can_invoke(conn, actor, row, quiet=True)
        ):
            raise ToolLifecycleError("unknown_tool", "工具不存在", 404)
        return tool_history(conn, actor, row, page, page_size)
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
            )
            tools = []
            for row in rows:
                if _can_invoke(conn, actor, row, quiet=True):
                    tools.append(_runtime_spec(conn, row))
            return {"tools": tools}
        finally:
            conn.close()

    return _cached(key, build)


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


def list_audit(
    actor: Actor, tool_id: str | None = None, query: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    _require_admin(actor)
    page, page_size, *_ = _list_args({"page_size": 100, **(query or {})})
    return read_audit(actor, tool_id, page, page_size)


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


def calls_for(
    actor: Actor, tool_id: str, *, page: int = 1, page_size: int = 100
) -> list[dict[str, Any]]:
    _require_admin(actor)
    page, page_size, *_ = _list_args({"page": page, "page_size": page_size})
    conn = _connect()
    try:
        _tool_row(conn, actor, tool_id)
        calls, _ = read_calls(conn, actor, tool_id, page, page_size)
        return calls
    finally:
        conn.close()
