from __future__ import annotations

import re


def thinking_steps_from_planner_stream_text(merged: str) -> str | None:
    if not (merged or "").strip():
        return None
    lines: list[str] = []
    patterns = (
        r"\[正在调用工具:[^\]\n]+\]",
        r"\[工具已返回[^\]\n]*\]|\[工具未成功[^\]\n]*\]",
        r"\[需要授权:[^\]\n]+\]|\[请提供令牌:[^\]\n]+\]",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, merged):
            step = match.group(0).strip()
            if step and step not in lines:
                lines.append(step)
    return "\n".join(lines) if lines else None
