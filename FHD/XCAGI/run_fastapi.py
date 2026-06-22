#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FastAPI + Uvicorn 启动入口

由 ``start-lan.ps1``、``python run.py`` 或桌面壳 ``xcagi-backend`` 调用。
环境变量（由启动脚本或 .env 注入）：

- FASTAPI_HOST / XCAGI_API_HOST — 监听地址，默认 0.0.0.0
- FASTAPI_PORT / XCAGI_API_PORT — 监听端口，默认 5000（**XCAGI_API_PORT 优先**，供 systemd/fhd-full.env 覆盖 .env 内 FASTAPI_PORT）
- XCAGI_UVICORN_RELOAD — 是否启用热重载，默认 1（桌面/打包强制 0）
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
from pathlib import Path

_XCAGI_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _XCAGI_DIR.parent

# 运行时端口文件：前端 Vite 读取此文件确定代理目标，实现前后端端口联动
_RUNTIME_PORT_FILE = _REPO_ROOT / ".runtime" / "api.port"
# 自动寻找端口的范围（macOS AirPlay 常占用 5000）
_PORT_PROBE_RANGE = range(5000, 5021)


def _is_port_free(host: str, port: int) -> bool:
    """检测 host:port 是否可绑定（未被占用）。"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
        return True
    except OSError:
        return False


def _find_free_port(host: str, preferred: int) -> int:
    """从 preferred 开始在 _PORT_PROBE_RANGE 内找可用端口；都占用则返回 preferred。"""
    candidates = [preferred] + [p for p in _PORT_PROBE_RANGE if p != preferred]
    for p in candidates:
        if _is_port_free(host, p):
            return p
    return preferred


def _persist_runtime_port(port: int) -> None:
    """将实际监听端口写入 .runtime/api.port，供前端 Vite 读取联动。"""
    try:
        _RUNTIME_PORT_FILE.parent.mkdir(parents=True, exist_ok=True)
        _RUNTIME_PORT_FILE.write_text(str(port), encoding="utf-8")
    except OSError:
        pass


def _load_dotenv_if_present(env_path: Path) -> None:
    if not env_path.is_file():
        return
    try:
        from dotenv import dotenv_values

        for k, v in dotenv_values(str(env_path)).items():
            if v is not None and k not in os.environ:
                os.environ[k] = v
    except ImportError:
        pass


_LOCAL_MARKET_ENV_KEYS = frozenset(
    {
        "XCAGI_MARKET_BASE_URL",
        "MODSTORE_LOCAL_AUTOMATION",
        "MODSTORE_LOCAL_BASE_URL",
        "MODSTORE_DIGEST_BASE_URL",
        "MODSTORE_ALL_HANDS_BASE_URL",
        "MODSTORE_DIGEST_ADMIN_USER",
        "MODSTORE_DIGEST_ADMIN_PASSWORD",
        "XCMAX_MONOREPO_ROOT",
    }
)


def _load_dotenv_override(env_path: Path, keys: frozenset[str] | None = None) -> None:
    if not env_path.is_file():
        return
    try:
        from dotenv import dotenv_values

        for k, v in dotenv_values(str(env_path)).items():
            if v is None:
                continue
            if keys is None or k in keys:
                os.environ[k] = v
    except ImportError:
        pass


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _apply_desktop_local_market_env() -> None:
    """桌面模式默认连接生产认证服务器；本地 MODstore 仅当显式 XCAGI_USE_LOCAL_MARKET=1。

    ``XCAGI_USE_REMOTE_MARKET=1`` 优先于本地市场，避免 shell 同时 export 两者时
    ``.env.local-market`` 把 ``XCAGI_MARKET_BASE_URL`` 覆盖回 ``:8788``。
    """
    os.environ.setdefault("XCAGI_MARKET_BASE_URL", "https://xiu-ci.com")
    if _env_truthy("XCAGI_USE_REMOTE_MARKET"):
        _load_dotenv_override(_XCAGI_DIR / ".env.online-market", frozenset({"XCAGI_MARKET_BASE_URL"}))
        if not os.environ.get("XCAGI_MARKET_BASE_URL"):
            os.environ["XCAGI_MARKET_BASE_URL"] = "https://xiu-ci.com"
        return
    if _env_truthy("XCAGI_USE_LOCAL_MARKET"):
        _load_dotenv_override(_XCAGI_DIR / ".env.local-market", _LOCAL_MARKET_ENV_KEYS)
        if not os.environ.get("XCAGI_MARKET_BASE_URL"):
            os.environ["XCAGI_MARKET_BASE_URL"] = "http://127.0.0.1:8788"


def _ensure_sys_path() -> None:
    for p in (_REPO_ROOT, _XCAGI_DIR):
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False)) or hasattr(sys, "_MEIPASS")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="XCAGI FastAPI server")
    parser.add_argument("--desktop", action="store_true", help="桌面模式（本地 SQLite、禁用 reload）")
    parser.add_argument("--headless", action="store_true", help="无控制台窗口（由 Electron 托管）")
    parser.add_argument("--host", default=None, help="监听地址")
    parser.add_argument("--port", type=int, default=None, help="监听端口")
    parser.add_argument("--data-dir", default=None, help="桌面数据目录")
    parser.add_argument("--migrate-only", action="store_true", help="仅执行数据库迁移后退出")
    parser.add_argument("--backup", action="store_true", help="迁移前备份（与 --migrate-only 合用）")
    return parser.parse_args(argv)


def _apply_desktop_bootstrap(args: argparse.Namespace) -> None:
    if args.desktop:
        os.environ["XCAGI_DESKTOP_MODE"] = "1"
    if args.data_dir:
        os.environ["XCAGI_DATA_DIR"] = str(args.data_dir)
    _ensure_sys_path()
    try:
        from app.desktop_runtime import configure_desktop_environment, is_desktop_mode

        if is_desktop_mode():
            configure_desktop_environment(os.environ.get("XCAGI_DATA_DIR"))
    except Exception as exc:
        print(f"[run_fastapi] desktop bootstrap warning: {exc}", file=sys.stderr)


def _resolve_reload(desktop: bool) -> bool:
    if _is_frozen() or desktop:
        return False
    return os.environ.get("XCAGI_UVICORN_RELOAD", "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    _load_dotenv_if_present(_XCAGI_DIR / ".env")
    _load_dotenv_if_present(_REPO_ROOT / ".env")

    if args.desktop or args.data_dir or args.migrate_only:
        _apply_desktop_bootstrap(args)

    if args.desktop or os.environ.get("XCAGI_DESKTOP_MODE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        _apply_desktop_local_market_env()

    if args.migrate_only:
        _ensure_sys_path()
        from app.desktop_runtime.migrate import backup_database, run_alembic_upgrade
        from app.desktop_runtime.paths import configure_desktop_environment

        configure_desktop_environment(args.data_dir)
        version = os.environ.get("XCAGI_VERSION", "unknown")
        if args.backup:
            backup_database(args.data_dir, version)
        run_alembic_upgrade(args.data_dir)
        return

    if args.host:
        os.environ["FASTAPI_HOST"] = args.host
        os.environ["XCAGI_API_HOST"] = args.host
    if args.port is not None:
        os.environ["FASTAPI_PORT"] = str(args.port)
        os.environ["XCAGI_API_PORT"] = str(args.port)

    _ensure_sys_path()

    host = (
        os.environ.get("FASTAPI_HOST")
        or os.environ.get("XCAGI_API_HOST")
        or "0.0.0.0"
    )
    port = int(
        os.environ.get("XCAGI_API_PORT")
        or os.environ.get("FASTAPI_PORT")
        or "5000"
    )
    # 桌面模式：端口由 Electron 主进程指定，不做避让——避让会导致 Electron 健康检查
    # 轮询原端口而后端实际监听其他端口，引发白屏超时。端口被占时直接报错退出，
    # 由 Electron 捕获退出码并引导用户。
    if not args.desktop:
        # 自动寻找可用端口：macOS AirPlay 等常占用 5000，被占用时在 5000-5020 内自动避让
        probe_host = "127.0.0.1" if host in ("0.0.0.0", "") else host
        free_port = _find_free_port(probe_host, port)
        if free_port != port:
            print(
                f"[run_fastapi] 端口 {port} 被占用，自动切换到 {free_port}",
                file=sys.stderr,
            )
            port = free_port
    # 持久化实际端口，供前端 Vite 读取联动
    _persist_runtime_port(port)
    reload = _resolve_reload(args.desktop or os.environ.get("XCAGI_DESKTOP_MODE", "").strip().lower() in {"1", "true", "yes", "on"})

    import uvicorn

    # 打包后避免 ``"module:attr"`` 字符串导入（PyInstaller 常无法解析，导致桌面端启动失败/假死）
    if _is_frozen():
        from app.fastapi_app import create_fastapi_app

        uvicorn.run(
            create_fastapi_app,
            factory=True,
            host=host,
            port=port,
            reload=False,
            log_level="info",
        )
        return

    uvicorn.run(
        "app.fastapi_app:create_fastapi_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
        reload_dirs=[str(_REPO_ROOT)] if reload else None,
        log_level="info",
    )


if __name__ == "__main__":
    main()
