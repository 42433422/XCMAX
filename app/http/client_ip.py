"""从 Starlette Request 解析客户端 IP（支持 X-Forwarded-For）。"""

from __future__ import annotations

from starlette.requests import Request


def client_host_from_request(request: Request | None) -> str:
    if request is None:
        return ""
    forwarded = (request.headers.get("x-forwarded-for") or "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()[:128]
    if request.client and request.client.host:
        return str(request.client.host)[:128]
    return "unknown"
