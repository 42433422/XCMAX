import json
from types import SimpleNamespace

from app.fastapi_routes.mobile_extensions.cs_helpers import _service_request_to_cs_messages


def test_service_request_to_cs_messages_prefers_manual_response_over_ai_reply():
    row = SimpleNamespace(
        id=7,
        title="客户原话",
        description="客户原话",
        response="人工回复",
        extra_data=json.dumps({"ai_reply": "AI 自动回复"}, ensure_ascii=False),
        created_at=None,
        updated_at=None,
    )

    messages = _service_request_to_cs_messages(row)

    assert messages == [
        {
            "message_id": "sr_7_user",
            "sender": "user",
            "body": "客户原话",
            "timestamp": "",
            "msg_type": "text",
        },
        {
            "message_id": "sr_7_cs",
            "sender": "cs",
            "body": "人工回复",
            "timestamp": "",
            "msg_type": "text",
        },
    ]


def test_service_request_to_cs_messages_extracts_message_text_from_ai_json():
    row = SimpleNamespace(
        id=8,
        title="客户原话",
        description="客户原话",
        response="",
        extra_data=json.dumps(
            {"ai_reply": '```json\n{"message_text":"清洗后的回复"}\n```'},
            ensure_ascii=False,
        ),
        created_at=None,
        updated_at=None,
    )

    messages = _service_request_to_cs_messages(row)

    assert messages[1]["body"] == "清洗后的回复"
