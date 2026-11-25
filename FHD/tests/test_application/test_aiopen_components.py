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
from app.application.aiopen.openclaw import OpenClawProxy
from app.application.aiopen.runtime import ApiKeyRegistry, RuntimeState


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(service.AIOPEN_STATE, "whitelist", {"/api/products": True})
    monkeypatch.setitem(service.AIOPEN_STATE, "runtime_keys", {})
    monkeypatch.delenv("AIOPEN_API_KEY", raising=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["chat", "capability_loop"])
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
    opener = MagicMock(side_effect=error)
    result = OpenClawProxy(lambda: "http://local.invalid", opener).chat(
        "local message", request_id="original-request", gateway_url="http://local.invalid"
    )

    assert result["success"] is False
    assert result["upstream_status_code"] == 503
    assert result["execution_state"] == "unknown"
    assert result["retryable"] is False
    assert response.closed is True


@pytest.mark.parametrize("raw", [b'{"reply":"accepted"}', b"", b"not-json"])
def test_openclaw_http_response_is_not_business_completion(raw):
    response = BytesIO(raw)
    opener = MagicMock(return_value=response)
    result = OpenClawProxy(lambda: "http://local.invalid", opener).chat(
        "approved message", request_id="original-request", gateway_url="http://local.invalid"
    )
    assert result["transport_accepted"] is True
    assert result["success"] is False
    assert result["execution_state"] == "unknown"
    assert result["reconciliation_required"] is True
    assert result["retryable"] is False
    assert response.closed
    request = opener.call_args.args[0]
    assert request.full_url == "http://local.invalid/api/chat"
    assert request.get_header("Idempotency-key") == "original-request"
    assert request.data == b'{"message": "approved message"}'
    opener.assert_called_once()


@pytest.mark.parametrize(
    ("message", "request_id", "gateway_url"),
    [
        ("", "key", "http://local.invalid"),
        ("hi", "", "http://local.invalid"),
        ("hi", "key", "http://other.invalid"),
    ],
)
def test_openclaw_changed_target_or_missing_identity_never_sends(message, request_id, gateway_url):
    opener = MagicMock()
    result = OpenClawProxy(lambda: "http://local.invalid", opener).chat(
        message, request_id=request_id, gateway_url=gateway_url
    )
    assert result["success"] is False
    assert result["execution_state"] == "not_started"
    opener.assert_not_called()


def test_openclaw_network_exception_is_unknown_without_retry():
    opener = MagicMock(side_effect=ConnectionError("private upstream error"))
    result = OpenClawProxy(lambda: "http://local.invalid", opener).chat(
        "hi", request_id="original-request", gateway_url="http://local.invalid"
    )
    assert result["execution_state"] == "unknown"
    assert result["retryable"] is False
    assert "private upstream" not in str(result)
    opener.assert_called_once()


def test_key_registry_owns_only_injected_state_and_key_sources() -> None:
    values: dict[str, Any] = {}
    configured_key = [""]
    registry = ApiKeyRegistry(
        RuntimeState(values), lambda: configured_key[0], lambda size: "local-token", lambda: 42.0
    )
    assert registry.verify(None) is False

    generated = registry.generate("  local client  ")
    # 计量字段（usage/total_calls/error_calls）是配额与调用统计的预期契约，
    # 这里只断言归属与注入来源，不锁定完整字段集。
    assert generated["key"] == "aiopen_local-token"
    assert generated["label"] == "local client"
    assert generated["created_at"] == 42.0
    assert values["runtime_keys"]["aiopen_local-token"]["label"] == "local client"
    assert values["runtime_keys"]["aiopen_local-token"]["created_at"] == 42.0
    assert set(values["runtime_keys"]) == {"aiopen_local-token"}
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
