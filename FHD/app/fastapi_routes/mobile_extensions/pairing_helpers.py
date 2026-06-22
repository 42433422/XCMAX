"""移动端 API 扩展 — 配对相关纯计算辅助函数。"""

from __future__ import annotations

import ipaddress
import os
import socket
from typing import Any
from urllib.parse import urlencode

from fastapi import Request


def _guess_lan_ipv4() -> str:
    """本机对外网卡 IPv4，供手机扫码时避免 127.0.0.1。"""
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))
        ip = str(probe.getsockname()[0] or "").strip()
        probe.close()
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    return "127.0.0.1"


def _request_host_port(request: Request) -> int:
    host_header = (request.headers.get("host") or "").strip()
    if ":" in host_header:
        raw_port = host_header.rsplit(":", 1)[-1]
        port = int(raw_port) if raw_port.isdigit() else 0
        if 0 < port <= 65535:
            return port
    return 0


def _pairing_issue_port(request: Request, requested: int) -> int:
    request_port = _request_host_port(request)
    # Older callers omitted the port but hit the model default 5000.  When the
    # current request clearly arrived on another port, prefer that real API port
    # so mobile phones do not bind to stale desktop defaults.
    if requested > 0 and not (requested == 5000 and request_port not in (0, 5000)):
        return requested
    if request_port:
        return request_port
    for key in ("XCAGI_API_PORT", "FASTAPI_PORT"):
        raw = os.environ.get(key, "").strip()
        port = int(raw) if raw.isdigit() else 0
        if 0 < port <= 65535:
            return port
    return 5000


def _pairing_api_base_url(host: str, port: int) -> str:
    clean_host = str(host or "").strip().removeprefix("http://").removeprefix("https://")
    clean_host = clean_host.strip("/").split("/", 1)[0].split("?", 1)[0]
    bare_host = clean_host.rsplit(":", 1)[0] if ":" in clean_host else clean_host
    clean_port = int(port or 0)
    if clean_port <= 0:
        clean_port = 5000
    return f"http://{bare_host}:{clean_port}/"


def _host_is_private_or_loopback(host: str) -> bool:
    clean = str(host or "").strip().removeprefix("http://").removeprefix("https://")
    clean = clean.strip("/").split("/", 1)[0].split("?", 1)[0].rsplit(":", 1)[0]
    try:
        ip = ipaddress.ip_address(clean)
        return ip.is_private or ip.is_loopback
    except ValueError:
        return clean in {"localhost", "0.0.0.0"} or clean.endswith(".local")


def _enrich_pairing_payload(payload: dict[str, Any]) -> dict[str, Any]:
    data = dict(payload)
    host = str(data.get("host") or "").strip()
    port = int(data.get("port") or 0)
    base_url = _pairing_api_base_url(host, port)
    code = str(data.get("shortCode") or data.get("code") or "").strip()
    nonce = str(data.get("nonce") or "").strip()
    data["api_base_url"] = base_url
    data["base_url"] = base_url
    if code:
        data["code"] = code
    data["deep_link"] = "xcagi://pairing?" + urlencode(
        {
            "code": code,
            "nonce": nonce,
            "host": host,
            "port": str(port),
            "api_base_url": base_url,
        }
    )
    data["qr_json"] = {
        "v": 2,
        "kind": "xcagi_pairing",
        "t": code,
        "code": code,
        "shortCode": code,
        "nonce": nonce,
        "host": host,
        "port": port,
        "api_base_url": base_url,
    }
    return data
