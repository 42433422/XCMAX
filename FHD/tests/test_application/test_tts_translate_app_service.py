"""tts_translate_app_service 分支覆盖。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.application.tts_translate_app_service import translate_zh_to_en


@pytest.mark.asyncio
async def test_translate_empty_text() -> None:
    result = await translate_zh_to_en("   ")
    assert result["success"] is False
    assert "不能为空" in result["message"]


@pytest.mark.asyncio
async def test_translate_success() -> None:
    with patch(
        "app.infrastructure.llm.invoke.chat_completion_openai_format",
        new=AsyncMock(
            return_value={
                "choices": [{"message": {"content": "Hello"}}],
            }
        ),
    ):
        result = await translate_zh_to_en("你好")
    assert result["success"] is True
    assert result["translation"] == "Hello"


@pytest.mark.asyncio
async def test_translate_empty_model_content() -> None:
    with patch(
        "app.infrastructure.llm.invoke.chat_completion_openai_format",
        new=AsyncMock(return_value={"choices": [{"message": {"content": "  "}}]}),
    ):
        result = await translate_zh_to_en("你好")
    assert result["success"] is False
    assert "为空" in result["message"]


@pytest.mark.asyncio
async def test_translate_recoverable_error() -> None:
    with patch(
        "app.infrastructure.llm.invoke.chat_completion_openai_format",
        new=AsyncMock(side_effect=ConnectionError("down")),
    ):
        result = await translate_zh_to_en("你好")
    assert result["success"] is False
    assert "暂不可用" in result["message"]


@pytest.mark.asyncio
async def test_translate_non_dict_response() -> None:
    with patch(
        "app.infrastructure.llm.invoke.chat_completion_openai_format",
        new=AsyncMock(return_value="not-a-dict"),
    ):
        result = await translate_zh_to_en("你好")
    assert result["success"] is False
    assert "暂不可用" in result["message"]
