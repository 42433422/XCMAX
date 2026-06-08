"""HTTP middleware extracted from app.py — request_id, payment proxy, SPA fallback."""

from __future__ import annotations

import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Optional, cast

import httpx
from fastapi import Request, Response
from fastapi.responses import FileResponse, JSONResponse

logger = logging.getLogger(__name__)

_MARKET_DIST = Path(__file__).resolve().parent.parent.parent / "market" / "dist"


def request_id_from_headers(request: Request) -> str:
    raw = request.headers.get("x-request-id") or request.headers.get("x-correlation-id")
    if raw:
        cleaned = raw.strip()
        if cleaned:
            return cast(str, cleaned[:128])
    return uuid.uuid4().hex


async def request_id_middleware(request: Request, call_next):
    rid = request_id_from_headers(request)
    request.state.request_id = rid
    try:
        from modstore_server.eventing.request_trace import set_trace_ids

        set_trace_ids(rid, span_id="")
    except Exception:  # noqa: BLE001
        pass
    response = await call_next(request)
    response.headers["X-Request-Id"] = rid
    return response


def payment_backend_is_java(request: Request) -> bool:
    from modstore_server.application.payment_gateway import PaymentGatewayService

    gateway = PaymentGatewayService()
    return cast(bool, gateway.should_proxy_to_java(request.url.path))


_HOP_BY_HOP_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "host",
        "content-length",
    }
)

_PROXY_RESPONSE_DROP_HEADERS = _HOP_BY_HOP_HEADERS | frozenset({"content-encoding"})

_payment_proxy_client: Optional[httpx.AsyncClient] = None


def _get_payment_proxy_client() -> httpx.AsyncClient:
    global _payment_proxy_client
    if _payment_proxy_client is None:
        limits = httpx.Limits(max_connections=1000, max_keepalive_connections=200)
        _payment_proxy_client = httpx.AsyncClient(limits=limits)
    return _payment_proxy_client


async def payment_backend_proxy_middleware(request: Request, call_next):
    from modstore_server.application.payment_gateway import (
        PaymentGatewayService,
        java_payment_unreachable_message,
    )
    from modstore_server.metrics import observe_payment_proxy

    gateway = PaymentGatewayService()
    if not gateway.should_proxy_to_java(request.url.path):
        return await call_next(request)

    method = request.method
    target_url = f"{gateway.target_base_url()}{request.url.path}"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    fwd_headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP_BY_HOP_HEADERS}
    request_id = getattr(request.state, "request_id", "") or request_id_from_headers(request)
    fwd_headers["X-Request-Id"] = request_id
    body_bytes = await request.body() if method not in ("GET", "HEAD") else b""
    started = time.perf_counter()

    up: httpx.Response | None = None
    try:
        timeout = httpx.Timeout(
            gateway.read_timeout_seconds,
            connect=gateway.connect_timeout_seconds,
        )
        client = _get_payment_proxy_client()
        up = await client.request(
            method,
            target_url,
            content=body_bytes if body_bytes else None,
            headers=fwd_headers,
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        observe_payment_proxy(method, request.url.path, 502, time.perf_counter() - started)
        return JSONResponse(
            {"ok": False, "message": java_payment_unreachable_message(exc)},
            headers={"X-Request-Id": request_id},
            status_code=502,
        )
    except Exception as exc:
        observe_payment_proxy(method, request.url.path, 502, time.perf_counter() - started)
        return JSONResponse(
            {"ok": False, "message": java_payment_unreachable_message(exc)},
            headers={"X-Request-Id": request_id},
            status_code=502,
        )

    if up is None:
        observe_payment_proxy(method, request.url.path, 502, time.perf_counter() - started)
        return JSONResponse(
            {"ok": False, "message": "Java 支付服务请求未完成"},
            headers={"X-Request-Id": request_id},
            status_code=502,
        )

    observe_payment_proxy(method, request.url.path, up.status_code, time.perf_counter() - started)
    out_headers = {
        k: v for k, v in up.headers.items() if k.lower() not in _PROXY_RESPONSE_DROP_HEADERS
    }
    out_headers["X-Request-Id"] = request_id
    return Response(
        content=up.content,
        status_code=up.status_code,
        headers=out_headers,
        media_type=up.headers.get("content-type"),
    )


async def market_history_spa_middleware(request: Request, call_next):
    if request.scope["type"] != "http":
        return await call_next(request)
    if request.method not in ("GET", "HEAD"):
        return await call_next(request)
    path = request.url.path

    for prefix in ("/market", "/new"):
        if path == prefix or path == prefix + "/" or path.startswith(prefix + "/"):
            idx = _MARKET_DIST / "index.html"
            if not _MARKET_DIST.is_dir() or not idx.is_file():
                return await call_next(request)

            dist_root = _MARKET_DIST.resolve()
            rel = path[len(prefix) :].lstrip("/")
            if rel:
                if ".." in rel.split("/"):
                    return JSONResponse({"detail": "非法路径"}, status_code=400)
                candidate = (_MARKET_DIST / rel).resolve()
                try:
                    candidate.relative_to(dist_root)
                except ValueError:
                    return await call_next(request)
                if candidate.is_file():
                    return FileResponse(candidate)
            return FileResponse(idx)

    return await call_next(request)
