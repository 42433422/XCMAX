"""部署环境判定与生产硬约束（限流 Redis、Mod DAL、密钥等）。"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def is_desktop_mode() -> bool:
    try:
        from app.desktop_runtime import is_desktop_mode as _desktop

        return bool(_desktop())
    except Exception:
        return env_flag("XCAGI_DESKTOP_MODE")


def deployment_env() -> str:
    return os.environ.get("FHD_ENV", "").strip().lower()


def deployment_is_staging() -> bool:
    return deployment_env() == "staging"


def deployment_is_production() -> bool:
    return deployment_env() in {"production", "prod"}


def deployment_is_test() -> bool:
    return env_flag("TESTING") or env_flag("XCAGI_TESTING")


def redis_url_from_env() -> str:
    for key in ("CACHE_REDIS_URL", "REDIS_URL", "XCAGI_REDIS_URL"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return ""


def distributed_rate_limit_required() -> bool:
    """多副本 Web/生产必须走 Redis 限流；桌面与单测豁免。"""
    if is_desktop_mode() or deployment_is_test():
        return False
    if deployment_is_production() or deployment_is_staging():
        return True
    return env_flag("XCAGI_REQUIRE_REDIS_RATE_LIMIT")


def mod_dal_sqlite_fallback_allowed() -> bool:
    """PostgreSQL 主库时是否允许 Mod DAL 暂回退 SQLite（仅 dev/桌面）。"""
    if is_desktop_mode() or deployment_is_test():
        return True
    if env_flag("XCAGI_MOD_DAL_ALLOW_SQLITE_FALLBACK"):
        return True
    return not deployment_is_production() and not deployment_is_staging()


def validate_production_runtime(*, redis_client: object | None = None) -> None:
    """启动时校验：生产/staging 必须可连 Redis（限流与 OIDC state 共享）。"""
    if not distributed_rate_limit_required():
        return
    if redis_client is not None:
        return
    url = redis_url_from_env()
    if not url:
        raise RuntimeError(
            "生产/staging 部署必须配置 CACHE_REDIS_URL（或 REDIS_URL / XCAGI_REDIS_URL）"
            "以启用分布式限流；桌面模式请设置 XCAGI_DESKTOP_MODE=1。"
        )
    try:
        import redis

        client = redis.from_url(url, decode_responses=True)
        client.ping()
    except Exception as exc:
        raise RuntimeError(
            f"生产/staging 无法连接 Redis（{url!r}）：{exc}"
        ) from exc
