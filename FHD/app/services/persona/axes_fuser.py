"""三层融合器：L1 + L2 + L3 加权融合 + rapport 软偏移。"""

from __future__ import annotations

from app.domain.persona.value_objects import PersonaAxes, RapportScore


class AxesFuser:
    """三层推断结果融合器。

    融合公式：final = w1*L1 + w2*L2 + w3*L3
    权重根据可用层级动态调整：
    - 仅 L1：w1=1.0
    - L1+L2：w1=0.5, w2=0.5
    - L1+L2+L3：w1=0.4, w2=0.3, w3=0.3

    软偏移：rapport 高时偏移四轴基线，但用户信号强时不偏移。
    """

    WEIGHT_L1_ONLY = 1.0
    WEIGHT_L1_WITH_L2 = 0.5
    WEIGHT_L2_WITH_L1 = 0.5
    WEIGHT_L1_FULL = 0.4
    WEIGHT_L2_FULL = 0.3
    WEIGHT_L3_FULL = 0.3

    SIGNAL_STRENGTH_THRESHOLD = 0.7  # 用户信号强度高于此值时锁定，不偏移

    def fuse(
        self,
        l1: PersonaAxes,
        l2: PersonaAxes | None,
        l3: PersonaAxes | None,
        rapport: RapportScore,
        signal_strength: float = 0.0,
    ) -> PersonaAxes:
        """融合三层推断结果。

        Args:
            l1: L1 规则层结果（必有）
            l2: L2 embedding 层结果（可空）
            l3: L3 LLM 层结果（可空）
            rapport: 关系深度
            signal_strength: 用户信号强度（0-1），高时锁定不偏移

        Returns:
            PersonaAxes: 融合后的四轴值
        """
        if l2 is None and l3 is None:
            base = l1
        elif l2 is not None and l3 is None:
            base = PersonaAxes(
                warmth=self.WEIGHT_L1_WITH_L2 * l1.warmth + self.WEIGHT_L2_WITH_L1 * l2.warmth,
                detail=self.WEIGHT_L1_WITH_L2 * l1.detail + self.WEIGHT_L2_WITH_L1 * l2.detail,
                proactivity=self.WEIGHT_L1_WITH_L2 * l1.proactivity
                + self.WEIGHT_L2_WITH_L1 * l2.proactivity,
                structure=self.WEIGHT_L1_WITH_L2 * l1.structure
                + self.WEIGHT_L2_WITH_L1 * l2.structure,
            )
        elif l2 is not None and l3 is not None:
            base = PersonaAxes(
                warmth=self.WEIGHT_L1_FULL * l1.warmth
                + self.WEIGHT_L2_FULL * l2.warmth
                + self.WEIGHT_L3_FULL * l3.warmth,
                detail=self.WEIGHT_L1_FULL * l1.detail
                + self.WEIGHT_L2_FULL * l2.detail
                + self.WEIGHT_L3_FULL * l3.detail,
                proactivity=self.WEIGHT_L1_FULL * l1.proactivity
                + self.WEIGHT_L2_FULL * l2.proactivity
                + self.WEIGHT_L3_FULL * l3.proactivity,
                structure=self.WEIGHT_L1_FULL * l1.structure
                + self.WEIGHT_L2_FULL * l2.structure
                + self.WEIGHT_L3_FULL * l3.structure,
            )
        else:
            # l2 is None but l3 is not None: 退化到 L1 only（L3 依赖 L2 提供模式）
            base = l1

        # 软偏移：用户信号弱时才应用 rapport 偏移
        if signal_strength < self.SIGNAL_STRENGTH_THRESHOLD:
            offsets = self._rapport_offsets(rapport)
            return base.clamp(**offsets)
        return base

    def _rapport_offsets(self, rapport: RapportScore) -> dict[str, float]:
        """根据 rapport 计算四轴偏移量。"""
        if rapport.score >= 0.7:
            return {
                "warmth_offset": 0.2,
                "proactivity_offset": 0.2,
                "detail_offset": 0.1,
            }
        if rapport.score >= 0.4:
            return {
                "warmth_offset": 0.1,
                "proactivity_offset": 0.1,
            }
        return {}
