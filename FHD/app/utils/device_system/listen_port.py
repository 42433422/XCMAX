"""Shared HTTP bind configuration for desktop, development and discovery."""

from __future__ import annotations

import os
import socket
from collections.abc import Iterable

DESKTOP_API_PORT = 5000
DEVELOPMENT_API_PORT = 42422


def resolve_listen_host() -> str:
    return os.environ.get("FASTAPI_HOST") or os.environ.get("XCAGI_API_HOST") or "127.0.0.1"


def resolve_listen_port(default: int = DESKTOP_API_PORT) -> int:
    for key in ("FASTAPI_PORT", "XCAGI_API_PORT", "PORT"):
        raw = (os.environ.get(key) or "").strip()
        if raw.isdigit():
            port = int(raw)
            if 1 <= port <= 65535:
                return port
    return default


def is_port_available(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
        return True
    except OSError:
        return False


def find_available_port(host: str, preferred: int, candidates: Iterable[int]) -> int:
    """Probe only development launches; desktop callers keep their assigned port."""
    if not 1 <= preferred <= 65535:
        raise ValueError("HTTP port must be between 1 and 65535")
    for port in dict.fromkeys((preferred, *candidates)):
        if 1 <= port <= 65535 and is_port_available(host, port):
            return port
    raise RuntimeError(f"No available HTTP port for {host}:{preferred}")


def publish_listen_address(host: str, port: int) -> None:
    """Keep discovery and application consumers aligned after a development fallback."""
    os.environ["FASTAPI_HOST"] = os.environ["XCAGI_API_HOST"] = host
    os.environ["FASTAPI_PORT"] = os.environ["XCAGI_API_PORT"] = str(port)
