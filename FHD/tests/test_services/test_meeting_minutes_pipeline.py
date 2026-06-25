"""会议纪要三级派生内核：派生顺序契约、降级、失败、hash。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

import app.mod_sdk  # noqa: F401  # 预热 app.services 包，规避隔离运行时已知的循环导入
from app.services.meeting_minutes.pipeline import (
    MeetingLLMUnavailable,
    compute_source_hash,
    generate_all_levels,
    load_levels_config,
)

PIPE = "app.services.meeting_minutes.pipeline.chat_completion_openai_format"


def _resp(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


@pytest.mark.asyncio
async def test_completed_all_three_levels():
    mock = AsyncMock(side_effect=[_resp("L1剧本"), _resp("L2架构图"), _resp("L3说人话")])
    with patch(PIPE, mock):
        out = await generate_all_levels("张三：下周上线。李四：好。")
    assert out["status"] == "completed"
    assert out["level1_script"] == "L1剧本"
    assert out["level2_architecture"] == "L2架构图"
    assert out["level3_plain"] == "L3说人话"
    assert mock.await_count == 3


@pytest.mark.asyncio
async def test_derivation_order_contract():
    """SSOT 契约：L2 的输入必须是 L1 的输出，L3 的输入必须是 L2 的输出（绝不越级读 raw）。"""
    captured: list[str] = []

    async def _fake(messages, **_kwargs):
        # messages[1] 是 user 内容（上游产物）；按调用次序返回各级输出
        captured.append(messages[1]["content"])
        idx = len(captured)
        return _resp({1: "OUT_L1", 2: "OUT_L2", 3: "OUT_L3"}[idx])

    with patch(PIPE, side_effect=_fake):
        out = await generate_all_levels("RAW_TRANSCRIPT")

    assert out["status"] == "completed"
    # 第一级吃 raw
    assert captured[0] == "RAW_TRANSCRIPT"
    # 第二级吃第一级的输出，而非 raw
    assert captured[1] == "OUT_L1"
    assert captured[1] != "RAW_TRANSCRIPT"
    # 第三级吃第二级的输出，而非 L1/raw
    assert captured[2] == "OUT_L2"
    assert captured[2] not in ("OUT_L1", "RAW_TRANSCRIPT")


@pytest.mark.asyncio
async def test_degraded_when_llm_unavailable():
    """LLM 未配置（返回 None）→ degraded，三级为 None，不抛异常。"""
    with patch(PIPE, AsyncMock(return_value=None)):
        out = await generate_all_levels("有内容的会议原文")
    assert out["status"] == "degraded"
    assert out["level1_script"] is None
    assert out["level2_architecture"] is None
    assert out["level3_plain"] is None
    assert out["error_message"]


@pytest.mark.asyncio
async def test_degraded_when_empty_content():
    with patch(PIPE, AsyncMock(return_value={"choices": [{"message": {"content": "   "}}]})):
        out = await generate_all_levels("有内容的会议原文")
    assert out["status"] == "degraded"


@pytest.mark.asyncio
async def test_failed_on_recoverable_error():
    """provider 抛可恢复错误 → failed，不抛出。"""
    with patch(PIPE, AsyncMock(side_effect=ConnectionError("network down"))):
        out = await generate_all_levels("有内容的会议原文")
    assert out["status"] == "failed"
    assert out["error_message"]


@pytest.mark.asyncio
async def test_empty_raw_is_failed_without_llm_call():
    mock = AsyncMock()
    with patch(PIPE, mock):
        out = await generate_all_levels("   ")
    assert out["status"] == "failed"
    mock.assert_not_awaited()


def test_source_hash_stable_and_sensitive():
    assert compute_source_hash("abc") == compute_source_hash("abc")
    assert compute_source_hash("abc") != compute_source_hash("abd")
    assert len(compute_source_hash("abc")) == 64


def test_levels_config_shape():
    cfg = load_levels_config()
    ids = [lvl["id"] for lvl in cfg["levels"]]
    assert ids == ["level1_script", "level2_architecture", "level3_plain"]
    # 派生关系链
    by_id = {lvl["id"]: lvl for lvl in cfg["levels"]}
    assert by_id["level1_script"]["derives_from"] == "raw"
    assert by_id["level2_architecture"]["derives_from"] == "level1_script"
    assert by_id["level3_plain"]["derives_from"] == "level2_architecture"


def test_meeting_llm_unavailable_is_runtimeerror():
    assert issubclass(MeetingLLMUnavailable, RuntimeError)
