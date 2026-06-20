"""Persona 模型参数映射器：四轴 → 推理参数。"""
from __future__ import annotations

from app.domain.persona.value_objects import PersonaAxes, RapportScore


class PersonaParamMapper:
    """模型参数映射器。

    映射公式：
    - temperature = 0.3 + warmth * 0.4  (0.3-0.7)
    - max_tokens = int(300 + detail * 700)  (300-1000)
    - top_p = 0.9 - structure * 0.2  (0.7-0.9)
    - frequency_penalty = proactivity * 0.3  (0-0.3)
    - presence_penalty = 0  (固定)
    """

    def map(self, axes: PersonaAxes, rapport: RapportScore) -> dict[str, float | int]:
        """映射 persona 参数到 LLM 推理参数。

        Args:
            axes: 四轴风格参数
            rapport: 关系深度（预留，当前未使用）

        Returns:
            dict: LLM 推理参数
        """
        return {
            "temperature": 0.3 + axes.warmth * 0.4,
            "max_tokens": int(300 + axes.detail * 700),
            "top_p": 0.9 - axes.structure * 0.2,
            "frequency_penalty": axes.proactivity * 0.3,
            "presence_penalty": 0,
        }
