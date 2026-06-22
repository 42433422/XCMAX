"""L1 规则推断器：实时从用户消息提取 persona 信号。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.persona.value_objects import PersonaAxes


@dataclass(frozen=True)
class RuleInferResult:
    """L1 规则推断结果。"""

    axes: PersonaAxes
    confidence: float
    signals: list[str]  # 命中的规则名列表，用于调试


# 语气词/emoji 模式
_MODAL_PARTICLES = re.compile(r"[哈呢呀哦嘛啦哇呗]")
_EMOJI_PATTERN = re.compile(
    "[\U0001f600-\U0001f64f\U0001f300-\U0001f5ff\U0001f680-\U0001f6ff\U0001f1e0-\U0001f1ff]"
)
# 祈使句模式
_IMPERATIVE_PATTERN = re.compile(
    r"^(帮我|查下|弄一下|搞一下|弄下|搞下|处理下|处理一下|弄|查|搞|做)"
)
# 详细/简洁请求
_DETAIL_REQUEST = re.compile(r"(详细|展开|具体|说说|讲讲|解释)")
_BRIEF_REQUEST = re.compile(r"(简单|简洁|长话短说|少说|概括|摘要)")


class RuleInferencer:
    """L1 规则推断器。

    从用户当前消息 + 最近 N 轮历史提取 persona 信号，
    输出四轴瞬时值（0-1）+ 置信度。
    延迟预算：<1ms（纯内存计算）。
    """

    def infer(self, message: str | None, history: list[dict]) -> RuleInferResult:
        """推断四轴参数。

        Args:
            message: 用户当前消息
            history: 最近 N 轮历史（每条 {"role": "user"|"assistant", "content": "..."})

        Returns:
            RuleInferResult: 四轴值 + 置信度 + 命中信号
        """
        if not message or not message.strip():
            return RuleInferResult(
                axes=PersonaAxes(),
                confidence=0.0,
                signals=[],
            )

        signals: list[str] = []
        warmth_score = 0.5
        detail_score = 0.5
        proactivity_score = 0.5
        structure_score = 0.5

        # === warmth 规则 ===
        emoji_count = len(_EMOJI_PATTERN.findall(message))
        modal_count = len(_MODAL_PARTICLES.findall(message))
        is_imperative = bool(_IMPERATIVE_PATTERN.match(message.strip()))

        if emoji_count > 0:
            warmth_score = min(0.9, 0.6 + emoji_count * 0.1)
            signals.append("emoji")
        elif modal_count > 0:
            warmth_score = min(0.8, 0.55 + modal_count * 0.08)
            signals.append("modal_particle")
        elif is_imperative:
            warmth_score = 0.35
            signals.append("imperative")

        # === detail 规则 ===
        msg_len = len(message)
        has_detail_request = bool(_DETAIL_REQUEST.search(message))
        has_brief_request = bool(_BRIEF_REQUEST.search(message))

        if has_brief_request:
            detail_score = 0.3
            signals.append("brief_request")
        elif has_detail_request:
            detail_score = 0.8
            signals.append("detail_request")
        elif msg_len <= 10:
            detail_score = 0.35
            signals.append("short_message")
        elif msg_len >= 50:
            detail_score = 0.7
            signals.append("long_message")

        # === proactivity 规则（问句比例）===
        question_count = message.count("?") + message.count("？")
        if question_count >= 2:
            proactivity_score = 0.35
            signals.append("multi_question")
        elif question_count == 0 and msg_len > 5:
            proactivity_score = 0.65
            signals.append("statement")

        # === structure 规则（编号/列表）===
        has_list = bool(re.search(r"\d+[.、)]", message))
        if has_list:
            structure_score = 0.8
            signals.append("list_format")

        axes = PersonaAxes(
            warmth=warmth_score,
            detail=detail_score,
            proactivity=proactivity_score,
            structure=structure_score,
        )
        confidence = min(1.0, len(signals) * 0.25)

        return RuleInferResult(axes=axes, confidence=confidence, signals=signals)
