"""L3 LLM 推断器：定期复盘校准。"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from app.domain.persona.value_objects import PersonaAxes

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LlmInferResult:
    """L3 LLM 推断结果。"""

    axes: PersonaAxes
    reason: str
    confidence: float


_L3_SYSTEM_PROMPT = """你是对话风格分析助手。分析用户最近的对话历史，输出用户的对话风格参数。

输出 JSON 格式：
{
  "warmth": 0.0-1.0,  // 亲切度：0=就事论事，1=有温度
  "detail": 0.0-1.0,  // 详细度：0=概括，1=具体步骤
  "proactivity": 0.0-1.0,  // 主动度：0=问答，1=主动建议
  "structure": 0.0-1.0,  // 结构度：0=灵活，1=结构化
  "reason": "判断依据简述"
}

只输出 JSON，不要其他内容。"""


class LlmInferencer:
    """L3 LLM 推断器。

    流程：
    1. 用小模型分析用户最近 20 轮对话风格
    2. 输出四轴校准值 + 理由（JSON）
    3. 与 L1/L2 加权融合

    延迟预算：~1-2s（异步，不阻塞对话）
    作用：校准规则和 embedding 的偏差，处理复杂语境
    """

    def __init__(self, llm_client):
        self._llm_client = llm_client

    async def infer(
        self,
        user_id: str,
        history: list[dict],
        current_axes: PersonaAxes,
    ) -> LlmInferResult:
        """推断四轴参数。

        Args:
            user_id: 用户 ID
            history: 最近 20 轮对话历史
            current_axes: 当前四轴值（供 LLM 参考）

        Returns:
            LlmInferResult: 四轴值 + 理由 + 置信度
        """
        if not history:
            return LlmInferResult(
                axes=PersonaAxes(),
                reason="无历史数据",
                confidence=0.0,
            )

        try:
            # 构造对话摘要
            summary = self._summarize_history(history)
            user_prompt = f"用户最近对话：\n{summary}\n\n当前四轴值：{current_axes.to_dict()}\n\n请分析用户对话风格："

            messages = [
                {"role": "system", "content": _L3_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]

            response = await self._llm_client.chat_completion(messages)
            content = response["choices"][0]["message"]["content"]

            return self._parse_response(content)
        except Exception as e:
            logger.warning("L3 LLM 推断失败，返回中性值: %s", e)
            return LlmInferResult(
                axes=PersonaAxes(),
                reason=f"推断失败: {e}",
                confidence=0.0,
            )

    def _summarize_history(self, history: list[dict]) -> str:
        """将历史对话摘要为文本。"""
        lines = []
        for msg in history[-20:]:  # 最多 20 轮
            role = msg.get("role", "unknown")
            content = str(msg.get("content", ""))[:100]  # 每条最多 100 字
            lines.append(f"[{role}] {content}")
        return "\n".join(lines)

    def _parse_response(self, content: str) -> LlmInferResult:
        """解析 LLM 返回的 JSON。"""
        try:
            data = json.loads(content)
            axes = PersonaAxes(
                warmth=float(data.get("warmth", 0.5)),
                detail=float(data.get("detail", 0.5)),
                proactivity=float(data.get("proactivity", 0.5)),
                structure=float(data.get("structure", 0.5)),
            )
            reason = str(data.get("reason", ""))
            return LlmInferResult(axes=axes, reason=reason, confidence=0.7)
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.warning("L3 LLM 返回解析失败: %s, content: %s", e, content[:200])
            return LlmInferResult(
                axes=PersonaAxes(),
                reason=f"解析失败: {e}",
                confidence=0.0,
            )
