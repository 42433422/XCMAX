import pytest

from app.services.intent_service import recognize_intents
from app.services.rule_engine import RuleEngine


@pytest.mark.parametrize(
    "message,expected",
    [
        ("打印机列表", "printer_list"),
        (" 微信联系人 ", "wechat"),
        ("联系人列表", "wechat"),
        ("系统设置", "settings"),
        ("模板预览", "template_preview"),
        ("提取模板", "template_extract"),
        ("打印标签", "print_label"),
    ],
)
def test_complete_configured_command_wins_over_broad_keywords(message, expected):
    result = recognize_intents(message)
    assert result["tool_key"] == expected
    assert result["primary_intent"] == expected


def test_exact_command_does_not_override_a_longer_request():
    engine = RuleEngine()
    matches = engine.match_intents("把打印机列表发给他")
    assert matches[0]["tool_key"] == "wechat_send"
    assert all(item["tool_key"] != "printer_list" for item in matches)


def test_negated_print_command_still_cannot_execute():
    result = recognize_intents("不要打印标签")
    assert result["is_negated"]
    assert result["tool_key"] is None


def test_normal_router_keeps_label_model_separate_from_quantity():
    from app.application.normal_chat_dispatch import route_normal_mode_message

    result = route_normal_mode_message("打印标签 A9803 20张")
    assert result == {"intent": "label_print", "slots": {"model_number": "A9803", "quantity": 20}}
    result = route_normal_mode_message("打印标签 A9803")
    assert result["slots"]["quantity"] == 1
    assert route_normal_mode_message("打印9803规格28")["intent"] == "shipment"
    assert route_normal_mode_message("不要打印标签 A9803 20张")["intent"] == "unknown"


@pytest.mark.parametrize(
    "text,model,quantity",
    [
        ("打印20张标签", "", 20),
        ("28规格的要贴标，打20张", "", 20),
        ("打印20张 A9803标签", "A9803", 20),
        ("打印标签9803规格28，20张", "9803", 20),
        ("标签A9803和B200各20张", "", 20),
    ],
)
def test_label_quantity_or_specification_does_not_supply_missing_model(text, model, quantity):
    from app.application.normal_chat_dispatch import route_normal_mode_message

    assert route_normal_mode_message(text) == {
        "intent": "label_print",
        "slots": {"model_number": model, "quantity": quantity},
    }
