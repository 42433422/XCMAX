"""闲聊回复的增量 JSON 提取：确认 mode=reply 后逐段下发正文。"""

import asyncio
import json

from app.application.workflow.llm_plan_generation import (
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
