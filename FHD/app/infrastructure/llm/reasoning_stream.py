"""把模型推理文本作为思考步骤推给当前对话流。

前端把 thinking 事件累加到消息的 thinkingSteps，并随消息一起落库，
因此推送即持久化；没有流式上下文时静默忽略，不影响回答本身。
"""

from __future__ import annotations

from app.utils.operational_errors import BOUNDARY_ERRORS

REASONING_NOTE_PREFIX = "模型思考："
REASONING_NOTE_LIMIT = 4000


def publish_reasoning(reasoning: str) -> None:
    text = str(reasoning or "").strip()
    if not text:
        return
    if len(text) > REASONING_NOTE_LIMIT:
        text = f"{text[:REASONING_NOTE_LIMIT]}…"
    try:
        from app.infrastructure.chat_stream_lifetime import publish_stream_note

        publish_stream_note(f"{REASONING_NOTE_PREFIX}{text}")
    except BOUNDARY_ERRORS:  # 观测通道失败不能改变回答结果
        return


def reasoning_from_message(payload: dict) -> str:
    """从完整响应里取推理文本（choices[0].message.reasoning_content）。"""
    for choice in payload.get("choices") or []:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message")
        if not isinstance(message, dict):
            continue
        for key in ("reasoning_content", "reasoning"):
            value = message.get(key)
            if isinstance(value, str) and value:
                return value
    return str(payload.get("reasoning_content") or "")
