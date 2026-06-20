"""XCAGI API 启动入口（仓库根；CI / gunicorn 使用）。

端口读取顺序（与 FHD/.env.example 约定一致）：
  1. ``FASTAPI_PORT``（与 FHD/docker compose、second-local-tree 配置同名）
  2. ``XCAGI_API_PORT``（保留兼容老 .env 习惯写法）
  3. 默认 ``5000``——macOS 上 AirPlay / ControlCe 可能占用 :5000（commplex-main）。

首选端口被占用时，会自动向后寻找下一个可用端口（最多尝试 100 个），
无需手动改环境变量。如需固定端口，仍可通过 ``FASTAPI_PORT`` 显式指定。
"""

from __future__ import annotations

import os
import socket

from app.fastapi_app import get_fastapi_app

app = get_fastapi_app()


def _is_port_available(host: str, port: int) -> bool:
    """检测端口是否可 bind（近似可用性判断，存在竞态但实用）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def _resolve_host() -> str:
    return os.environ.get("FASTAPI_HOST", "0.0.0.0")


def _resolve_port(host: str) -> int:
    """解析监听端口；首选端口被占用时自动寻找下一个可用端口。"""
    preferred = 42422
    for key in ("FASTAPI_PORT", "XCAGI_API_PORT", "PORT"):
        raw = os.environ.get(key)
        if raw and raw.strip().isdigit():
            port = int(raw.strip())
            if 1 <= port <= 65535:
                preferred = port
                break

    if _is_port_available(host, preferred):
        return preferred

    upper = min(preferred + 100, 65535)
    for candidate in range(preferred + 1, upper + 1):
        if _is_port_available(host, candidate):
            print(
                f"[run.py] 端口 {preferred} 被占用，自动切换到可用端口 {candidate}。"
                f"如需固定端口请设置 FASTAPI_PORT 环境变量。",
                flush=True,
            )
            return candidate
    raise RuntimeError(f"在 {preferred}~{upper} 范围内未找到可用端口")


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
