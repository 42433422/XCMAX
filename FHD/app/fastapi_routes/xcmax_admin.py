"""XCmax 服务器后台控制面路由（facade）。"""

from __future__ import annotations

import logging
import urllib  # noqa: F401 — tests patch app.fastapi_routes.xcmax_admin.urllib.request.*
import urllib.request  # noqa: F401

from fastapi import APIRouter

from app.fastapi_routes import xcmax_admin_proxies as _proxies
from app.fastapi_routes.xcmax_admin_deploy_routes import router as _deploy_router
from app.fastapi_routes.xcmax_admin_digest_routes import router as _digest_router
from app.fastapi_routes.xcmax_admin_local_ops_routes import router as _local_router
from app.fastapi_routes.xcmax_admin_market_routes import (
    admin_list_market_users,
    admin_list_wallets,
    admin_set_user_profile,
)
from app.fastapi_routes.xcmax_admin_market_routes import (
    router as _market_router,
)
from app.fastapi_routes.xcmax_admin_ops_routes import router as _ops_router
from app.fastapi_routes.xcmax_admin_sync_routes import router as _sync_router
from app.fastapi_routes.xcmax_admin_sync_routes import sync_receive
from app.fastapi_routes.xcmax_admin_token_routes import router as _token_router
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/xcmax", tags=["xcmax-admin"])
router.include_router(_market_router)
router.include_router(_digest_router)
router.include_router(_local_router)
router.include_router(_deploy_router)
router.include_router(_ops_router)
router.include_router(_sync_router)
router.include_router(_token_router)

REMOTE_HOST = _proxies.REMOTE_HOST
REMOTE_PORT = _proxies.REMOTE_PORT
_DEFAULT_URLOPEN = _proxies._DEFAULT_URLOPEN
SYNC_POLL_INTERVAL_S = _proxies.SYNC_POLL_INTERVAL_S
CORE_MODULES = _proxies.CORE_MODULES

_require_market_admin_session = _proxies._require_market_admin_session
_release_train_snapshot = _proxies._release_train_snapshot
_market_admin_proxy = _proxies._market_admin_proxy
_digest_local_or_proxy = _proxies._digest_local_or_proxy
_self_maintenance_local_or_proxy = _proxies._self_maintenance_local_or_proxy
_remote_duty_health = _proxies._remote_duty_health
_collect_mod_modules = _proxies._collect_mod_modules
_collect_employee_pack_modules = _proxies._collect_employee_pack_modules
_clean_string_list = _proxies._clean_string_list
_truthy = _proxies._truthy
_inject_digest_api_base = _proxies._inject_digest_api_base
_probe_remote_health_sync = _proxies._probe_remote_health_sync
_sync_sse_generator = _proxies._sync_sse_generator
_xcmax_market_proxy_impl = _proxies._xcmax_market_proxy_impl
_register_market_proxy_method = _proxies._register_market_proxy_method
_build_token_usage_summary = _proxies._build_token_usage_summary

from app.fastapi_routes.xcmax_admin_token_usage import (  # noqa: E402, I001
    _collect_codex_usage as _collect_codex_usage,
    _collect_cursor_usage as _collect_cursor_usage,
    _collect_local_ledger as _collect_local_ledger,
    _collect_mimo_usage as _collect_mimo_usage,
    _collect_trae_usage as _collect_trae_usage,
    _estimate_cost_usd as _estimate_cost_usd,
    _to_float as _to_float,
    _to_int as _to_int,
)

__all__ = [
    "CORE_MODULES",
    "RECOVERABLE_ERRORS",
    "REMOTE_HOST",
    "REMOTE_PORT",
    "SYNC_POLL_INTERVAL_S",
    "_DEFAULT_URLOPEN",
    "_build_token_usage_summary",
    "_clean_string_list",
    "_collect_codex_usage",
    "_collect_cursor_usage",
    "_collect_employee_pack_modules",
    "_collect_local_ledger",
    "_collect_mimo_usage",
    "_collect_mod_modules",
    "_collect_trae_usage",
    "_digest_local_or_proxy",
    "_estimate_cost_usd",
    "_inject_digest_api_base",
    "_market_admin_proxy",
    "_probe_remote_health_sync",
    "_register_market_proxy_method",
    "_release_train_snapshot",
    "_remote_duty_health",
    "_require_market_admin_session",
    "_self_maintenance_local_or_proxy",
    "_sync_sse_generator",
    "_to_float",
    "_to_int",
    "_truthy",
    "_xcmax_market_proxy_impl",
    "admin_list_market_users",
    "admin_list_wallets",
    "admin_set_user_profile",
    "router",
    "sync_receive",
    "urllib",
]

for _market_proxy_method in ("GET", "POST", "PUT", "DELETE", "PATCH"):
    _proxies._register_market_proxy_method(_market_proxy_method, parent_router=router)
