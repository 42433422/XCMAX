"""Regression tests for AIOPEN's policy, transport, and dispatch boundaries."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from email.message import Message
from io import BytesIO
from threading import Event
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

import pytest
from fastapi import FastAPI, Request
from starlette.responses import RedirectResponse
from starlette.types import ASGIApp

from app.application.aiopen import service
from app.application.aiopen.capability_probe import CapabilityProbe
from app.application.aiopen.runtime import ApiKeyRegistry, RuntimeState


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(service.AIOPEN_STATE, "whitelist", {"/api/products": True})
    monkeypatch.setitem(service.AIOPEN_STATE, "runtime_keys", {})
    monkeypatch.delenv("AIOPEN_API_KEY", raising=False)


@pytest.mark.parametrize(
    "path",
    [
        "/api/products/../private",
        "/api/products/%2e%2e/private",
        "/api/products/..%2fprivate",
        "/api/products/%252e%252e/private",
    ],
)
def test_gateway_denies_paths_that_escape_the_allowed_prefix(path: str) -> None:
    app = FastAPI()
    private_calls: list[str] = []

    @app.get("/api/private")
    async def private_route() -> dict[str, bool]:
        private_calls.append("private")
        return {"private": True}

    result = service._tool_api_call(app, {"path": path})

    assert private_calls == []
    assert result.get("code") == "ROUTE_NOT_WHITELISTED"
    assert result["success"] is False


def test_gateway_does_not_follow_redirect_outside_whitelist() -> None:
    app = FastAPI()
    private_calls: list[str] = []

    @app.get("/api/products/redirect")
    async def redirect() -> RedirectResponse:
        return RedirectResponse("/api/private")

    @app.get("/api/private")
    async def private_route() -> dict[str, bool]:
        private_calls.append("private")
        return {"private": True}

    result = service._tool_api_call(app, {"path": "/api/products/redirect"})

    assert private_calls == []
    assert result["status_code"] == 307


@pytest.mark.parametrize("request_fails", [False, True])
def test_gateway_closes_client_after_success_and_request_failure(request_fails: bool) -> None:
    client = MagicMock()
    client.get.return_value.status_code = 200
    client.get.return_value.json.return_value = {"items": []}
    if request_fails:
        client.get.side_effect = RuntimeError("local transport failed")

    with patch("starlette.testclient.TestClient", return_value=client):
        result = service._tool_api_call(FastAPI(), {"path": "/api/products"})

    assert result["success"] is not request_fails
    client.close.assert_called_once_with()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["api_call", "chat", "capability_loop"])
async def test_blocking_tools_release_event_loop_and_preserve_context(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    context: ContextVar[str] = ContextVar("aiopen_test_context", default="missing")
    context.set("request-context")
    entered, released = Event(), Event()

    def blocking_tool(app: Any, args: dict[str, Any]) -> dict[str, Any]:
        entered.set()
        return {"released": released.wait(1), "context": context.get(), "args": args}

    async def concurrent_request() -> None:
        while not entered.is_set():
            await asyncio.sleep(0)
        released.set()

    monkeypatch.setattr(service, f"_tool_{name}", blocking_tool)
    observer = asyncio.create_task(concurrent_request())
    try:
        result = await service.invoke_tool(name, {"message": "local"}, FastAPI())
        await observer
    finally:
        released.set()
        observer.cancel()

    assert result["released"] is True, "another request could not run during the API call"
    assert result["context"] == "request-context"
    assert result["args"] == {"message": "local"}


@pytest.mark.parametrize("count", [0, 1, 11])
def test_guide_tool_count_tracks_manifest(count: int, monkeypatch: pytest.MonkeyPatch) -> None:
    definitions = [
        {"name": f"tool_{i}", "description": "local tool", "inputSchema": {"type": "object"}}
        for i in range(count)
    ]
    monkeypatch.setattr(service, "TOOL_DEFINITIONS", definitions)

    guide = service.build_aiopen_guide("http://testserver")

    assert len(service.aiopen_manifest()["tools"]) == count
    assert f"应返回 {count} 个工具" in guide["markdown"]


def test_non_ascii_api_key_is_rejected_without_crashing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIOPEN_API_KEY", "configured-key")
    assert service.verify_api_key("错误口令") is False


def test_upstream_http_error_response_is_closed() -> None:
    response = BytesIO(b"upstream unavailable")
    error = HTTPError("http://local.invalid/api/chat", 503, "unavailable", Message(), response)
    with patch("app.application.aiopen.service.urllib.request.urlopen", side_effect=error):
        result, status = service.openclaw_chat_proxy("local message")

    assert status == 502
    assert result["status_code"] == 503
    assert response.closed is True


@pytest.mark.parametrize(
    ("raw_path", "route_path", "value"),
    [
        ("/api/products/a/../list?value=one%20two", "/api/products/list", "one two"),
        ("/api/%70roducts/na%6De/", "/api/products/name/", ""),
        ("/api/products/分类%2F商品?value=a%2Fb", "/api/products/分类/商品", "a/b"),
        ("/api/products/a%3Fb%23c?value=ok", "/api/products/a?b#c", "ok"),
    ],
)
def test_gateway_sends_the_checked_path_without_restarting_host_lifespan(
    raw_path: str, route_path: str, value: str
) -> None:
    lifecycle: list[str] = []

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        lifecycle.append("start")
        yield
        lifecycle.append("stop")

    app = FastAPI(lifespan=lifespan)

    async def endpoint(request: Request) -> dict[str, str]:
        return {"path": request.scope["path"], "value": request.query_params.get("value", "")}

    app.add_api_route(route_path, endpoint)

    result = service._tool_api_call(app, {"path": raw_path})

    assert result["status_code"] == 200
    assert result["data"] == {"path": route_path, "value": value}
    assert result["path"] == raw_path
    assert lifecycle == []


@pytest.mark.parametrize(
    "path",
    [
        "https://external.invalid/api/products",
        "//external.invalid/api/products",
        "/api/products\\..\\private",
        "/api/products/%00/unused",
        "/api/products/%FF",
    ],
)
def test_gateway_rejects_ambiguous_targets_before_creating_client(path: str) -> None:
    with patch("starlette.testclient.TestClient") as factory:
        result = service._tool_api_call(FastAPI(), {"path": path})

    assert result["code"] == "ROUTE_NOT_WHITELISTED"
    factory.assert_not_called()


def test_key_registry_owns_only_injected_state_and_key_sources() -> None:
    values: dict[str, Any] = {}
    configured_key = [""]
    registry = ApiKeyRegistry(
        RuntimeState(values), lambda: configured_key[0], lambda size: "local-token", lambda: 42.0
    )
    assert registry.verify(None) is False

    generated = registry.generate("  local client  ")
    assert generated == {"key": "aiopen_local-token", "label": "local client", "created_at": 42.0}
    assert values["runtime_keys"] == {
        "aiopen_local-token": {"label": "local client", "created_at": 42.0}
    }
    assert registry.verify(None) is False
    assert registry.verify(generated["key"]) is True
    assert registry.revoke(generated["key"]) is True

    configured_key[0] = "配置口令"
    assert registry.verify("配置口令") is True
    assert registry.verify("错误口令") is False
    assert service.AIOPEN_STATE["runtime_keys"] == {}


def test_installation_resolves_replaced_builders_after_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url_config = {"url": "http://testserver/replaced"}
    monkeypatch.setattr(service, "build_mcp_url_config", lambda base, key: url_config)
    monkeypatch.setattr(service, "_repo_stdio_bridge_path", lambda: "/tmp/local-bridge.py")

    bundle = service.build_mcp_install_bundle("http://testserver", "local-key")

    assert bundle["methods"]["url"]["config"] is url_config
    assert bundle["mcp_config_template"]["mcpServers"][service.MCP_SERVER_NAME] is url_config
    assert bundle["methods"]["stdio"]["config"]["args"] == ["/tmp/local-bridge.py"]


def test_chat_and_probe_resolve_replaced_callbacks_after_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def api_call(app: ASGIApp, args: dict[str, Any]) -> dict[str, Any]:
        calls.append(args)
        return {"success": True, "status_code": 200}

    monkeypatch.setattr(service, "_tool_api_call", api_call)
    service._tool_chat(FastAPI(), {"message": "  local message  "})
    assert calls == [
        {
            "path": "/api/ai/unified_chat",
            "method": "POST",
            "body": {"message": "local message", "source": "aiopen"},
        }
    ]

    monkeypatch.setattr(service, "_tool_api_catalog", lambda: {"success": True, "routes": []})
    monkeypatch.setattr(service, "_pick_probe_path", lambda routes, preferred: "/api/probe")
    chat = MagicMock(return_value={"success": True, "status_code": 200})
    monkeypatch.setattr(service, "_tool_chat", chat)
    result = service._tool_capability_loop(FastAPI(), {"message": "probe message"})

    assert calls[-1] == {"path": "/api/probe", "method": "GET"}
    assert chat.call_args.args[1] == {"message": "probe message"}
    assert result["closed_loop"] is True
    assert result["steps"][0]["total_count"] == 0


class LocalCursor:
    def session_ids(self) -> list[str]:
        return ["local"]

    def sessions_info(self) -> list[dict[str, Any]]:
        return [{"session_id": "local"}]

    async def dispatch(
        self,
        action: str,
        params: dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        return {"success": True}


def test_capability_probe_uses_only_its_ports_and_distinguishes_499_from_loop_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service, "_tool_api_call", MagicMock(side_effect=AssertionError))
    probe = CapabilityProbe(
        RuntimeState({"remote_control_enabled": True}),
        lambda: {
            "success": True,
            "routes": [
                {"path": "/api/local", "enabled": True},
                {"path": "/api/disabled", "enabled": False},
                "invalid catalog entry",
            ],
        },
        lambda routes, preferred: "/api/local",
        lambda app, args: {"success": True, "status_code": 499},
        lambda app, args: {"success": True, "status_code": 200},
        LocalCursor,
    )

    result = probe.run(FastAPI(), {})

    assert result["closed_loop"] is False
    assert result["ui_loop_ready"] is True
    assert result["steps"][0] == {
        "step": "api_catalog",
        "ok": True,
        "enabled_count": 1,
        "total_count": 2,
    }
    assert result["steps"][1]["ok"] is False
    assert result["steps"][1]["status_code"] == 499
