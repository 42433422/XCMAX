"""朗读字幕短译（中文 → 英文）应用服务。"""

from __future__ import annotations

import logging
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You are a concise translator. Translate the user's Chinese text into natural English. "
    "Output ONLY the English translation, no quotes, no explanation."
)


async def translate_zh_to_en(text: str, *, max_chars: int = 500) -> dict[str, Any]:
    """返回 ``{success, translation|message}``。"""
    raw = str(text or "").strip()
    if not raw:
        return {"success": False, "message": "text 不能为空"}
    try:
        from app.infrastructure.llm import invoke

        resp = await invoke.chat_completion_openai_format(
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": raw[: max(1, int(max_chars))]},
            ],
            temperature=0.2,
            max_tokens=400,
            profile="default",
        )
    except RECOVERABLE_ERRORS as exc:
        logger.info("tts translate failed: %s", type(exc).__name__)
        return {"success": False, "message": "翻译服务暂不可用"}
    if not isinstance(resp, dict):
        return {"success": False, "message": "翻译服务暂不可用"}
    choices = resp.get("choices") or []
    content = ""
    if choices and isinstance(choices[0], dict):
        content = str((choices[0].get("message") or {}).get("content") or "").strip()
    if not content:
        return {"success": False, "message": "翻译结果为空"}
    return {"success": True, "translation": content, "data": {"translation": content}}
