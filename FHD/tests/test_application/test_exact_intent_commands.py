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
