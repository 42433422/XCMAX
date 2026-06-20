"""Persona 值对象。"""

from __future__ import annotations

from dataclasses import dataclass


def _clamp01(value: float) -> float:
    """将值限制在 [0, 1] 区间。"""
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


@dataclass(frozen=True)
class PersonaAxes:
    """四轴风格参数（MBTI 映射业务四轴）。

    - warmth: 亲切度（T/F）0=就事论事 / 1=有温度
    - detail: 详细度（S/N）0=概括方向 / 1=具体步骤
    - proactivity: 主动度（E/I）0=问什么答什么 / 1=主动建议
    - structure: 结构度（J/P）0=灵活对话 / 1=结构化清单
    """

    warmth: float = 0.5
    detail: float = 0.5
    proactivity: float = 0.5
    structure: float = 0.5

    def __post_init__(self):
        for name in ("warmth", "detail", "proactivity", "structure"):
            value = getattr(self, name)
            if value is None:
                raise ValueError(f"{name} 不能为 None")
            if not isinstance(value, (int, float)):
                raise ValueError(f"{name} 必须是数值，实际: {type(value)}")
            if value < 0.0 or value > 1.0:
                raise ValueError(f"{name} 必须在 [0, 1] 区间，实际: {value}")

    def to_dict(self) -> dict[str, float]:
        return {
            "warmth": self.warmth,
            "detail": self.detail,
            "proactivity": self.proactivity,
            "structure": self.structure,
        }

    @classmethod
    def from_dict(cls, d: dict[str, float]) -> PersonaAxes:
        return cls(
            warmth=d["warmth"],
            detail=d["detail"],
            proactivity=d["proactivity"],
            structure=d["structure"],
        )

    def clamp(self, **offsets: float) -> PersonaAxes:
        """对指定轴施加偏移并 clamp 到 [0,1]，返回新实例。"""
        return PersonaAxes(
            warmth=_clamp01(self.warmth + offsets.get("warmth_offset", 0.0)),
            detail=_clamp01(self.detail + offsets.get("detail_offset", 0.0)),
            proactivity=_clamp01(self.proactivity + offsets.get("proactivity_offset", 0.0)),
            structure=_clamp01(self.structure + offsets.get("structure_offset", 0.0)),
        )


@dataclass(frozen=True)
class PersonaIdentity:
    """身份值对象。"""

    name: str
    brief: str
    business_domain: str
    industry: str

    def __post_init__(self):
        if not self.name or not self.name.strip():
            raise ValueError("name 不能为空")
        if not self.business_domain or not self.business_domain.strip():
            raise ValueError("business_domain 不能为空")

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "brief": self.brief,
            "business_domain": self.business_domain,
            "industry": self.industry,
        }

    @classmethod
    def from_dict(cls, d: dict[str, str]) -> PersonaIdentity:
        return cls(
            name=d["name"],
            brief=d.get("brief", ""),
            business_domain=d["business_domain"],
            industry=d.get("industry", ""),
        )


@dataclass(frozen=True)
class RapportScore:
    """关系深度值对象（0.0 陌生 ~ 1.0 忠诚）。"""

    score: float = 0.3  # 冷启动友好默认
    interaction_count: int = 0
    business_depth: float = 0.0
    emotion_signal_count: int = 0

    def __post_init__(self):
        if self.score < 0.0 or self.score > 1.0:
            raise ValueError(f"score 必须在 [0, 1] 区间，实际: {self.score}")
        if self.business_depth < 0.0 or self.business_depth > 1.0:
            raise ValueError(f"business_depth 必须在 [0, 1] 区间，实际: {self.business_depth}")
        if self.interaction_count < 0:
            raise ValueError(f"interaction_count 不能为负，实际: {self.interaction_count}")
        if self.emotion_signal_count < 0:
            raise ValueError(f"emotion_signal_count 不能为负，实际: {self.emotion_signal_count}")

    def is_loyal(self) -> bool:
        """是否达到忠诚阶段（score >= 0.7）。"""
        return self.score >= 0.7

    def is_stranger(self) -> bool:
        """是否处于陌生阶段（score < 0.3）。"""
        return self.score < 0.3

    def to_dict(self) -> dict[str, float | int]:
        return {
            "score": self.score,
            "interaction_count": self.interaction_count,
            "business_depth": self.business_depth,
            "emotion_signal_count": self.emotion_signal_count,
        }

    @classmethod
    def from_dict(cls, d: dict[str, float | int]) -> RapportScore:
        return cls(
            score=float(d.get("score", 0.3)),
            interaction_count=int(d.get("interaction_count", 0)),
            business_depth=float(d.get("business_depth", 0.0)),
            emotion_signal_count=int(d.get("emotion_signal_count", 0)),
        )
