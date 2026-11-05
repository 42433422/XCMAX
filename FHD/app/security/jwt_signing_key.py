"""JWT 签名密钥解析：优先环境变量，未配置时持久化到实例数据目录。

移动端/网页端 access、refresh token 都依赖同一签名密钥。旧实现未配置
``SECRET_KEY`` 时使用进程级随机值，服务重启后历史 token 全部验签失败：
客户端表现为 401（接口）与 403（CSRF 中间件把失效 Bearer 误判为缺失 CSRF），
并且 refresh token 同样无法验签，用户被强制重新登录。

本模块提供稳定解析顺序：

1. ``SECRET_KEY``（生产必须显式配置，优先级最高）
2. ``XCAGI_SECRET_KEY``
3. 数据目录下的 ``.jwt-signing-secret``（首次启动生成，0600 持久化）
4. 进程级随机兜底（仅当数据目录不可写，重启后仍会失效）

数据目录依次取 ``XCAGI_DATA_DIR``、``XCAGI_DESKTOP_DATA_DIR``，否则使用
``FHD/data``（与桌面默认数据库目录一致）。
"""

from __future__ import annotations

import contextlib
import logging
import os
import secrets
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_SECRET_FILE_NAME = ".jwt-signing-secret"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SECRET_BYTES = 48

_lock = threading.Lock()
_cached_path: Path | None = None
_cached_secret: str | None = None
_process_secret: str | None = None
_warned_persisted = False
_warned_fallback = False


def _data_dir() -> Path:
    raw = (
        os.environ.get("XCAGI_DATA_DIR") or os.environ.get("XCAGI_DESKTOP_DATA_DIR") or ""
    ).strip()
    if raw:
        return Path(raw).expanduser()
    return _REPO_ROOT / "data"


def _secret_path() -> Path:
    return _data_dir() / _SECRET_FILE_NAME


def _read_secret(path: Path) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return value


def _create_secret(path: Path) -> str:
    """原子创建密钥文件；并发进程竞争时回读已有值，避免各进程密钥分叉。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        # 并发首启时另一进程刚创建文件但可能尚未写完，短暂等待后回读。
        for _ in range(10):
            existing = _read_secret(path)
            if existing:
                return existing
            time.sleep(0.05)
        return ""
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(secrets.token_urlsafe(_SECRET_BYTES) + "\n")
        with contextlib.suppress(OSError):
            os.chmod(path, 0o600)
    except OSError:
        with contextlib.suppress(OSError):
            path.unlink()
        raise
    return _read_secret(path)


def _process_fallback() -> str:
    global _process_secret, _warned_fallback
    if _process_secret is None:
        _process_secret = secrets.token_urlsafe(_SECRET_BYTES)
    if not _warned_fallback:
        logger.warning(
            "SECRET_KEY 未配置且数据目录不可写，JWT 使用进程级随机密钥（重启后历史 token 失效）"
        )
        _warned_fallback = True
    return _process_secret


def resolve_jwt_signing_key() -> str:
    """返回用于移动端/网页端 JWT 的稳定签名密钥。"""
    env_secret = (
        os.environ.get("SECRET_KEY") or os.environ.get("XCAGI_SECRET_KEY") or ""
    ).strip()
    if env_secret:
        return env_secret

    path = _secret_path()
    global _cached_path, _cached_secret, _warned_persisted
    with _lock:
        if _cached_secret is not None and _cached_path == path:
            return _cached_secret
        persisted = _read_secret(path)
        if not persisted:
            try:
                persisted = _create_secret(path)
            except OSError:
                persisted = ""
        if persisted:
            _cached_path = path
            _cached_secret = persisted
            if not _warned_persisted:
                logger.warning(
                    "SECRET_KEY 未配置，JWT 使用持久化实例密钥 %s（跨重启保持 token 有效）",
                    path,
                )
                _warned_persisted = True
            return persisted
        return _process_fallback()


__all__ = ["resolve_jwt_signing_key"]
