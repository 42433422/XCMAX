"""Tenant-scoped, paginated projections of tool versions, calls, and audit events."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.application.agent_tool_contracts import Actor
from app.application.agent_tool_registry_store import _connect, _public_tool, _tool_row


def read_calls(
    conn: sqlite3.Connection, actor: Actor, tool_id: str, page: int, page_size: int
) -> tuple[list[dict[str, Any]], int]:
    total = int(
        conn.execute(
            "SELECT COUNT(*) FROM calls WHERE tenant_id = ? AND tool_id = ?",
            (actor.tenant_id, tool_id),
        ).fetchone()[0]
    )
    rows = conn.execute(
        "SELECT id, version_id, definition_json, args_json, status, started_at FROM calls "
        "WHERE tenant_id = ? AND tool_id = ? ORDER BY rowid ASC LIMIT ? OFFSET ?",
        (actor.tenant_id, tool_id, page_size, (page - 1) * page_size),
    )
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
    ], total


def tool_history(
    conn: sqlite3.Connection, actor: Actor, row: sqlite3.Row, page: int, page_size: int
) -> dict[str, Any]:
    tool_id = row["id"]
    versions = conn.execute(
        "SELECT id, version_no, state, actor_id, created_at, created_at_shanghai, "
        "schema_json, description FROM versions WHERE tool_id = ? AND tenant_id = ? "
        "ORDER BY version_no ASC LIMIT ? OFFSET ?",
        (tool_id, actor.tenant_id, page_size, (page - 1) * page_size),
    )
    payload = _public_tool(conn, row)
    payload.update(history_page=page, history_page_size=page_size)
    payload["versions_total"] = int(
        conn.execute(
            "SELECT COUNT(*) FROM versions WHERE tool_id = ? AND tenant_id = ?",
            (tool_id, actor.tenant_id),
        ).fetchone()[0]
    )
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
    if actor.role == "admin":
        calls, total = read_calls(conn, actor, tool_id, page, page_size)
        payload["calls"] = [
            {key: value for key, value in call.items() if key != "arguments"} for call in calls
        ]
        payload["calls_total"] = total
    return payload


def read_audit(actor: Actor, tool_id: str | None, page: int, page_size: int) -> dict[str, Any]:
    conn = _connect()
    try:
        clause = "tenant_id = ?"
        params: list[Any] = [actor.tenant_id]
        if tool_id:
            _tool_row(conn, actor, tool_id)
            clause += " AND tool_id = ?"
            params.append(tool_id)
        total = int(
            conn.execute("SELECT COUNT(*) FROM events WHERE " + clause, params).fetchone()[0]
        )
        rows = conn.execute(
            "SELECT id, tool_id, kind, actor_id, actor_role, at, at_shanghai, detail_json "
            "FROM events WHERE " + clause + " ORDER BY id ASC LIMIT ? OFFSET ?",
            [*params, page_size, (page - 1) * page_size],
        )
        return {
            "page": page,
            "page_size": page_size,
            "total": total,
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
            ],
        }
    finally:
        conn.close()
