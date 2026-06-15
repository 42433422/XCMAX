"""Planner 流式/混流内部标记 — 前后端清洗 SSOT（Python）。"""

from __future__ import annotations

import re

# 与 frontend chatBubbleDisplay.PLANNER_DISPLAY_MARKERS 对齐
PLANNER_MARKER_REGEXES: tuple[str, ...] = (
    r"\[正在调用工具:[^\]\n]+\]",
    r"【正在调用工具:[^】\n]+】",
    r"\[正在调用工具:[^\]\n]+(?!\])",
    r"【正在调用工具:[^】\n]+(?!\】)",
    r"\[工具已返回[^\]\n]*\]",
    r"【工具已返回[^】\n]*】",
    r"\[工具未成功[^\]\n]*\]",
    r"【工具未成功[^】\n]*】",
    r"\[需要授权:[^\]\n]+\]",
    r"【需要授权:[^】\n]+】",
    r"\[请提供令牌:[^\]\n]+\]",
    r"【请提供令牌:[^】\n]+】",
    r"（仍在处理中，已等待 \d+ 秒，请稍候…）",
    r"（正在将 Excel 导入数据库[^）]*）",
    r"（正在生成 Word 文档[^）]*）",
    r"（正在生成 Excel 工作簿[^）]*）",
    r"（正在生成可下载文件[^）]*）",
    r"正在连接修茈模型服务…",
    r"(?<![\[\【])正在调用工具:[^\s\]\】\n]{1,64}",
)

_COMPILED = tuple(re.compile(p) for p in PLANNER_MARKER_REGEXES)


def strip_planner_stream_markers(merged: str) -> tuple[str, str | None]:
    """从 planner 混流文本中剥离内部标记，返回 (用户可见正文, thinking_steps)。"""
    if not (merged or "").strip():
        return "", None
    lines: list[str] = []
    user_text = merged
    for pat in _COMPILED:
        for m in pat.finditer(user_text):
            s = m.group(0).strip()
            if s and s not in lines:
                lines.append(s)
        user_text = pat.sub("\n", user_text)
    user_text = re.sub(r"\n{3,}", "\n\n", user_text).strip()
    thinking = "\n".join(lines) if lines else None
    return user_text, thinking
