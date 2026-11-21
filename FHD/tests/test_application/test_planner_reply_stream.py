"""闲聊回复的增量 JSON 提取：确认 mode=reply 后逐段下发正文。"""

import asyncio
import json
from unittest.mock import Mock

import httpx
import pytest

from app.application.workflow.llm_plan_generation import (
    LlmPlanGeneration,
    _consume_reply_stream,
    _reply_prefix,
)


def test_reply_prefix_requires_confirmed_mode():
    assert _reply_prefix('{"mode":"rep') is None
    assert _reply_prefix('{"mode":"workflow"') is None
    assert _reply_prefix('{"mode":"reply","reply":"你') == "你"
    # mode 尚未送达也不阻塞，reply 字段即可开始下发。
    assert _reply_prefix('{"reply":"你') == "你"
    assert _reply_prefix('{"reply":"你","nodes":[{"tool_id":"excel"}]') is None


def test_reply_prefix_decodes_escapes_across_chunks():
    assert _reply_prefix('{"mode":"reply","reply":"你好\\n世界') == "你好\n世界"
    assert _reply_prefix('{"mode":"reply","reply":"引号\\"结尾') == '引号"结尾'


def test_consume_reply_stream_publishes_progressive_deltas():
    parts = ['{"mode":"reply",', '"reply":"你', "好", '世界"}']

    async def stream():
        for part in parts:
            yield part

    emitted: list[str] = []
    text, prefix = asyncio.run(_consume_reply_stream(stream(), emitted.append))
    assert "".join(emitted) == "你好世界"
    assert prefix == "你好世界"
    assert json.loads(text)["reply"] == "你好世界"


@pytest.mark.parametrize("has_lifetime", [False, True])
def test_absent_stream_does_not_consume_the_only_model_attempt(monkeypatch, has_lifetime):
    from app.application.workflow.retry_policy import planning_request_scope
    from app.infrastructure.chat_stream_lifetime import StreamLifetime, current_lifetime

    monkeypatch.setenv("XCAGI_PLAN_MAX_MODEL_CALLS", "1")
    monkeypatch.setattr(
        "app.application.workflow.planner_llm_gateway.stream_planner_completion", lambda **_: None
    )
    completion = Mock(
        return_value={
            "choices": [{"message": {"content": '{"mode":"reply","reply":"收到"}'}}],
        }
    )
    generator = LlmPlanGeneration(Mock(get_context=Mock(return_value=None)), completion, Mock())
    context = {}
    token = current_lifetime.set(StreamLifetime() if has_lifetime else None)
    try:
        with planning_request_scope(context):
            result = generator.generate("p", "u", "你好", {}, context)
    finally:
        current_lifetime.reset(token)
    assert result is not None and result.metadata["reply"] == "收到"
    assert completion.call_count == context["planning_diagnostics"]["model_attempts"] == 1
    assert "exhausted" not in context["planning_diagnostics"]


@pytest.mark.parametrize("fault", ["newline", "duplicate", "truncated", "transport"])
def test_visible_stream_reply_is_never_replayed_or_marked_complete_after_failure(
    monkeypatch, fault
):
    from app.application.workflow.retry_policy import planning_request_scope
    from app.infrastructure.chat_stream_lifetime import StreamLifetime, current_lifetime

    async def stream():
        yield {
            "newline": '{"mode":"reply","reply":"first\nanswer"}',
            "duplicate": '{"mode":"reply","reply":"first","reply":"second"}',
        }.get(fault, '{"mode":"reply","reply":"first')
        if fault == "transport":
            raise httpx.ReadError("private upstream detail")

    monkeypatch.setattr(
        "app.application.workflow.planner_llm_gateway.stream_planner_completion",
        lambda **_: stream(),
    )
    completion = Mock(side_effect=AssertionError("must not replay after visible output"))
    generator = LlmPlanGeneration(Mock(get_context=Mock(return_value=None)), completion, Mock())
    context, visible = {}, []
    lifetime = StreamLifetime()
    lifetime.observe_deltas(visible.append)
    token = current_lifetime.set(lifetime)
    try:
        with planning_request_scope(context):
            result = generator.generate("p", "u", "你好", {}, context)
    finally:
        current_lifetime.reset(token)
    assert visible and result is None
    completion.assert_not_called()
    assert context["planning_diagnostics"]["model_attempts"] == 1
    assert context["planning_failure_kind"] == (
        "model_unavailable" if fault == "transport" else "plan_format_invalid"
    )
    assert "private upstream detail" not in json.dumps(context)
