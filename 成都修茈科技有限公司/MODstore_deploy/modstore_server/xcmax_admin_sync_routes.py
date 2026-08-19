# ruff: noqa
"""XCmax server-side synchronization routes."""
from __future__ import annotations
import asyncio
import importlib
import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any
from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

logger = logging.getLogger("modstore_server.xcmax_admin_api")
router = APIRouter(prefix="/api/xcmax", tags=["xcmax-admin"])


def _facade():
    return importlib.import_module("modstore_server.xcmax_admin_api")


def _last_change_id(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(id) AS mx FROM xcmax_changes").fetchone()
    return int(row["mx"] or 0)


def _inbox_pending_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(1) AS c FROM xcmax_inbox WHERE status='pending'").fetchone()
    return int(row["c"] or 0)


def _inbox_conflict_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(1) AS c FROM xcmax_inbox WHERE status='conflict'").fetchone()
    return int(row["c"] or 0)


@router.get("/sync/status", response_model=None)
async def sync_status() -> dict[str, Any]:
    _facade()._ensure_schema()
    try:
        with _facade()._connect() as conn:
            local_cursor = _facade()._last_change_id(conn)
            remote_cursor = int(_facade()._meta_get(conn, "remote_cursor", "0") or 0)
            outbox_count = _facade()._inbox_pending_count(conn)
            conflict_count = _facade()._inbox_conflict_count(conn)
            last_sync_at = _facade()._meta_get(conn, "last_sync_at", "")
        return {
            "success": True,
            "data": {
                "healthy": True,
                "local_cursor": local_cursor,
                "remote_cursor": remote_cursor,
                "outbox_count": outbox_count,
                "last_sync_at": last_sync_at or None,
                "conflict_count": conflict_count,
                "role": "server",
            },
        }
    except Exception as exc:
        _facade().logger.warning("sync_status failed: %s", exc)
        return {
            "success": True,
            "data": {
                "healthy": False,
                "local_cursor": None,
                "remote_cursor": None,
                "outbox_count": 0,
                "last_sync_at": None,
                "conflict_count": 0,
                "role": "server",
                "note": str(exc),
            },
        }


@router.get("/sync/changes", response_model=None)
async def sync_changes(
    since_cursor: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000)
) -> dict[str, Any]:
    """供本地节点拉取增量。"""
    _facade()._ensure_schema()
    try:
        with _facade()._connect() as conn:
            rows = conn.execute(
                "SELECT id, entity_type, entity_id, operation, payload_json, version, actor, origin_node, created_at FROM xcmax_changes WHERE id > ? ORDER BY id ASC LIMIT ?",
                (int(since_cursor), int(limit)),
            ).fetchall()
        data: list[dict[str, Any]] = []
        for r in rows:
            try:
                payload = json.loads(r["payload_json"] or "{}")
            except Exception:
                payload = {}
            data.append(
                {
                    "id": r["id"],
                    "entity_type": r["entity_type"],
                    "entity_id": r["entity_id"],
                    "operation": r["operation"],
                    "payload": payload,
                    "version": r["version"],
                    "actor": r["actor"],
                    "origin_node": r["origin_node"],
                    "created_at": r["created_at"],
                }
            )
        return {"success": True, "data": data, "count": len(data)}
    except Exception as exc:
        _facade().logger.warning("sync_changes failed: %s", exc)
        return {"success": True, "data": [], "count": 0, "note": str(exc)}


@router.post("/sync/receive", response_model=None)
async def sync_receive(body: dict | list = Body(default=None)) -> dict[str, Any]:
    """接收来自本地节点的变更。

    兼容 ``app/services/xcmax_sync_service.py`` 的单条 payload 与批量数组。"""
    _facade()._ensure_schema()
    if body is None:
        return _facade().JSONResponse(
            {"success": False, "message": "missing body"}, status_code=400
        )
    items = body if isinstance(body, list) else [body]
    written = 0
    now_iso = _facade().datetime.now(_facade().timezone.utc).isoformat()
    try:
        with _facade()._db_lock, _facade()._connect() as conn:
            for raw in items:
                if not isinstance(raw, dict):
                    continue
                entity_type = str(raw.get("entity_type") or "").strip()
                entity_id = str(raw.get("entity_id") or "").strip()
                operation = str(raw.get("operation") or "sync").strip()
                if not entity_type or not entity_id:
                    continue
                payload = raw.get("payload") or {}
                try:
                    payload_json = json.dumps(payload, ensure_ascii=False, default=str)
                except Exception:
                    payload_json = "{}"
                origin_node = str(raw.get("origin_node") or "remote").strip() or "remote"
                conn.execute(
                    "INSERT INTO xcmax_inbox(entity_type, entity_id, operation, payload_json, origin_node, status, received_at) VALUES(?, ?, ?, ?, ?, 'pending', ?)",
                    (entity_type, entity_id, operation, payload_json, origin_node, now_iso),
                )
                conn.execute(
                    "INSERT INTO xcmax_changes(entity_type, entity_id, operation, payload_json, version, actor, origin_node, created_at) VALUES(?, ?, ?, ?, 1, ?, ?, ?)",
                    (
                        entity_type,
                        entity_id,
                        operation,
                        payload_json,
                        str(raw.get("actor") or "remote"),
                        origin_node,
                        now_iso,
                    ),
                )
                written += 1
            _facade()._meta_set(conn, "last_sync_at", now_iso)
            conn.commit()
        return {
            "success": True,
            "received": written,
            "apply_result": {"applied": written, "conflicts": 0},
        }
    except Exception as exc:
        _facade().logger.warning("sync_receive failed: %s", exc)
        return _facade().JSONResponse({"success": False, "message": str(exc)}, status_code=500)


@router.post("/sync/push", response_model=None)
async def sync_push() -> dict[str, Any]:
    """服务器端通常不需要主动 push，但保留接口以便 UI 调用一致。"""
    _facade()._ensure_schema()
    return {
        "success": True,
        "data": {"sent": 0, "failed": 0, "total_pending": 0, "note": "server-side noop"},
    }


@router.post("/sync/pull", response_model=None)
async def sync_pull() -> dict[str, Any]:
    """占位：服务器端无远端可拉，返回空摘要。"""
    _facade()._ensure_schema()
    return {
        "success": True,
        "data": {"pull": {"pulled": 0}, "apply": {"applied": 0, "conflicts": 0}},
    }


@router.get("/sync/conflicts", response_model=None)
async def list_conflicts(limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    _facade()._ensure_schema()
    try:
        with _facade()._connect() as conn:
            rows = conn.execute(
                "SELECT id, entity_type, entity_id, operation, payload_json, conflict_note, received_at FROM xcmax_inbox WHERE status='conflict' ORDER BY id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        data: list[dict[str, Any]] = []
        for r in rows:
            try:
                payload = json.loads(r["payload_json"] or "{}")
            except Exception:
                payload = {}
            data.append(
                {
                    "id": r["id"],
                    "entity_type": r["entity_type"],
                    "entity_id": r["entity_id"],
                    "operation": r["operation"],
                    "payload": payload,
                    "conflict_note": r["conflict_note"],
                    "received_at": r["received_at"],
                }
            )
        return {"success": True, "data": data, "count": len(data)}
    except Exception as exc:
        return {"success": True, "data": [], "count": 0, "note": str(exc)}


@router.post("/sync/conflicts/{inbox_id}/resolve", response_model=None)
async def resolve_conflict(
    inbox_id: int, body: dict = Body(default_factory=dict)
) -> dict[str, Any]:
    _facade()._ensure_schema()
    action = str((body or {}).get("action") or "skip").strip()
    new_status = "applied" if action == "apply" else "skipped"
    try:
        with _facade()._db_lock, _facade()._connect() as conn:
            conn.execute("UPDATE xcmax_inbox SET status=? WHERE id=?", (new_status, int(inbox_id)))
            conn.commit()
        return {"success": True, "inbox_id": int(inbox_id), "action": action}
    except Exception as exc:
        return _facade().JSONResponse({"success": False, "message": str(exc)}, status_code=500)


SYNC_POLL_INTERVAL_S = float(os.environ.get("XCMAX_SYNC_POLL_S", "10"))


async def _sse_generator(request: Request, since_cursor: int):
    cursor = int(since_cursor)
    while True:
        if await request.is_disconnected():
            break
        try:
            _facade()._ensure_schema()
            with _facade()._connect() as conn:
                rows = conn.execute(
                    "SELECT id, entity_type, entity_id, operation, payload_json, created_at FROM xcmax_changes WHERE id > ? ORDER BY id ASC LIMIT 50",
                    (cursor,),
                ).fetchall()
                if rows:
                    cursor = int(rows[-1]["id"])
                    payload = {
                        "cursor": cursor,
                        "changes": [
                            {
                                "id": r["id"],
                                "entity_type": r["entity_type"],
                                "entity_id": r["entity_id"],
                                "operation": r["operation"],
                                "created_at": r["created_at"],
                            }
                            for r in rows
                        ],
                    }
                    yield f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
                else:
                    status = {
                        "healthy": True,
                        "local_cursor": _facade()._last_change_id(conn),
                        "remote_cursor": int(_facade()._meta_get(conn, "remote_cursor", "0") or 0),
                        "outbox_count": _facade()._inbox_pending_count(conn),
                        "last_sync_at": _facade()._meta_get(conn, "last_sync_at", "") or None,
                        "conflict_count": _facade()._inbox_conflict_count(conn),
                        "role": "server",
                    }
                    heartbeat = {"type": "heartbeat", "cursor": cursor, "status": status}
                    yield f"data: {json.dumps(heartbeat, ensure_ascii=False, default=str)}\n\n"
        except Exception as exc:
            err = {"type": "error", "message": str(exc)}
            yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"
        await asyncio.sleep(SYNC_POLL_INTERVAL_S)


@router.get("/sync/stream", response_model=None)
async def sync_stream(request: Request, since_cursor: int = Query(0, ge=0)):
    return StreamingResponse(
        _facade()._sse_generator(request, since_cursor),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
