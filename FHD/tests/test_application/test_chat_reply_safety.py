from app.application.chat_reply_safety import sanitize_model_chat_reply


def test_sanitize_model_chat_reply_keeps_visible_text_and_removes_tool_protocol() -> None:
    assert sanitize_model_chat_reply("已查询。<tool_call>hidden</tool_call>") == "已查询。"


def test_sanitize_model_chat_reply_rejects_encoded_protocol_only_reply() -> None:
    reply = sanitize_model_chat_reply("&amp;lt;tool_call&amp;gt;hidden&amp;lt;/tool_call&amp;gt;")
    assert "未执行任何数据操作" in reply
