from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

import pytest

from app.application.workflow.multimodal_user_content import EmptyMultimodalResponseError
from app.legacy.chat.legacy_chat_adapter import chat_stream_text


def test_empty_image_stream_stops_after_first_request() -> None:
    client = MagicMock()
    client.chat.completions.create.return_value = iter(())
    payload = base64.standard_b64encode(b"image").decode("ascii")
    runtime_context = {
        "multimodal_attachments": [
            {"filename": "screen.png", "mime_type": "image/png", "data_base64": payload}
        ]
    }

    with (
        patch("app.legacy.chat.legacy_chat_adapter._get_workflow_tool_registry", return_value=[]),
        pytest.raises(EmptyMultimodalResponseError, match="停止重复空请求"),
    ):
        list(
            chat_stream_text(
                "看看截图",
                runtime_context=runtime_context,
                model="text-model",
                client=client,
            )
        )

    assert client.chat.completions.create.call_count == 1
