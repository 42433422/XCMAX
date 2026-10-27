"""AIOPEN composition root and stable application API.

The legacy qclaw panel retains the identical AIOPEN_STATE dictionary. Explicit
forwarders resolve callbacks when called, preserving runtime patches without
components importing this module or depending on a generic facade.
"""

from __future__ import annotations

import os
import secrets
import time
import urllib.request
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

from starlette.types import ASGIApp

from app.infrastructure.aiopen.cursor_hub import aiopen_cursor_hub
from app.infrastructure.mods.manifest import host_xcagi_version

from .api_gateway import InternalApiGateway
from .capability_probe import CapabilityProbe
from .catalog import CatalogGuide
from .definitions import (
    _API_CALL_METHODS as _API_CALL_METHODS,
)
from .definitions import (
    _UI_ACTIONS as _UI_ACTIONS,
)
from .definitions import (
    AIOPEN_PRODUCT_NAME as AIOPEN_PRODUCT_NAME,
)
from .definitions import (
    AIOPEN_PRODUCT_TAGLINE as AIOPEN_PRODUCT_TAGLINE,
)
from .definitions import (
    CAPABILITY_ROUTE_PREFIXES as CAPABILITY_ROUTE_PREFIXES,
)
from .definitions import (
    MCP_DEFAULT_PROTOCOL_VERSION as MCP_DEFAULT_PROTOCOL_VERSION,
)
from .definitions import (
    MCP_PROTOCOL_VERSIONS as MCP_PROTOCOL_VERSIONS,
)
from .definitions import (
    MCP_SERVER_NAME as MCP_SERVER_NAME,
)
from .definitions import (
    TOOL_DEFINITIONS as TOOL_DEFINITIONS,
)
from .dispatch import ToolDispatcher, call_chat
from .installation import (
    InstallationComposer,
)
from .installation import (
    build_cursor_deeplink as build_cursor_deeplink,
)
from .installation import (
    build_mcp_remote_config as build_mcp_remote_config,
)
from .installation import (
    build_mcp_url_config as build_mcp_url_config,
)
from .openclaw import OpenClawProxy
from .protocols import InstallationBuilders, InternalHttpClient, UpstreamResponse
from .result_text import format_tool_result_text as format_tool_result_text
from .route_policy import RoutePolicy
from .route_policy import normalize_api_path as normalize_api_path
from .runtime import ApiKeyRegistry, RuntimeState

AIOPEN_STATE: dict[str, Any] = {
    "wechat_open": True,
    "openclaw_base": "http://localhost:28789",
    "whitelist": dict.fromkeys(CAPABILITY_ROUTE_PREFIXES, True),
    "remote_control_enabled": True,
    "runtime_keys": {},
}
_UI_TOOL_TIMEOUT_SECONDS = 10.0


def _env_api_key() -> str:
    return (os.environ.get("AIOPEN_API_KEY") or "").strip()


def _repo_stdio_bridge_path() -> str:
    return str(Path(__file__).resolve().parents[3] / "scripts" / "dev" / "aiopen_mcp_stdio.py")


def _api_client(app: ASGIApp) -> InternalHttpClient:
    from starlette.testclient import TestClient

    return TestClient(app, follow_redirects=False)


def _upstream_open(
    request: urllib.request.Request, *, timeout: float
) -> AbstractContextManager[UpstreamResponse]:
    response: AbstractContextManager[UpstreamResponse] = urllib.request.urlopen(
        request, timeout=timeout
    )
    return response


_state = RuntimeState(AIOPEN_STATE)
_keys = ApiKeyRegistry(
    _state, lambda: _env_api_key(), lambda count: secrets.token_urlsafe(count), lambda: time.time()
)
_policy = RoutePolicy(
    _state, lambda: CAPABILITY_ROUTE_PREFIXES, lambda path: normalize_api_path(path)
)
_installation = InstallationComposer(
    MCP_SERVER_NAME,
    lambda: _repo_stdio_bridge_path(),
    InstallationBuilders(
        url=lambda base, key: build_mcp_url_config(base, key),
        stdio=lambda base, key: build_mcp_stdio_config(base, key),
        remote=lambda base, key: build_mcp_remote_config(base, key),
        deeplink=lambda name, config: build_cursor_deeplink(name, config),
    ),
)
_catalog = CatalogGuide(
    _state,
    lambda: TOOL_DEFINITIONS,
    lambda base: build_mcp_install_bundle(base),
    lambda: aiopen_cursor_hub,
    lambda: host_xcagi_version(),
)
_gateway = InternalApiGateway(
    lambda app: _api_client(app), lambda path: is_path_whitelisted(path), lambda: _API_CALL_METHODS
)
_probe = CapabilityProbe(
    _state,
    lambda: _tool_api_catalog(),
    lambda routes, path: _pick_probe_path(routes, path),
    lambda app, args: _tool_api_call(app, args),
    lambda app, args: _tool_chat(app, args),
    lambda: aiopen_cursor_hub,
)
_dispatcher = ToolDispatcher(
    _state,
    lambda: _tool_api_catalog(),
    {
        "api_call": lambda app, args: _tool_api_call(app, args),
        "chat": lambda app, args: _tool_chat(app, args),
        "capability_loop": lambda app, args: _tool_capability_loop(app, args),
    },
    lambda: aiopen_cursor_hub,
    lambda: _UI_ACTIONS,
    lambda: _UI_TOOL_TIMEOUT_SECONDS,
)
_openclaw = OpenClawProxy(
    lambda: _state.openclaw_base,
    lambda request, *, timeout: _upstream_open(request, timeout=timeout),
)


def _default_capability_whitelist() -> dict[str, bool]:
    return _policy.defaults()


def verify_api_key(provided: str | None) -> bool:
    return _keys.verify(provided)


def generate_api_key(label: str = "") -> dict[str, Any]:
    return _keys.generate(label)


def revoke_api_key(key: str | None) -> bool:
    return _keys.revoke(key)


def list_api_keys() -> list[dict[str, Any]]:
    return _keys.list_keys()


def build_mcp_stdio_config(base_url: str, api_key: str = "") -> dict[str, Any]:
    return _installation.stdio(base_url, api_key)


def build_mcp_install_bundle(base_url: str, api_key: str = "") -> dict[str, Any]:
    return _installation.bundle(base_url, api_key)


def aiopen_manifest() -> dict[str, Any]:
    return _catalog.manifest()


def build_aiopen_guide(base_url: str) -> dict[str, Any]:
    return _catalog.guide(base_url)


def is_path_whitelisted(path: str, whitelist: dict[str, bool] | None = None) -> bool:
    return _policy.allows(path, whitelist)


def seed_capability_whitelist(*, enable: bool = True, merge: bool = True) -> dict[str, Any]:
    return _policy.seed(enable=enable, merge=merge)


def _tool_api_catalog() -> dict[str, Any]:
    return _policy.catalog()


def _tool_api_call(app: ASGIApp, args: dict[str, Any]) -> dict[str, Any]:
    return _gateway.call(app, args)


def _tool_chat(app: ASGIApp, args: dict[str, Any]) -> dict[str, Any]:
    return call_chat(app, args, _tool_api_call)


def _pick_probe_path(routes: list[dict[str, Any]], preferred: str = "") -> str | None:
    return _policy.pick_probe(routes, preferred, is_path_whitelisted)


def _tool_capability_loop(app: ASGIApp, args: dict[str, Any]) -> dict[str, Any]:
    return _probe.run(app, args)


async def invoke_tool(name: str, args: dict[str, Any] | None, app: ASGIApp) -> dict[str, Any]:
    return await _dispatcher.invoke(name, args, app)


def openclaw_chat_proxy(message: str) -> tuple[dict[str, Any], int]:
    return _openclaw.chat(message)
