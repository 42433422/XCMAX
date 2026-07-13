"""Request-scoped MODstore credentials for the unified chat mainline."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.requests import Request

from app.application import planner_compat_service as planner
from app.fastapi_routes.xcagi_compat_chat_helpers import (
    XcagiCompatChatBatchBody,
    XcagiCompatChatBody,
)


def _request(token: str = "") -> Request:
    headers = []
    if token:
        headers.append((b"x-test-market-token", token.encode("utf-8")))
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/ai/chat",
            "headers": headers,
        }
    )


class _FakeAdapter:
    def __init__(self, token: str, *, close_after_call: bool):
        self.auth_token = token
        self.close_after_call = close_after_call


class _FakeAIChatApplicationService:
    shared_ai_service = SimpleNamespace(modstore_adapter="shared-provider")
    barrier: threading.Barrier | None = None

    def __init__(self) -> None:
        self.ai_service = self.shared_ai_service

    def process_chat(self, **_kwargs):
        if self.barrier is not None:
            self.barrier.wait(timeout=5)
        adapter = self.ai_service.modstore_adapter
        token = getattr(adapter, "auth_token", str(adapter))
        return {
            "success": True,
            "response": token,
            "request_service_id": id(self.ai_service),
            "close_after_call": getattr(adapter, "close_after_call", False),
        }


def _patch_adapter_from_request(monkeypatch: pytest.MonkeyPatch) -> None:
    def _from_request(_cls, request: Request, **kwargs):
        return _FakeAdapter(
            request.headers.get("x-test-market-token", ""),
            close_after_call=bool(kwargs.get("close_after_call")),
        )

    monkeypatch.setattr(
        planner.ModstorePlatformAdapter,
        "from_request",
        classmethod(_from_request),
    )


@pytest.mark.asyncio
async def test_mainline_injects_request_market_token_without_mutating_singleton(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_adapter_from_request(monkeypatch)
    body = XcagiCompatChatBody(message="你好")

    with patch(
        "app.application.ai_chat_app_service.AIChatApplicationService",
        _FakeAIChatApplicationService,
    ):
        result = await planner._execute_ai_chat_mainline(
            body,
            {},
            request=_request("market-token-single"),
        )

    assert result["response"] == "market-token-single"
    assert result["close_after_call"] is True
    assert result["request_service_id"] != id(_FakeAIChatApplicationService.shared_ai_service)
    assert _FakeAIChatApplicationService.shared_ai_service.modstore_adapter == "shared-provider"


@pytest.mark.asyncio
async def test_mainline_concurrent_requests_never_share_market_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_adapter_from_request(monkeypatch)
    body = XcagiCompatChatBody(message="并发隔离")
    _FakeAIChatApplicationService.barrier = threading.Barrier(2)
    try:
        with patch(
            "app.application.ai_chat_app_service.AIChatApplicationService",
            _FakeAIChatApplicationService,
        ):
            first, second = await asyncio.gather(
                planner._execute_ai_chat_mainline(
                    body,
                    {},
                    request=_request("market-token-a"),
                ),
                planner._execute_ai_chat_mainline(
                    body,
                    {},
                    request=_request("market-token-b"),
                ),
            )
    finally:
        _FakeAIChatApplicationService.barrier = None

    assert {first["response"], second["response"]} == {
        "market-token-a",
        "market-token-b",
    }
    assert first["request_service_id"] != second["request_service_id"]
    assert _FakeAIChatApplicationService.shared_ai_service.modstore_adapter == "shared-provider"


@pytest.mark.asyncio
async def test_mainline_without_market_token_preserves_existing_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_adapter_from_request(monkeypatch)
    body = XcagiCompatChatBody(message="没有市场绑定")

    with patch(
        "app.application.ai_chat_app_service.AIChatApplicationService",
        _FakeAIChatApplicationService,
    ):
        result = await planner._execute_ai_chat_mainline(body, {}, request=_request())

    assert result["response"] == "shared-provider"
    assert result["request_service_id"] == id(_FakeAIChatApplicationService.shared_ai_service)


@pytest.mark.asyncio
async def test_single_route_forwards_request_to_mainline() -> None:
    request = _request("single-route")
    body = XcagiCompatChatBody(message="单条消息", context={"use_ai_chat_mainline": True})

    with (
        patch.object(planner, "assert_p2_elevated_claim_or_raise"),
        patch.object(planner, "resolve_ai_tier", return_value="p1"),
        patch.object(planner, "runtime_context_with_tier", side_effect=lambda ctx, _tier: ctx),
        patch.object(planner, "_ensure_chat_db_read_authorized", return_value=(True, None)),
        patch.object(planner, "planner_workflow_interrupt_reply", return_value=None),
        patch.object(planner, "_ensure_vector_index_if_needed", return_value=None),
        patch.object(planner, "_use_ai_chat_mainline", return_value=True),
        patch.object(
            planner,
            "_execute_ai_chat_mainline",
            new=AsyncMock(return_value={"success": True, "run_id": "single-mainline"}),
        ) as mainline,
        patch(
            "app.application.chat_business_safety.try_handle_business_chat_action",
            return_value=None,
        ),
        patch(
            "app.application.kitten_planner_context.enrich_kitten_analyzer_runtime",
            new=AsyncMock(side_effect=lambda ctx, _message: ctx),
        ),
        patch("app.application.kitten_planner_context.kitten_reply_attachments", return_value={}),
    ):
        result = await planner.execute_compat_chat(request, body)

    assert result["run_id"] == "single-mainline"
    assert mainline.await_args.kwargs["request"] is request


@pytest.mark.asyncio
async def test_batch_route_forwards_same_request_to_every_mainline_message() -> None:
    request = _request("batch-route")
    body = XcagiCompatChatBatchBody(
        messages=["第一条", "第二条"],
        context={"use_ai_chat_mainline": True},
    )

    async def _mainline(_body, _context, *, request, message, **_kwargs):
        return {"success": True, "run_id": f"run-{message}", "request_id": id(request)}

    with (
        patch.object(planner, "assert_p2_elevated_claim_or_raise"),
        patch.object(planner, "resolve_ai_tier", return_value="p1"),
        patch.object(
            planner,
            "_merge_runtime_context_with_message_paths",
            side_effect=lambda ctx, _message: (dict(ctx or {}), []),
        ),
        patch.object(planner, "runtime_context_with_tier", side_effect=lambda ctx, _tier: ctx),
        patch.object(planner, "_ensure_chat_db_read_authorized", return_value=(True, None)),
        patch.object(planner, "planner_workflow_interrupt_reply", return_value=None),
        patch.object(planner, "_ensure_vector_index_if_needed", return_value=None),
        patch.object(planner, "_use_ai_chat_mainline", return_value=True),
        patch.object(
            planner,
            "create_modstore_openai_client_from_request",
            return_value=MagicMock(),
        ),
        patch.object(
            planner,
            "_execute_ai_chat_mainline",
            new=AsyncMock(side_effect=_mainline),
        ) as mainline,
        patch(
            "app.application.chat_business_safety.try_handle_business_chat_action",
            return_value=None,
        ),
    ):
        result = await planner.execute_compat_chat_batch(request, body)

    assert result["count"] == 2
    assert mainline.await_count == 2
    assert all(call.kwargs["request"] is request for call in mainline.await_args_list)
