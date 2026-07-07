"""移动端 API 扩展 — 配对相关纯计算辅助函数。"""

from __future__ import annotations

import ipaddress
import os
import socket
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import Request

# Vite 开发服端口：可代理 /api 到 loopback 后端，手机局域网应走此端口而非 127.0.0.1 API。
_FRONTEND_DEV_PORTS = frozenset({5001, 5011})
_REPO_ROOT = Path(__file__).resolve().parents[3]


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


def _read_runtime_api_port(default: int = 0) -> int:
    """读取 run_fastapi 写入的 .runtime/api.port（与 frontend Vite 联动）。"""
    try:
        port_file = _REPO_ROOT / ".runtime" / "api.port"
        if port_file.is_file():
            port = int(port_file.read_text(encoding="utf-8").strip())
            if 0 < port <= 65535:
                return port
    except (OSError, ValueError):
        pass
    return default


def _backend_listen_host() -> str:
    for key in ("XCAGI_API_HOST", "FASTAPI_HOST"):
        raw = os.environ.get(key, "").strip()
        if raw:
            return raw
    return "0.0.0.0"


def _backend_listens_loopback_only() -> bool:
    host = _backend_listen_host().lower()
    return host in {"127.0.0.1", "localhost", "::1"}


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
    runtime_port = _read_runtime_api_port()
    # Older callers omitted the port but hit the model default 5000.  When the
    # current request clearly arrived on another port, prefer that real API port
    # so mobile phones do not bind to stale desktop defaults.
    if requested > 0 and not (requested == 5000 and request_port not in (0, 5000)):
        return requested
    if request_port and request_port not in _FRONTEND_DEV_PORTS:
        return request_port
    if runtime_port > 0:
        return runtime_port
    for key in ("XCAGI_API_PORT", "FASTAPI_PORT"):
        raw = os.environ.get(key, "").strip()
        port = int(raw) if raw.isdigit() else 0
        if 0 < port <= 65535:
            return port
    return 5000


def _pairing_reachable_port(request: Request | None, api_port: int) -> int:
    """后端仅监听 loopback 时，手机局域网需走 Vite 代理端口。"""
    clean_port = int(api_port or 0)
    if clean_port <= 0:
        clean_port = 5000
    if not _backend_listens_loopback_only() or request is None:
        return clean_port
    proxy_port = _request_host_port(request)
    if proxy_port in _FRONTEND_DEV_PORTS:
        return proxy_port
    return clean_port


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


def _enrich_pairing_payload(
    payload: dict[str, Any],
    request: Request | None = None,
) -> dict[str, Any]:
    data = dict(payload)
    host = str(data.get("host") or "").strip()
    api_port = int(data.get("port") or 0)
    port = _pairing_reachable_port(request, api_port)
    base_url = _pairing_api_base_url(host, port)
    code = str(data.get("shortCode") or data.get("code") or "").strip()
    nonce = str(data.get("nonce") or "").strip()
    data["port"] = port
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
