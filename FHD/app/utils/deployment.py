"""部署环境探测工具（v10 线内迭代 · §6 测试燃尽）。

集中环境判定逻辑，供限流/缓存/启动等按部署形态（桌面/测试/staging/生产）做分支。
纯读环境变量 + 对 ``app.desktop_runtime`` 的软依赖（缺失时回退到环境变量），无副作用。

契约见 ``tests/test_utils/test_deployment_env_probe.py``。
"""

from __future__ import annotations

import os

_TRUTHY = {"1", "true", "yes", "on"}


def env_flag(name: str, default: bool = False) -> bool:
    """读取布尔型环境变量。

    - 变量**未设置** → 返回 ``default``。
    - 变量**已设置**：去空白后小写，命中 ``{1,true,yes,on}`` 为 ``True``，其余（含空串）为 ``False``。
      注意：已设置但为空白串视为显式 falsy，**不**回退 ``default``。
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUTHY


def deployment_env() -> str:
    """部署环境标识（``FHD_ENV``，去空白小写）；未设置返回空串。"""
    return (os.environ.get("FHD_ENV") or "").strip().lower()


def deployment_is_staging() -> bool:
    return deployment_env() == "staging"


def deployment_is_production() -> bool:
    return deployment_env() in {"production", "prod"}


def deployment_is_test() -> bool:
    """是否测试环境（``TESTING`` 或 ``XCAGI_TESTING`` 任一为真）。"""
    return env_flag("TESTING") or env_flag("XCAGI_TESTING")


def redis_url_from_env() -> str:
    """按优先级回退取 Redis URL：``CACHE_REDIS_URL`` → ``REDIS_URL`` → ``XCAGI_REDIS_URL``。

    均未设置（或为空）时返回空串。
    """
    for key in ("CACHE_REDIS_URL", "REDIS_URL", "XCAGI_REDIS_URL"):
        value = (os.environ.get(key) or "").strip()
        if value:
            return value
    return ""


def is_desktop_mode() -> bool:
    """是否桌面运行时。

    优先复用 ``app.desktop_runtime.paths.is_desktop_mode``；该模块不可用（如精简打包/导入失败）
    时回退到 ``XCAGI_DESKTOP_MODE`` 环境变量。
    """
    try:
        from app.desktop_runtime.paths import is_desktop_mode as _desktop_mode

        return bool(_desktop_mode())
    except ImportError:
        return env_flag("XCAGI_DESKTOP_MODE")


def distributed_rate_limit_required() -> bool:
    """是否需要分布式（Redis）限流。

    桌面/测试环境不需要；显式开关 ``XCAGI_REQUIRE_REDIS_RATE_LIMIT`` 或 staging/生产需要；
    其余默认不需要。
    """
    if is_desktop_mode():
        return False
    if deployment_is_test():
        return False
    if env_flag("XCAGI_REQUIRE_REDIS_RATE_LIMIT"):
        return True
    return deployment_is_production() or deployment_is_staging()
