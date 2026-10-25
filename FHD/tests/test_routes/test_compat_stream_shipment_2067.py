"""#2067：桌面「智能对话」流式入口开单要和 /api/ai/chat 走同一套规则识别。"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import Request

from app.application.ai_chat_app_service import AIChatApplicationService
from app.application.workflow.workflow_types import PlanGraph
from app.fastapi_routes import xcagi_compat_chat_helpers as chat_helpers

ISSUE_MESSAGE = "客户闭环验收客户 发货单：客户闭环测试商品A 数量24 单价3.5"


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/mod/xcagi-planner-bridge/chat/stream",
            "headers": [],
            "client": ("127.0.0.1", 12345),
        }
    )


def _events(raw: bytes) -> list[dict[str, Any]]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in raw.decode("utf-8").splitlines()
        if line.startswith("data: ")
    ]


def _no_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_called(*_args: Any, **_kwargs: Any):
        raise AssertionError("开单不能交给 LLM 规划器")

    monkeypatch.setattr(chat_helpers, "_xcagi_guarded_planner_stream_events", fail_if_called)
    monkeypatch.setattr(
        "app.domain.conversation.legacy_services.modstore_adapter.create_modstore_openai_client_from_request",
        fail_if_called,
    )
    monkeypatch.setattr(
        "app.fastapi_routes.xcagi_compat_chat_stream._classify_and_submit_client_issue",
        lambda *_a, **_k: None,
    )


def test_stream_entry_creates_order_with_explicit_quantity_and_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_llm(monkeypatch)
    service = AIChatApplicationService()
    monkeypatch.setattr("app.application.get_ai_chat_app_service", lambda: service)
    shipment_svc = MagicMock()
    shipment_svc.generate_shipment_document.return_value = {
        "success": True,
        "message": "发货单生成成功",
        "doc_name": "发货单_2067.xlsx",
    }
    body = chat_helpers.XcagiCompatChatBody(
        message=ISSUE_MESSAGE.replace("数量24", "数量24kg"), user_id="u-2067"
    )
    with patch("app.bootstrap.get_shipment_app_service", return_value=shipment_svc):
        raw = b"".join(chat_helpers._xcagi_planner_stream_bytes(_request(), body, ai_tier="P1"))

    events = _events(raw)
    assert [event["type"] for event in events] == ["token", "done"]
    shipment_svc.generate_shipment_document.assert_called_once()
    kwargs = shipment_svc.generate_shipment_document.call_args.kwargs
    assert kwargs["unit_name"] == "客户闭环验收客户"
    (product,) = kwargs["products"]
    assert product["name"] == "客户闭环测试商品A"
    assert product["quantity"] == 24
    assert product["unit"] == "kg"
    assert product["unit_price"] == 3.5
    document = events[-1]["result"]["data"]["data"]["document"]
    assert document["doc_name"] == "发货单_2067.xlsx"


@pytest.mark.parametrize(
    "message",
    [
        ISSUE_MESSAGE,
        "请备份数据库。执行前先给我确认，需要审批的操作提交审批。",
        "请恢复数据库，使用备份 xcagi.db.20261011_160815.bak。执行前先给我确认。",
    ],
)
def test_stream_entry_hands_shipment_to_the_same_chat_service(
    monkeypatch: pytest.MonkeyPatch,
    message: str,
) -> None:
    _no_llm(monkeypatch)
    service = MagicMock(_pending_workflows={})
    service.process_chat.return_value = {"success": True, "response": "已生成发货单"}
    monkeypatch.setattr("app.application.get_ai_chat_app_service", lambda: service)
    body = chat_helpers.XcagiCompatChatBody(message=message, user_id="u-2067")
    raw = b"".join(chat_helpers._xcagi_planner_stream_bytes(_request(), body, ai_tier="P1"))

    service.process_chat.assert_called_once()
    assert service.process_chat.call_args.kwargs["message"] == message
    assert _events(raw)[-1]["result"]["response"] == "已生成发货单"


@pytest.mark.parametrize("message", ["确认", "取消"])
@pytest.mark.parametrize(
    "case", ["absent", "missing", "corrupt", "empty", "expired", "cross_session"]
)
def test_cancel_reaches_pending_guard_before_smalltalk(monkeypatch, message, case):
    _no_llm(monkeypatch)
    service = AIChatApplicationService()
    monkeypatch.setattr(service, "_hydrate_pending_workflow", lambda *_a: False)
    if case != "absent":
        service._pending_workflows["u-cancel"] = {
            "plan": {}
            if case == "corrupt"
            else PlanGraph("empty", "fixture")
            if case == "empty"
            else None,
            "runtime_context": {"session_id": "other" if case == "cross_session" else "s"},
            "kind": "clarification" if case == "expired" else "workflow",
            "created_at": 1.0,
            "ttl_seconds": 30,
        }
    monkeypatch.setattr("app.application.get_ai_chat_app_service", lambda: service)
    execute = MagicMock(side_effect=AssertionError("Invalid control must not execute"))
    monkeypatch.setattr(service, "_run_workflow_with_state_updates", execute)
    trace = MagicMock(side_effect=AssertionError("取消不得创建闲聊业务任务"))
    monkeypatch.setattr(service, "_attach_deterministic_workflow_trace", trace)
    body = chat_helpers.XcagiCompatChatBody(
        message=message, user_id="u-cancel", context={"session_id": "s"}
    )
    result = _events(
        b"".join(chat_helpers._xcagi_planner_stream_bytes(_request(), body, ai_tier="P1"))
    )[-1]["result"]
    trace.assert_not_called()
    assert result["data"]["action"] == "clarification_required"
    execute.assert_not_called()
    assert (
        not service._pending_workflows
        if case in {"absent", "expired"}
        else "u-cancel" in service._pending_workflows
    )


def test_stream_missing_spec_requests_clarification_without_document(monkeypatch):
    from app.application.shipment_app_service import ShipmentApplicationService

    _no_llm(monkeypatch)
    service = AIChatApplicationService()
    monkeypatch.setattr("app.application.get_ai_chat_app_service", lambda: service)
    generator = MagicMock()
    shipment = ShipmentApplicationService(MagicMock(), generator, MagicMock())
    body = chat_helpers.XcagiCompatChatBody(message=ISSUE_MESSAGE, user_id="u-2292")
    with patch("app.bootstrap.get_shipment_app_service", return_value=shipment):
        raw = b"".join(chat_helpers._xcagi_planner_stream_bytes(_request(), body, ai_tier="P1"))
    result = _events(raw)[-1]["result"]
    assert result["success"] is False
    assert "计量单位" in result["response"]
    assert "已生成" not in result["response"]
    generator.generate.assert_not_called()
