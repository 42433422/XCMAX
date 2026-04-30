"""
集中加载 LAN 安全相关的环境变量。

设计要点：
- 默认 **关闭**（``LAN_GUARD_ENABLED=0``），避免在未配置 ``LAN_LICENSE_SECRET`` 时
  把整套系统锁死；开发与 CI 都可以零侵入。
- ``LAN_LICENSE_SECRET`` 在启用时必填；若未设置且开关为 1，仍会启动，但所有
  签发/校验操作会显式抛 ``RuntimeError``，让管理员立刻发现配置疏漏。
- 路径默认值依赖 ``app.config.Config.BASE_DIR`` 计算，落在 ``<repo>/data/``。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from ipaddress import ip_network
from pathlib import Path
from typing import List, Tuple

LAN_LICENSE_SECRET_MIN_LENGTH = 8


def _env_bool(name: str, default: bool = False) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_csv(name: str, default: str = "") -> List[str]:
    raw = (os.environ.get(name) or default).strip()
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def _resolve_repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "backend" / "routers").is_dir():
            return parent
    return here.parents[2]


@dataclass(frozen=True)
class LanConfig:
    enabled: bool
    allowed_cidrs: Tuple[str, ...]
    trusted_proxies: Tuple[str, ...]
    admin_host_ips: Tuple[str, ...]
    bypass_paths: Tuple[str, ...]
    license_secret: str
    token_ttl_seconds: int
    admin_bootstrap_key: str
    license_db_path: Path
    cookie_name: str
    cookie_secure: bool
    cookie_samesite: str
    cookie_domain: str
    static_prefixes: Tuple[str, ...] = field(default_factory=tuple)

    def is_secret_ready(self) -> bool:
        return bool(self.license_secret) and len(self.license_secret) >= LAN_LICENSE_SECRET_MIN_LENGTH

    def cidr_objects(self):
        out = []
        for raw in self.allowed_cidrs:
            try:
                out.append(ip_network(raw, strict=False))
            except ValueError:
                continue
        return tuple(out)


_DEFAULT_BYPASS = (
    "/api/health",
    "/api/ping",
    "/api/lan/activate",
    "/api/lan/status",
    "/api/lan/host-info",
    "/api/lan/access-requests",
    "/api/lan/access-requests/mine",
    "/api/lan/admin/settings",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/favicon.ico",
)

_DEFAULT_STATIC_PREFIXES = (
    "/assets/",
    "/static/",
    "/_vite/",
    "/font-awesome/",
    "/startup/",
    "/yuangong/",
    "/workflow/",
    "/brand-xc-logo",
    "/workflow-employee-docs.json",
)

_DEFAULT_PRIVATE_CIDRS = (
    "127.0.0.1/32",
    "::1/128",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
)


@lru_cache(maxsize=1)
def get_lan_config() -> LanConfig:
    repo_root = _resolve_repo_root()
    db_path_raw = (os.environ.get("LAN_LICENSE_DB_PATH") or "").strip()
    if db_path_raw:
        db_path = Path(db_path_raw).expanduser().resolve()
    else:
        db_path = (repo_root / "data" / "lan_license.db").resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    enabled = _env_bool("LAN_GUARD_ENABLED", default=False)
    cidrs = _env_csv("LAN_ALLOWED_CIDRS")
    if not cidrs:
        cidrs = list(_DEFAULT_PRIVATE_CIDRS)

    trusted = _env_csv("LAN_TRUSTED_PROXIES")
    admin_hosts = _env_csv("LAN_ADMIN_HOST_IPS") or ["127.0.0.1", "::1"]

    bypass = _env_csv("LAN_BYPASS_PATHS") or list(_DEFAULT_BYPASS)
    extra_bypass = _env_csv("LAN_BYPASS_PATHS_EXTRA")
    if extra_bypass:
        bypass = sorted(set(bypass) | set(extra_bypass))

    static_prefixes = _env_csv("LAN_STATIC_PREFIXES") or list(_DEFAULT_STATIC_PREFIXES)

    secret = (os.environ.get("LAN_LICENSE_SECRET") or "").strip()
    ttl_raw = (os.environ.get("LAN_TOKEN_TTL_HOURS") or "8").strip()
    try:
        ttl_hours = max(1, int(float(ttl_raw)))
    except ValueError:
        ttl_hours = 8

    bootstrap_key = (os.environ.get("LAN_ADMIN_BOOTSTRAP_KEY") or "").strip()

    # 叠加 "在页面内保存" 的运行时覆写（data/lan_settings.json）。
    # 覆写优先级 > env，这样用户在主机管理员控制台改完马上生效，
    # 而 .env 仍然可以作为 CI / 初始部署的基线。
    try:
        from app.security.lan_settings_store import load_overrides

        overrides = load_overrides()
        if overrides.enabled is not None:
            enabled = bool(overrides.enabled)
        if overrides.license_secret is not None:
            secret = overrides.license_secret.strip()
        if overrides.admin_bootstrap_key is not None:
            bootstrap_key = overrides.admin_bootstrap_key.strip()
        if overrides.allowed_cidrs is not None:
            cidrs = [str(x).strip() for x in overrides.allowed_cidrs if str(x).strip()]
    except Exception:
        # 任何读/解析失败都不阻断系统启动，只走 env 路径。
        pass

    cookie_name = (os.environ.get("LAN_COOKIE_NAME") or "fhd_lan_token").strip() or "fhd_lan_token"
    cookie_secure = _env_bool("LAN_COOKIE_SECURE", default=False)
    cookie_samesite = (os.environ.get("LAN_COOKIE_SAMESITE") or "Lax").strip() or "Lax"
    cookie_domain = (os.environ.get("LAN_COOKIE_DOMAIN") or "").strip()

    return LanConfig(
        enabled=enabled,
        allowed_cidrs=tuple(cidrs),
        trusted_proxies=tuple(trusted),
        admin_host_ips=tuple(admin_hosts),
        bypass_paths=tuple(bypass),
        license_secret=secret,
        token_ttl_seconds=ttl_hours * 3600,
        admin_bootstrap_key=bootstrap_key,
        license_db_path=db_path,
        cookie_name=cookie_name,
        cookie_secure=cookie_secure,
        cookie_samesite=cookie_samesite,
        cookie_domain=cookie_domain,
        static_prefixes=tuple(static_prefixes),
    )


def reset_lan_config_cache() -> None:
    """测试或热加载场景下清缓存。"""
    get_lan_config.cache_clear()
