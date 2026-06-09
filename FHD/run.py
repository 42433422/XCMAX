"""XCAGI API 启动入口（仓库根；CI / gunicorn 使用）。

端口读取顺序（与 FHD/.env.example 约定一致）：
  1. ``FASTAPI_PORT``（与 FHD/docker compose、second-local-tree 配置同名）
  2. ``XCAGI_API_PORT``（保留兼容老 .env 习惯写法）
  3. 默认 ``5000``——macOS 上 AirPlay / ControlCe 可能占用 :5000（commplex-main），
     此时建议 ``export FASTAPI_PORT=5100``，与 docs/xcagi-dashboard/api-base.js
     的 DEFAULT_FHD_API_ORIGIN 对齐。
"""

from __future__ import annotations

import os

from app.fastapi_app import get_fastapi_app

app = get_fastapi_app()


def _resolve_port() -> int:
    for key in ("FASTAPI_PORT", "XCAGI_API_PORT", "PORT"):
        raw = os.environ.get(key)
        if raw and raw.strip().isdigit():
            port = int(raw.strip())
            if 1 <= port <= 65535:
                return port
    return 5000


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=_resolve_port())
