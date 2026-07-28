"""Regression coverage for the chat -> confirmation-card shipment handoff."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.application.ai_chat_app_service import AIChatApplicationService

ORDER_TEXT = "打印金汉武发货单，黑棕面用修色精，规格28，3桶"
PARSED_NAMED_ORDER = {
    "success": True,
    "unit_name": "金汉武",
    "products": [
        {
            "name": "黑棕面用修色精",
            "tin_spec": 28.0,
            "quantity_tins": 3,
        }
    ],
}


def _make_service() -> AIChatApplicationService:
    with (
        patch("app.application.ai_chat_app_service.get_ai_conversation_service"),
        patch("app.application.ai_chat_app_service.LLMWorkflowPlanner"),
        patch("app.application.ai_chat_app_service.HybridRiskGate"),
        patch("app.application.ai_chat_app_service.WorkflowEngine"),
        patch("app.application.ai_chat_app_service.get_approval_service"),
    ):
        return AIChatApplicationService()


def _response_data() -> dict:
    return {
        "success": True,
        "message": "处理完成",
        "data": {"text": "", "action": "tool_call", "data": {}},
    }


def _assert_confirmation_card(result: dict) -> dict:
    assert result["success"] is True
    assert result["message"] == "已识别订单，请确认执行"
    assert result["task"]["type"] == "shipment_generate"
    assert result["task"]["api_url"] == "/api/tools/execute"
    assert "toolCall" not in result
    return result["task"]["payload"]


def test_normal_chat_returns_confirmation_card_without_generating_document():
    """Natural-language shipment requests cannot generate before the click."""

    service = _make_service()
    shipment_service = MagicMock()

    with (
        patch(
            "app.application.facades.tools_facade._parse_order_text",
            return_value=PARSED_NAMED_ORDER,
        ),
        patch("app.bootstrap.get_shipment_app_service", return_value=shipment_service),
    ):
        result = service._handle_tool_call(
            _response_data(),
            {"text": "好的，正在为金汉武生成发货单。", "action": "tool_call"},
            {
                "tool_key": "shipment_generate",
                "slots": {
                    "unit_name": "金汉武",
                    "products": list(PARSED_NAMED_ORDER["products"]),
                },
            },
            "normal",
            ORDER_TEXT,
        )

    payload = _assert_confirmation_card(result)
    assert payload == {
        "tool_id": "shipment_generate",
        "action": "执行",
        "params": {
            "order_text": ORDER_TEXT,
            "unit_name": "金汉武",
            "products": PARSED_NAMED_ORDER["products"],
            "number_mode": True,
        },
    }
    shipment_service.generate_shipment_document.assert_not_called()


def test_normal_chat_uses_structured_slots_for_confirmation_when_original_is_unavailable():
    """A structured slot fallback is a preview, never an implicit write."""

    service = _make_service()
    shipment_service = MagicMock()
    slots = {
        "unit_name": "金汉武",
        "products": list(PARSED_NAMED_ORDER["products"]),
    }

    with (
        patch(
            "app.application.facades.tools_facade._parse_order_text",
            return_value={"success": False, "message": "未提供原订单文本"},
        ),
        patch("app.bootstrap.get_shipment_app_service", return_value=shipment_service),
    ):
        result = service._execute_normal_mode_tools(
            _response_data(),
            "shipment_generate",
            {},
            {"text": "正在处理。"},
            {"tool_key": "shipment_generate", "slots": slots},
            slots=slots,
        )

    payload = _assert_confirmation_card(result)
    assert payload["params"]["unit_name"] == "金汉武"
    assert payload["params"]["products"] == PARSED_NAMED_ORDER["products"]
    assert payload["params"]["order_text"] == "金汉武，3桶黑棕面用修色精规格28"
    shipment_service.generate_shipment_document.assert_not_called()


def test_pro_chat_returns_the_same_confirmation_card_without_generating_document():
    """The pro_default shortcut does not bypass user confirmation."""

    service = _make_service()
    shipment_service = MagicMock()

    with (
        patch(
            "app.application.facades.tools_facade._parse_order_text",
            return_value=PARSED_NAMED_ORDER,
        ),
        patch("app.bootstrap.get_shipment_app_service", return_value=shipment_service),
    ):
        result = service._handle_tool_call(
            _response_data(),
            {"text": "已识别订单，请确认生成发货单。", "action": "tool_call"},
            {
                "tool_key": "shipment_generate",
                "slots": {
                    "unit_name": "金汉武",
                    "products": list(PARSED_NAMED_ORDER["products"]),
                },
            },
            "pro",
            ORDER_TEXT,
        )

    payload = _assert_confirmation_card(result)
    assert payload["params"]["order_text"] == ORDER_TEXT
    assert payload["params"]["products"] == PARSED_NAMED_ORDER["products"]
    shipment_service.generate_shipment_document.assert_not_called()


def test_confirmation_card_carries_explicit_document_number_without_execution():
    """A labelled number stays a preview field until the user clicks confirm."""

    from app.application.ai_chat_helpers import build_shipment_preview_response_dict

    preview = build_shipment_preview_response_dict(
        "金汉武",
        PARSED_NAMED_ORDER["products"],
        "打印金汉武发货单，黑棕面用修色精，编号9803，规格28，3桶",
        order_number="9803",
        order_number_provenance={
            "kind": "explicit_document_number",
            "label": "编号",
            "value": "9803",
        },
    )

    payload = _assert_confirmation_card(preview)
    assert payload["params"]["order_number"] == "9803"
    assert payload["params"]["order_number_provenance"]["kind"] == "explicit_document_number"
    assert preview["data"]["order_number_provenance"]["value"] == "9803"
