# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.fastapi_routes.xcmax_admin")


async def _sync_sse_generator(request: _facade().Request, since_cursor: int):
    """持续产生 SSE 事件：每隔 SYNC_POLL_INTERVAL_S 秒检查一次本地变更日志。"""
    import json as _json

    cursor = since_cursor
    connected = _json.dumps({"type": "connected", "cursor": since_cursor}, ensure_ascii=False)
    yield f"data: {connected}\n\n"
    while True:
        if await request.is_disconnected():
            break
        try:
            from app.db.xcmax_sync import SyncDb

            db = SyncDb()
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
        except _facade().RECOVERABLE_ERRORS as exc:
            err = _json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False)
            yield f"data: {err}\n\n"
        await _facade().asyncio.sleep(_facade().SYNC_POLL_INTERVAL_S)


@_facade().router.get("/sync/conflicts", response_model=None)
async def list_conflicts(limit: int = _facade().Query(50, ge=1, le=500)):
    """列出 inbox 中待处理的冲突条目。"""
    try:
        from app.application.admin_sync_app_service import list_admin_sync_conflicts

        data = list_admin_sync_conflicts(limit=limit)
        return {"success": True, "data": data, "count": len(data)}
    except _facade().RECOVERABLE_ERRORS as exc:
        return {"success": True, "data": [], "count": 0, "note": str(exc)}


@_facade().router.post("/sync/conflicts/{inbox_id}/resolve", response_model=None)
async def resolve_conflict(inbox_id: int, body: dict):
    """手动解决指定冲突（action: 'apply' | 'skip'）。"""
    action = str(body.get("action") or "skip").strip()
    try:
        from app.db.xcmax_sync import SyncDb

        db = SyncDb()
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
    except _facade().RECOVERABLE_ERRORS as exc:
        return _facade().JSONResponse({"success": False, "message": str(exc)}, status_code=500)


@_facade().router.get("/sync/stream", response_model=None)
async def sync_stream(request: _facade().Request, since_cursor: int = _facade().Query(0, ge=0)):
    """专用 SSE 同步流：服务端实时推送本地变更（与 AI chat streaming 完全分离）。

    客户端监听示例：
        const es = new EventSource('/api/xcmax/sync/stream?since_cursor=0')
        es.onmessage = e => { const d = JSON.parse(e.data); console.log(d) }
    """
    return _facade().StreamingResponse(
        _facade()._sync_sse_generator(request, since_cursor),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _xcmax_market_proxy_impl(request: _facade().Request, subpath: str):
    """编制图 LLM / 员工执行等：经会话市场 token 转发至 MODstore ``/api/...``。"""
    method = request.method.upper()
    json_body: dict[str, _facade().Any] | None = None
    if method in {"POST", "PUT", "PATCH"}:
        try:
            body = await request.json()
            json_body = body if isinstance(body, dict) else None
        except _facade().RECOVERABLE_ERRORS:
            json_body = None
    api_path = f"/api/{str(subpath or '').lstrip('/')}"
    if api_path.startswith("/api/ops/self-maintenance/"):
        return await _facade()._self_maintenance_local_or_proxy(
            request, method, api_path, json_body=json_body
        )
    return await _facade()._market_admin_proxy(request, method, api_path, json_body=json_body)


def _register_market_proxy_method(method: str) -> None:

    async def endpoint(request: _facade().Request, subpath: str):
        return await _facade()._xcmax_market_proxy_impl(request, subpath)

    endpoint.__name__ = f"xcmax_market_proxy_{method.lower()}"
    endpoint.__qualname__ = endpoint.__name__
    _facade().router.add_api_route(
        "/market-proxy/{subpath:path}", endpoint, methods=[method], response_model=None
    )


def _to_int(value: _facade().Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _to_float(value: _facade().Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _collect_local_ledger() -> dict[str, _facade().Any]:
    """FHD 本地 token 账本（model_usage_ledger.json）。"""
    try:
        from app.infrastructure.billing.model_usage import list_model_usage_entries

        entries = list_model_usage_entries(limit=500)
    except _facade().RECOVERABLE_ERRORS as exc:
        return {"available": False, "reason": f"读取账本失败: {exc}"}
    prompt = sum(_facade()._to_int(e.get("prompt_tokens")) for e in entries)
    completion = sum(_facade()._to_int(e.get("completion_tokens")) for e in entries)
    total = sum(_facade()._to_int(e.get("total_tokens")) for e in entries)
    cost = sum(_facade()._to_float(e.get("cost_units")) for e in entries)
    by_model: dict[str, dict[str, _facade().Any]] = {}
    for e in entries:
        key = f"{e.get('provider', '?')}/{e.get('model', '?')}"
        slot = by_model.setdefault(key, {"total": 0, "count": 0, "cost": 0.0})
        slot["total"] += _facade()._to_int(e.get("total_tokens"))
        slot["count"] += 1
        slot["cost"] += _facade()._to_float(e.get("cost_units"))
    return {
        "available": True,
        "source": "FHD 本地账本",
        "records": len(entries),
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "cost_units": cost,
        "by_model": dict(sorted(by_model.items(), key=lambda x: -x[1]["total"])),
    }


def _collect_cursor_usage() -> dict[str, _facade().Any]:
    """Cursor 用量（cursor-usage CLI）。"""
    import shutil
    import subprocess

    cli = shutil.which("cursor-usage") or str(
        _facade().os.path.expanduser("~/Library/Python/3.9/bin/cursor-usage")
    )
    if not _facade().os.path.exists(cli):
        return {"available": False, "reason": f"cursor-usage CLI 不存在: {cli}"}
    try:
        proc = subprocess.run(
            [cli, "--json", "--days", "30"], capture_output=True, text=True, timeout=30
        )
    except _facade().RECOVERABLE_ERRORS as exc:
        return {"available": False, "reason": f"执行失败: {exc}"}
    if proc.returncode != 0:
        return {"available": False, "reason": f"exit={proc.returncode}"}
    try:
        raw = _facade().json.loads(proc.stdout)
    except _facade().RECOVERABLE_ERRORS as exc:
        return {"available": False, "reason": f"JSON 解析失败: {exc}"}
    aggs = raw.get("aggregations", []) if isinstance(raw, dict) else []
    total_input = sum(_facade()._to_int(a.get("inputTokens")) for a in aggs)
    total_output = sum(_facade()._to_int(a.get("outputTokens")) for a in aggs)
    total_cache_read = sum(_facade()._to_int(a.get("cacheReadTokens")) for a in aggs)
    total_cache_write = sum(_facade()._to_int(a.get("cacheWriteTokens")) for a in aggs)
    total_cents = sum(_facade()._to_float(a.get("totalCents")) for a in aggs)
    by_model: dict[str, dict[str, _facade().Any]] = {}
    for a in aggs:
        m = a.get("modelIntent", "unknown")
        slot = by_model.setdefault(
            m, {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "cents": 0.0}
        )
        slot["input"] += _facade()._to_int(a.get("inputTokens"))
        slot["output"] += _facade()._to_int(a.get("outputTokens"))
        slot["cache_read"] += _facade()._to_int(a.get("cacheReadTokens"))
        slot["cache_write"] += _facade()._to_int(a.get("cacheWriteTokens"))
        slot["cents"] += _facade()._to_float(a.get("totalCents"))
    return {
        "available": True,
        "source": "Cursor (cursor-usage CLI, 最近 30 天)",
        "aggregations": len(aggs),
        "prompt_tokens": total_input,
        "completion_tokens": total_output,
        "cache_read_tokens": total_cache_read,
        "cache_write_tokens": total_cache_write,
        "total_tokens": total_input + total_output + total_cache_read + total_cache_write,
        "cost_cents": total_cents,
        "by_model": dict(
            sorted(
                by_model.items(),
                key=lambda x: -(x[1]["input"] + x[1]["output"] + x[1]["cache_read"]),
            )
        ),
    }
