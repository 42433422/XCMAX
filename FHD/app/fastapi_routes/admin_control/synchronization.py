"""Sync queue application, reconciliation actions, and resumable event delivery."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable

from fastapi import Body, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.application.admin_control.protocols import ErrorPolicy, SyncStore


class Synchronization:
    def __init__(
        self,
        *,
        errors: ErrorPolicy,
        store: Callable[[], SyncStore],
        poll_interval: Callable[[], float],
        remote_host: Callable[[], str],
        remote_port: Callable[[], int],
        stream: Callable[[Request, int], AsyncIterator[str]],
    ) -> None:
        self._errors = errors
        self._store = store
        self._poll_interval = poll_interval
        self._remote_host = remote_host
        self._remote_port = remote_port
        self._stream = stream

    async def _sync_sse_generator(self, request: Request, since_cursor: int):
        """持续产生 SSE 事件：每隔 SYNC_POLL_INTERVAL_S 秒检查一次本地变更日志。"""
        import json as _json

        cursor = since_cursor
        connected = _json.dumps({"type": "connected", "cursor": since_cursor}, ensure_ascii=False)
        yield f"data: {connected}\n\n"
        while True:
            if await request.is_disconnected():
                break
            try:
                db = self._store()
                rows = db.get_changes(since_cursor=cursor, limit=50)
                if rows:
                    cursor = rows[-1]["id"]
                    data = _json.dumps(
                        {"cursor": cursor, "changes": rows}, ensure_ascii=False, default=str
                    )
                    yield f"data: {data}\n\n"
                else:
                    status = db.get_status()
                    heartbeat = _json.dumps(
                        {"type": "heartbeat", "cursor": cursor, "status": status},
                        ensure_ascii=False,
                        default=str,
                    )
                    yield f"data: {heartbeat}\n\n"
            except self._errors.recoverable() as exc:
                err = _json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False)
                yield f"data: {err}\n\n"
            await asyncio.sleep(self._poll_interval())

    async def sync_status(self):
        """获取双向同步健康状态。"""
        try:
            db = self._store()
            info = db.get_status()
            return {"success": True, "data": info}
        except self._errors.recoverable() as exc:
            self._errors.logger.debug("sync_status db read failed: %s", exc)
            return {
                "success": True,
                "data": {
                    "healthy": False,
                    "local_cursor": None,
                    "remote_cursor": None,
                    "outbox_count": 0,
                    "last_sync_at": None,
                    "conflict_count": 0,
                    "note": "同步数据库尚未初始化，请先完成 sync-foundation 阶段。",
                },
            }

    async def sync_push(self):
        """触发本地 outbox 向服务器推送。"""
        try:
            from app.application.xcmax_sync_app import push_outbox

            result = push_outbox(remote_host=self._remote_host(), remote_port=self._remote_port())
            return {"success": True, "data": result}
        except self._errors.recoverable() as exc:
            self._errors.logger.warning("sync_push failed: %s", exc)
            return JSONResponse({"success": False, "message": f"推送失败: {exc}"}, status_code=500)

    async def sync_changes(
        self, since_cursor: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000)
    ):
        """获取变更日志（支持断线补拉）。"""
        try:
            db = self._store()
            rows = db.get_changes(since_cursor=since_cursor, limit=limit)
            return {"success": True, "data": rows, "count": len(rows)}
        except self._errors.recoverable() as exc:
            self._errors.logger.debug("sync_changes read failed: %s", exc)
            return {"success": True, "data": [], "count": 0, "note": str(exc)}

    async def sync_receive(self, body: dict | list = Body(default=None)):
        """接收远端推来的变更，写入 inbox，立即尝试应用，并记录审计日志。

        须携带 ``X-XCMAX-Sync-Token``（与 ``XCMAX_SYNC_SHARED_SECRET`` 一致）。"""
        if body is None:
            return JSONResponse({"success": False, "message": "missing body"}, status_code=400)
        try:
            db = self._store()
            items = body if isinstance(body, list) else [body]
            written = db.enqueue_inbox(items)
            try:
                from app.application.xcmax_sync_app import apply_inbox

                result = apply_inbox(limit=len(items) + 50)
            except self._errors.recoverable() as ae:
                result = {"applied": 0, "error": str(ae)}
            try:
                from app.mod_sdk.audit import write_audit_event

                write_audit_event(
                    actor=None,
                    action="xcmax.sync.receive",
                    payload={"received": written, "apply": result},
                )
            except self._errors.recoverable():
                pass
            return {"success": True, "received": written, "apply_result": result}
        except self._errors.recoverable() as exc:
            self._errors.logger.warning("sync_receive failed: %s", exc)
            return JSONResponse({"success": False, "message": str(exc)}, status_code=500)

    async def sync_pull(self):
        """主动从远端拉取增量变更并应用到本地。"""
        try:
            from app.application.xcmax_sync_app import apply_inbox, pull_from_remote

            pull_result = pull_from_remote(
                remote_host=self._remote_host(), remote_port=self._remote_port()
            )
            apply_result = apply_inbox()
            return {"success": True, "data": {"pull": pull_result, "apply": apply_result}}
        except self._errors.recoverable() as exc:
            self._errors.logger.warning("sync_pull failed: %s", exc)
            return JSONResponse({"success": False, "message": str(exc)}, status_code=500)

    async def list_conflicts(self, limit: int = Query(50, ge=1, le=500)):
        """列出 inbox 中待处理的冲突条目。"""
        try:
            from app.application.admin_sync_app_service import list_admin_sync_conflicts

            data = list_admin_sync_conflicts(limit=limit)
            return {"success": True, "data": data, "count": len(data)}
        except self._errors.recoverable() as exc:
            return {"success": True, "data": [], "count": 0, "note": str(exc)}

    async def resolve_conflict(self, inbox_id: int, body: dict):
        """手动解决指定冲突（action: 'apply' | 'skip'）。"""
        action = str(body.get("action") or "skip").strip()
        try:
            db = self._store()
            if action == "apply":
                from app.application.admin_sync_app_service import fetch_admin_inbox_row
                from app.application.xcmax_sync_app import entity_appliers

                row = fetch_admin_inbox_row(inbox_id)
                if row:
                    applier = entity_appliers().get(row["entity_type"])
                    if applier:
                        applier(row)
                db.mark_inbox_applied(inbox_id)
            else:
                from app.application.admin_sync_app_service import mark_admin_inbox_skipped

                mark_admin_inbox_skipped(inbox_id)
            return {"success": True, "inbox_id": inbox_id, "action": action}
        except self._errors.recoverable() as exc:
            return JSONResponse({"success": False, "message": str(exc)}, status_code=500)

    async def sync_stream(self, request: Request, since_cursor: int = Query(0, ge=0)):
        """专用 SSE 同步流：服务端实时推送本地变更（与 AI chat streaming 完全分离）。

        客户端监听示例：
            const es = new EventSource('/api/xcmax/sync/stream?since_cursor=0')
            es.onmessage = e => { const d = JSON.parse(e.data); console.log(d) }
        """
        return StreamingResponse(
            self._stream(request, since_cursor),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
