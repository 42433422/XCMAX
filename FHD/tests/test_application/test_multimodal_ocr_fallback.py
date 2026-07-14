from __future__ import annotations

import base64

import pytest

from app.application.workflow.multimodal_user_content import (
    UnsupportedMultimodalModelError,
    messages_have_image_parts,
    replace_image_parts_with_ocr_text,
)


def _messages() -> list[dict]:
    payload = base64.standard_b64encode(b"local image bytes").decode("ascii")
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "这张截图有什么问题？"},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{payload}"},
                },
            ],
        }
    ]


def test_text_model_image_is_replaced_with_local_ocr_text() -> None:
    messages = _messages()

    prepared = replace_image_parts_with_ocr_text(
        messages,
        model_label="xiaomi/mimo-v2.5-pro",
        model_confirmed_text_only=True,
        recognizer=lambda raw: {"success": True, "text": "登录按钮\n用户名"},
    )

    assert messages_have_image_parts(messages) is True
    assert messages_have_image_parts(prepared) is False
    assert isinstance(prepared[0]["content"], str)
    assert "这张截图有什么问题" in prepared[0]["content"]
    assert "本地 OCR" in prepared[0]["content"]
    assert "登录按钮" in prepared[0]["content"]


def test_text_model_image_without_ocr_text_returns_actionable_error() -> None:
    with pytest.raises(UnsupportedMultimodalModelError, match="不支持直接读取图片"):
        replace_image_parts_with_ocr_text(
            _messages(),
            model_label="xiaomi/mimo-v2.5-pro",
            model_confirmed_text_only=True,
            recognizer=lambda raw: {"success": False, "text": ""},
        )
