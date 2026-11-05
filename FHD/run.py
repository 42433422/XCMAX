"""XCAGI API 启动入口（仓库根；CI / gunicorn 使用）。

端口读取顺序（与 FHD/.env.example 约定一致）：
  1. ``FASTAPI_PORT``（与 FHD/docker compose、second-local-tree 配置同名）
  2. ``XCAGI_API_PORT``（保留兼容老 .env 习惯写法）
  3. ``PORT``，然后开发入口默认 ``42422``。桌面入口默认 ``5000``。

首选端口被占用时，会自动向后寻找下一个可用端口（最多尝试 100 个），
无需手动改环境变量。可通过 ``FASTAPI_PORT`` 指定首选端口；桌面入口保留指定端口。
"""

from __future__ import annotations

import os

from app.fastapi_app import get_fastapi_app
from app.utils.device_system.listen_port import (
    DEVELOPMENT_API_PORT,
    find_available_port,
    publish_listen_address,
    resolve_listen_host,
    resolve_listen_port,
)

app = get_fastapi_app()


def _resolve_host() -> str:
    return resolve_listen_host()


def _resolve_port(host: str) -> int:
    """解析监听端口；首选端口被占用时自动寻找下一个可用端口。"""
    preferred = resolve_listen_port(DEVELOPMENT_API_PORT)
    selected = find_available_port(host, preferred, range(preferred + 1, preferred + 101))
    if selected != preferred:
        print(f"[run.py] 端口 {preferred} 被占用，切换到 {selected}。", flush=True)
    publish_listen_address(host, selected)
    return selected


def _write_runtime_port(port: int) -> None:
    """把实际监听端口写入 .runtime/api.port，供前端 vite 代理读取联动。"""
    runtime_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".runtime")
    try:
        os.makedirs(runtime_dir, exist_ok=True)
        with open(os.path.join(runtime_dir, "api.port"), "w", encoding="utf-8") as f:
            f.write(str(port))
    except OSError:
        pass


if __name__ == "__main__":
    import uvicorn

    host = _resolve_host()
    port = _resolve_port(host)
    _write_runtime_port(port)
    uvicorn.run(app, host=host, port=port)
