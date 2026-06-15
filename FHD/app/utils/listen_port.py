"""解析 FastAPI 实际监听端口（与 run.py 顺序一致）。"""

from __future__ import annotations

import os


def resolve_listen_port(default: int = 5000) -> int:
    for key in ("FASTAPI_PORT", "XCAGI_API_PORT", "PORT"):
        raw = (os.environ.get(key) or "").strip()
        if raw.isdigit():
            port = int(raw)
            if 1 <= port <= 65535:
                return port
    return default
