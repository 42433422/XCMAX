#!/usr/bin/env python3
"""Split market_account.py and xcmax_admin.py route monoliths (behavior-preserving)."""

from __future__ import annotations

import re
from pathlib import Path

FHD = Path(__file__).resolve().parents[2]
ROUTES = FHD / "app" / "fastapi_routes"


def _read(name: str) -> str:
    return (ROUTES / name).read_text(encoding="utf-8")


def _write(rel: str, content: str) -> None:
    path = ROUTES / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _lines(src: str, start: int, end: int) -> str:
    return "".join(src.splitlines(keepends=True)[start - 1 : end])


def _extract_functions(src: str, names: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for name in names:
        pat = rf"(^async def {re.escape(name)}\b[\s\S]*?)(?=^(?:async )?def |^@router\.|^class |\Z)"
        m = re.search(pat, src, re.MULTILINE)
        if not m:
            pat = rf"(^def {re.escape(name)}\b[\s\S]*?)(?=^(?:async )?def |^@router\.|^class |\Z)"
            m = re.search(pat, src, re.MULTILINE)
        if not m:
            raise KeyError(name)
        out[name] = m.group(1).rstrip() + "\n"
    return out


def _extract_router_handlers(src: str, start_line: int, end_line: int) -> str:
    segment = src.splitlines(keepends=True)[start_line - 1 : end_line]
    handlers: list[str] = []
    i = 0
    while i < len(segment):
        if not segment[i].startswith("@router."):
            i += 1
            continue
        block = [segment[i]]
        i += 1
        block.append(segment[i])
        i += 1
        while i < len(segment):
            nxt = segment[i]
            if nxt.startswith("@router.") or re.match(r"^(?:async )?def ", nxt) or re.match(r"^def ", nxt):
                break
            block.append(nxt)
            i += 1
        handlers.append("".join(block).rstrip())
    return "\n\n".join(handlers) + "\n"


def _extract_router_at_lines(src: str, router_lines: list[int]) -> str:
    all_lines = src.splitlines(keepends=True)
    handlers: list[str] = []
    for start_ln in router_lines:
        i = start_ln - 1
        block = [all_lines[i]]
        i += 1
        block.append(all_lines[i])
        i += 1
        while i < len(all_lines):
            nxt = all_lines[i]
            if nxt.startswith("@router.") or re.match(r"^(?:async )?def ", nxt) or re.match(r"^def ", nxt):
                break
            block.append(nxt)
            i += 1
        handlers.append("".join(block).rstrip())
    return "\n\n".join(handlers) + "\n"


def split_market_account() -> None:
    src = _read("market_account.py")
    session_names = [
        "session_id_from_request",
        "bind_market_auth_to_session",
        "save_session_market_token",
        "clear_session_market_token",
        "session_market_token",
        "session_market_refresh_token",
        "latest_session_market_refresh_token",
        "latest_session_market_token",
        "_user_id_from_session",
    ]
    sess_blocks = _extract_functions(src, session_names)
    session_store = (
        '"""Market session token storage."""\n\nfrom __future__ import annotations\n\n'
        "import logging\nfrom typing import Any\n\nfrom fastapi import Request\n\n"
        "from app.utils.operational_errors import RECOVERABLE_ERRORS\n\n"
        "logger = logging.getLogger(__name__)\n"
        "_MARKET_SESSION_TOKENS: dict[str, str] = {}\n"
        "_MARKET_SESSION_REFRESH_TOKENS: dict[str, str] = {}\n\n"
        + "".join(sess_blocks[n] for n in session_names)
    )

    proxy_names = [
        "_market_base_url", "_auth_header", "_normalize_bearer_token", "_proxy_error_http_status",
        "_authorization_from_request", "_authorization_from_request_resolved", "_body_snippet",
        "_error_message", "_market_http_timeout", "_market_http_retries", "_account_overview_cache_ttl",
        "_overview_cache_key", "_transport_error_message", "_proxy_json", "fetch_market_membership_tier",
    ]
    proxy_blocks = _extract_functions(src, proxy_names)
    proxy_http = (
        '"""HTTP proxy helpers for Xiuci market APIs."""\n\nfrom __future__ import annotations\n\n'
        "import logging\nimport os\nimport re\nfrom hashlib import sha256\nfrom typing import Any\n\n"
        "import httpx\nfrom fastapi import Request\nfrom fastapi.responses import JSONResponse\n\n"
        "from app.fastapi_routes.market_account.session_store import (\n"
        "    latest_session_market_token, session_id_from_request, session_market_token,\n"
        ")\nfrom app.utils.operational_errors import RECOVERABLE_ERRORS\n\n"
        "logger = logging.getLogger(__name__)\n"
        "_ACCOUNT_OVERVIEW_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}\n\n"
        + "".join(proxy_blocks[n] for n in proxy_names)
    )
    proxy_http = proxy_http.replace(
        "        resolved = await resolve_valid_market_access_token(sid)",
        "        from app.fastapi_routes.market_account.auth_service import resolve_valid_market_access_token\n\n"
        "        resolved = await resolve_valid_market_access_token(sid)",
    )

    auth_names = [
        "_token_from_auth_response", "_refresh_token_from_auth_response", "_user_blob_from_market_payload",
        "_truthy_identity_flag", "_market_identity_from_payloads", "_market_user_id_from_auth_payload",
        "refresh_session_market_token", "resolve_valid_market_access_token", "_looks_like_verification_required",
        "_register_without_verification", "send_market_reset_password_code", "reset_market_password_with_code",
        "register_market_user", "_is_local_market_base", "_demo_market_login_payload",
        "_normalize_market_auth_payload", "login_market_with_password", "login_market_with_phone_code",
        "_market_internal_api_key", "ensure_market_enterprise_profile", "_dedupe_mod_ids",
        "enterprise_mod_ids_for_industry", "grant_market_enterprise_entitlements_for_session",
        "_oidc_identity_from_profile", "login_market_for_oidc_profile", "send_market_phone_code",
    ]
    auth_blocks = _extract_functions(src, auth_names)
    auth_service = (
        '"""Market authentication services."""\n\nfrom __future__ import annotations\n\n'
        "import json\nimport logging\nimport os\nimport re\nfrom typing import Any\n\n"
        "from fastapi.responses import JSONResponse\n\n"
        "from app.fastapi_routes.market_account.proxy_http import (\n"
        "    _error_message, _market_base_url, _normalize_bearer_token, _proxy_error_http_status, _proxy_json,\n"
        ")\nfrom app.fastapi_routes.market_account.session_store import (\n"
        "    _user_id_from_session, latest_session_market_token, save_session_market_token,\n"
        "    session_market_refresh_token, session_market_token,\n"
        ")\nfrom app.utils.operational_errors import RECOVERABLE_ERRORS\n\n"
        "logger = logging.getLogger(__name__)\n\n"
        + "".join(auth_blocks[n] for n in auth_names)
    )

    routes_auth = (
        '"""Market auth/session HTTP routes."""\n\nfrom __future__ import annotations\n\n'
        "import logging\nimport uuid\nfrom typing import Any\n\n"
        "from fastapi import APIRouter, Body, Request\nfrom fastapi.responses import JSONResponse\n\n"
        "from app.fastapi_routes.market_account.auth_service import (\n"
        "    _register_without_verification, _token_from_auth_response, login_market_with_password,\n"
        "    login_market_with_phone_code, register_market_user, resolve_valid_market_access_token,\n"
        "    send_market_phone_code,\n"
        ")\nfrom app.fastapi_routes.market_account.proxy_http import (\n"
        "    _error_message, _market_base_url, _normalize_bearer_token, _proxy_json,\n"
        ")\nfrom app.fastapi_routes.market_account.session_store import (\n"
        "    bind_market_auth_to_session, latest_session_market_refresh_token, latest_session_market_token,\n"
        "    session_id_from_request, session_market_refresh_token, session_market_token,\n"
        ")\nfrom app.utils.operational_errors import RECOVERABLE_ERRORS\n\n"
        "logger = logging.getLogger(__name__)\nrouter = APIRouter()\n\n"
        + _extract_router_at_lines(src, [250, 608, 981, 1013, 1456, 1468, 1978, 1999])
    )

    account_helpers = _extract_functions(
        src,
        ["_degraded_account_overview", "_merge_live_overview_fields", "_bootstrap_overview_needs_live_merge",
         "_market_llm_catalog_impl", "_legacy_account_overview"],
    )
    routes_account = (
        '"""Market account overview routes."""\n\nfrom __future__ import annotations\n\n'
        "import logging\nimport time\nfrom typing import Any\n\n"
        "from fastapi import APIRouter, Body, Request\nfrom fastapi.responses import JSONResponse\n\n"
        "from app.fastapi_routes.market_account.proxy_http import (\n"
        "    _ACCOUNT_OVERVIEW_CACHE, _account_overview_cache_ttl, _auth_header,\n"
        "    _authorization_from_request_resolved, _error_message, _market_base_url,\n"
        "    _normalize_bearer_token, _overview_cache_key, _proxy_json,\n"
        ")\nfrom app.fastapi_routes.market_account.session_store import (\n"
        "    save_session_market_token, session_id_from_request,\n"
        ")\nfrom app.utils.operational_errors import RECOVERABLE_ERRORS\n\n"
        "logger = logging.getLogger(__name__)\nrouter = APIRouter()\n\n"
        + "".join(account_helpers[n] for n in account_helpers)
        + _extract_router_at_lines(src, [1498, 1562, 1698, 1705])
    )

    payment_helpers = _extract_functions(
        src,
        ["_market_auth_from_request", "_checkout_sign_body_from_request", "_checkout_body_has_signature",
         "_resolve_market_authorization_for_checkout"],
    )
    routes_payment = (
        '"""Market payment routes."""\n\nfrom __future__ import annotations\n\nfrom typing import Any\n\n'
        "from fastapi import APIRouter, Body, Request\nfrom fastapi.responses import JSONResponse\n\n"
        "from app.fastapi_routes.market_account.proxy_http import (\n"
        "    _authorization_from_request_resolved, _error_message, _market_base_url, _proxy_json,\n"
        ")\nfrom app.fastapi_routes.market_account.session_store import (\n"
        "    session_id_from_request, session_market_token,\n"
        ")\n\nrouter = APIRouter()\n\n"
        + "".join(payment_helpers[n] for n in payment_helpers)
        + _extract_router_at_lines(src, [1776, 1798, 1855, 1907, 1936, 1957])
    )

    init_py = _read("market_account/__init__.py") if False else ""
    init_py = Path(__file__).with_name("_market_account_init_snippet.py")
    init_py = '''"""Bridge XCAGI local UI to the Xiuci market account APIs."""

from __future__ import annotations

import logging

from fastapi import APIRouter

from app.fastapi_routes.market_account import auth_service, proxy_http, routes_account, routes_auth, routes_payment, session_store
from app.fastapi_routes.market_account.routes_account import router as _account_router
from app.fastapi_routes.market_account.routes_auth import router as _auth_router
from app.fastapi_routes.market_account.routes_payment import router as _payment_router

router = APIRouter(prefix="/api/market", tags=["market-account"])
router.include_router(_auth_router)
router.include_router(_account_router)
router.include_router(_payment_router)

logger = logging.getLogger(__name__)

_MARKET_SESSION_TOKENS = session_store._MARKET_SESSION_TOKENS
_MARKET_SESSION_REFRESH_TOKENS = session_store._MARKET_SESSION_REFRESH_TOKENS
session_id_from_request = session_store.session_id_from_request
bind_market_auth_to_session = session_store.bind_market_auth_to_session
save_session_market_token = session_store.save_session_market_token
clear_session_market_token = session_store.clear_session_market_token
session_market_token = session_store.session_market_token
session_market_refresh_token = session_store.session_market_refresh_token
latest_session_market_refresh_token = session_store.latest_session_market_refresh_token
latest_session_market_token = session_store.latest_session_market_token
_user_id_from_session = session_store._user_id_from_session

_ACCOUNT_OVERVIEW_CACHE = proxy_http._ACCOUNT_OVERVIEW_CACHE
_market_base_url = proxy_http._market_base_url
_auth_header = proxy_http._auth_header
_normalize_bearer_token = proxy_http._normalize_bearer_token
_proxy_error_http_status = proxy_http._proxy_error_http_status
_authorization_from_request = proxy_http._authorization_from_request
_authorization_from_request_resolved = proxy_http._authorization_from_request_resolved
_body_snippet = proxy_http._body_snippet
_error_message = proxy_http._error_message
_market_http_timeout = proxy_http._market_http_timeout
_market_http_retries = proxy_http._market_http_retries
_account_overview_cache_ttl = proxy_http._account_overview_cache_ttl
_overview_cache_key = proxy_http._overview_cache_key
_transport_error_message = proxy_http._transport_error_message
_proxy_json = proxy_http._proxy_json
fetch_market_membership_tier = proxy_http.fetch_market_membership_tier

_token_from_auth_response = auth_service._token_from_auth_response
_refresh_token_from_auth_response = auth_service._refresh_token_from_auth_response
_user_blob_from_market_payload = auth_service._user_blob_from_market_payload
_truthy_identity_flag = auth_service._truthy_identity_flag
_market_identity_from_payloads = auth_service._market_identity_from_payloads
_market_user_id_from_auth_payload = auth_service._market_user_id_from_auth_payload
refresh_session_market_token = auth_service.refresh_session_market_token
resolve_valid_market_access_token = auth_service.resolve_valid_market_access_token
_looks_like_verification_required = auth_service._looks_like_verification_required
_register_without_verification = auth_service._register_without_verification
send_market_reset_password_code = auth_service.send_market_reset_password_code
reset_market_password_with_code = auth_service.reset_market_password_with_code
register_market_user = auth_service.register_market_user
_is_local_market_base = auth_service._is_local_market_base
_demo_market_login_payload = auth_service._demo_market_login_payload
_normalize_market_auth_payload = auth_service._normalize_market_auth_payload
login_market_with_password = auth_service.login_market_with_password
login_market_with_phone_code = auth_service.login_market_with_phone_code
_market_internal_api_key = auth_service._market_internal_api_key
ensure_market_enterprise_profile = auth_service.ensure_market_enterprise_profile
_dedupe_mod_ids = auth_service._dedupe_mod_ids
enterprise_mod_ids_for_industry = auth_service.enterprise_mod_ids_for_industry
grant_market_enterprise_entitlements_for_session = auth_service.grant_market_enterprise_entitlements_for_session
_oidc_identity_from_profile = auth_service._oidc_identity_from_profile
login_market_for_oidc_profile = auth_service.login_market_for_oidc_profile
send_market_phone_code = auth_service.send_market_phone_code

_degraded_account_overview = routes_account._degraded_account_overview
_merge_live_overview_fields = routes_account._merge_live_overview_fields
_bootstrap_overview_needs_live_merge = routes_account._bootstrap_overview_needs_live_merge
_market_llm_catalog_impl = routes_account._market_llm_catalog_impl
_legacy_account_overview = routes_account._legacy_account_overview

_market_auth_from_request = routes_payment._market_auth_from_request
_checkout_sign_body_from_request = routes_payment._checkout_sign_body_from_request
_checkout_body_has_signature = routes_payment._checkout_body_has_signature
_resolve_market_authorization_for_checkout = routes_payment._resolve_market_authorization_for_checkout
'''

    _write("market_account/session_store.py", session_store)
    _write("market_account/proxy_http.py", proxy_http)
    _write("market_account/auth_service.py", auth_service)
    _write("market_account/routes_auth.py", routes_auth)
    _write("market_account/routes_account.py", routes_account)
    _write("market_account/routes_payment.py", routes_payment)
    _write("market_account/__init__.py", init_py)
    (ROUTES / "market_account.py").unlink()


def split_xcmax_admin() -> None:
    src = _read("xcmax_admin.py")
    proxy_chunks = [
        _lines(src, 35, 316),
        _lines(src, 322, 581),
        _lines(src, 749, 767),
        _extract_functions(src, ["_inject_digest_api_base"])["_inject_digest_api_base"],
        _extract_functions(src, ["_probe_remote_health_sync"])["_probe_remote_health_sync"],
        _extract_functions(src, ["_sync_sse_generator"])["_sync_sse_generator"],
        _extract_functions(src, ["_xcmax_market_proxy_impl"])["_xcmax_market_proxy_impl"],
        _extract_functions(src, ["_register_market_proxy_method"])["_register_market_proxy_method"],
        _extract_functions(src, ["_build_token_usage_summary"])["_build_token_usage_summary"],
    ]
    proxies = (
        '"""XCmax admin proxy helpers."""\n\nfrom __future__ import annotations\n\n'
        "import asyncio\nimport json\nimport logging\nimport os\nimport time\nimport urllib.request\n"
        "from typing import Any, cast\n\nfrom fastapi import APIRouter, Request\n"
        "from fastapi.responses import JSONResponse\n\nfrom app.utils.operational_errors import RECOVERABLE_ERRORS\n\n"
        "logger = logging.getLogger(__name__)\nrouter = APIRouter()\n\n"
        "REMOTE_HOST = os.environ.get(\"XCMAX_REMOTE_HOST\", \"119.27.178.147\")\n"
        "REMOTE_PORT = int(os.environ.get(\"XCMAX_REMOTE_PORT\", \"9999\"))\n"
        "_DEFAULT_URLOPEN = urllib.request.urlopen\n"
        "SYNC_POLL_INTERVAL_S = float(os.environ.get(\"XCMAX_SYNC_POLL_S\", \"10\"))\n\n"
        + "".join(proxy_chunks)
    )
    proxies = proxies.replace(
        "def _register_market_proxy_method(method: str) -> None:",
        "def _register_market_proxy_method(method: str, *, parent_router=None) -> None:",
    ).replace(
        '    router.add_api_route(\n        "/market-proxy/{subpath:path}",',
        '    target = parent_router if parent_router is not None else router\n'
        '    target.add_api_route(\n        "/market-proxy/{subpath:path}",',
    )
    proxies = proxies.replace(
        "def _build_token_usage_summary()",
        "from app.fastapi_routes.xcmax_admin_token_usage import (\n"
        "    _collect_codex_usage, _collect_cursor_usage, _collect_local_ledger,\n"
        "    _collect_mimo_usage, _collect_trae_usage, _estimate_cost_usd, _to_int,\n"
        ")\n\ndef _build_token_usage_summary()",
    )
    proxies = re.sub(
        r"\nfor _market_proxy_method in \(.*?\):\n    _register_market_proxy_method\(_market_proxy_method\)\n",
        "\n",
        proxies,
        flags=re.DOTALL,
    )
    proxies = re.sub(
        r"# -{10,}\n# Token 用量聚合.*?\nfrom app\.fastapi_routes\.xcmax_admin_token_usage import.*?\)\n",
        "",
        proxies,
        flags=re.DOTALL,
    )

    routes_market = (
        '"""XCmax admin market routes."""\n\nfrom __future__ import annotations\n\n'
        "import logging\nimport time\nfrom typing import Any\n\n"
        "from fastapi import APIRouter, Body, Query, Request\nfrom fastapi.responses import JSONResponse\n\n"
        "from app.fastapi_routes.xcmax_admin_proxies import (\n"
        "    REMOTE_HOST, REMOTE_PORT, _clean_string_list, _market_admin_proxy,\n"
        "    _require_market_admin_session, _truthy,\n"
        ")\nfrom app.utils.operational_errors import RECOVERABLE_ERRORS\n\n"
        "logger = logging.getLogger(__name__)\nrouter = APIRouter()\n\n"
        + _lines(src, 746, 746)
        + _extract_router_handlers(src, 583, 1228)
    )
    routes_digest = (
        '"""XCmax admin digest routes."""\n\nfrom __future__ import annotations\n\n'
        "import logging\nfrom typing import Any\n\n"
        "from fastapi import APIRouter, Body, Query, Request\nfrom fastapi.responses import JSONResponse\n\n"
        "from app.fastapi_routes.xcmax_admin_proxies import (\n"
        "    _digest_local_or_proxy, _inject_digest_api_base, _market_admin_proxy, _require_market_admin_session,\n"
        ")\n\nlogger = logging.getLogger(__name__)\nrouter = APIRouter()\n\n"
        + _extract_router_handlers(src, 1237, 1268)
        + _extract_router_handlers(src, 1564, 1699)
    )
    routes_local = (
        '"""XCmax admin local ops routes."""\n\nfrom __future__ import annotations\n\n'
        "import logging\nfrom typing import Any\n\n"
        "from fastapi import APIRouter, Body, Query, Request\nfrom fastapi.responses import JSONResponse\n\n"
        "from app.fastapi_routes.xcmax_admin_proxies import (\n"
        "    _market_admin_proxy, _require_market_admin_session, _self_maintenance_local_or_proxy,\n"
        ")\nfrom app.utils.operational_errors import RECOVERABLE_ERRORS\n\n"
        "logger = logging.getLogger(__name__)\nrouter = APIRouter()\n\n"
        + _extract_router_handlers(src, 1275, 1554)
    )
    routes_deploy = (
        '"""XCmax admin deploy/modules routes."""\n\nfrom __future__ import annotations\n\n'
        "import asyncio\nimport logging\nfrom typing import Any\n\n"
        "from fastapi import APIRouter, Body, Query, Request\nfrom fastapi.responses import JSONResponse\n\n"
        "from app.fastapi_routes.xcmax_admin_proxies import (\n"
        "    CORE_MODULES, _collect_employee_pack_modules, _collect_mod_modules,\n"
        "    _probe_remote_health_sync, _release_train_snapshot, _require_market_admin_session,\n"
        ")\nfrom app.utils.operational_errors import RECOVERABLE_ERRORS\n\n"
        "logger = logging.getLogger(__name__)\nrouter = APIRouter()\n\n"
        + _extract_router_handlers(src, 1269, 1274)
        + _extract_router_handlers(src, 1555, 1563)
        + _extract_router_handlers(src, 1741, 1802)
    )
    routes_ops = (
        '"""XCmax admin remote ops routes."""\n\nfrom __future__ import annotations\n\n'
        "import logging\nfrom typing import Any\n\n"
        "from fastapi import APIRouter, Body, Query, Request\nfrom fastapi.responses import JSONResponse\n\n"
        "from app.fastapi_routes.xcmax_admin_proxies import (\n"
        "    _market_admin_proxy, _remote_duty_health, _require_market_admin_session,\n"
        ")\nfrom app.utils.operational_errors import RECOVERABLE_ERRORS\n\n"
        "logger = logging.getLogger(__name__)\nrouter = APIRouter()\n\n"
        + _extract_router_handlers(src, 1809, 1997)
    )
    routes_sync = (
        '"""XCmax admin sync routes."""\n\nfrom __future__ import annotations\n\n'
        "import logging\nfrom typing import Any\n\n"
        "from fastapi import APIRouter, Body, Query, Request\n"
        "from fastapi.responses import JSONResponse, StreamingResponse\n\n"
        "from app.fastapi_routes.xcmax_admin_proxies import REMOTE_HOST, REMOTE_PORT, _sync_sse_generator\n"
        "from app.utils.operational_errors import RECOVERABLE_ERRORS\n\n"
        "logger = logging.getLogger(__name__)\nrouter = APIRouter()\n\n"
        + _extract_router_handlers(src, 1998, 2282)
    )
    routes_token = (
        '"""XCmax admin token usage route."""\n\nfrom __future__ import annotations\n\n'
        "import asyncio\n\nfrom fastapi import APIRouter, Request\nfrom fastapi.responses import JSONResponse\n\n"
        "from app.fastapi_routes.xcmax_admin_proxies import _build_token_usage_summary\n\n"
        "router = APIRouter()\n\n"
        + _extract_router_handlers(src, 2365, 2375)
    )
    facade = '''"""XCmax 服务器后台控制面路由（facade）。"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from app.fastapi_routes import xcmax_admin_proxies as _proxies
from app.fastapi_routes.xcmax_admin_deploy_routes import router as _deploy_router
from app.fastapi_routes.xcmax_admin_digest_routes import router as _digest_router
from app.fastapi_routes.xcmax_admin_local_ops_routes import router as _local_router
from app.fastapi_routes.xcmax_admin_market_routes import router as _market_router
from app.fastapi_routes.xcmax_admin_ops_routes import router as _ops_router
from app.fastapi_routes.xcmax_admin_sync_routes import router as _sync_router
from app.fastapi_routes.xcmax_admin_token_routes import router as _token_router

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

for _market_proxy_method in ("GET", "POST", "PUT", "DELETE", "PATCH"):
    _proxies._register_market_proxy_method(_market_proxy_method, parent_router=router)
'''
    _write("xcmax_admin_proxies.py", proxies)
    _write("xcmax_admin_market_routes.py", routes_market)
    _write("xcmax_admin_digest_routes.py", routes_digest)
    _write("xcmax_admin_local_ops_routes.py", routes_local)
    _write("xcmax_admin_deploy_routes.py", routes_deploy)
    _write("xcmax_admin_ops_routes.py", routes_ops)
    _write("xcmax_admin_sync_routes.py", routes_sync)
    _write("xcmax_admin_token_routes.py", routes_token)
    _write("xcmax_admin.py", facade)


if __name__ == "__main__":
    split_market_account()
    split_xcmax_admin()
    print("done")
