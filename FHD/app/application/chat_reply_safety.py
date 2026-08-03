"""Safety boundary for model text that is rendered as an end-user chat reply."""

from __future__ import annotations

import re
from html import unescape

_TOOL_CALL_MARKER_RE = re.compile(r"<\s*/?\s*tool_call\b", re.IGNORECASE)
_TOOL_CALL_BLOCK_RE = re.compile(
    r"<\s*tool_call\b.*?(?:<\s*/\s*tool_call\s*>|$)",
    re.IGNORECASE | re.DOTALL,
)
_NO_VISIBLE_REPLY = "未生成可执行的业务动作，未执行任何数据操作。请重新说明要查看、修改或删除的具体对象。"


def sanitize_model_chat_reply(raw: object) -> str:
    """Remove leaked tool protocol before a model reply reaches any chat client."""
    original = str(raw or "")
    decoded = original
    for _ in range(2):
        decoded = unescape(decoded)
    if not _TOOL_CALL_MARKER_RE.search(decoded):
        return original
    visible = _TOOL_CALL_BLOCK_RE.sub("", decoded).strip()
    return visible or _NO_VISIBLE_REPLY
