"""ButlerUserProfile 数据模型 — 拟人 Persy 系统的持久化层。

存储每个用户的 Butler 个性化人设：
- 身份层：主身份 + 复合身份标签 + 身份亲和度向量
- MBTI 层：4 维倾向分数（E/I、S/N、T/F、J/P）+ 16 型标签 + 置信度
- 元数据：最后推断时间 + 累计互动轮数

四轴参数（亲切度/详细度/主动度/结构度）不存储，运行时从 MBTI 派生。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ButlerUserProfile(Base):
    """Butler 个性化人设档案。每用户一行。"""

    __tablename__ = "butler_user_profiles"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), primary_key=True
    )

    # === 身份层 ===
    identity_primary: Mapped[str] = mapped_column(
        String(32), default="忠诚伙伴", comment="主身份枚举"
    )
    identity_composite: Mapped[str] = mapped_column(
        String(64), default="", comment="复合身份标签（LLM 生成）"
    )
    identity_vector_json: Mapped[str] = mapped_column(
        Text, default="{}", comment="各原子身份亲和度 JSON"
    )

    # === MBTI 层（底层模型，不在 UI 显示）===
    mbti_ei: Mapped[int] = mapped_column(
        Integer, default=65, comment="E/I 轴 0-100，E=100"
    )
    mbti_sn: Mapped[int] = mapped_column(
        Integer, default=60, comment="S/N 轴 0-100，N=100"
    )
    mbti_tf: Mapped[int] = mapped_column(
        Integer, default=70, comment="T/F 轴 0-100，F=100"
    )
    mbti_jp: Mapped[int] = mapped_column(
        Integer, default=40, comment="J/P 轴 0-100，P=100（< 50 = J）"
    )
    mbti_type: Mapped[str] = mapped_column(
        String(4), default="ENFJ", comment="派生 16 型标签"
    )
    mbti_confidence: Mapped[float] = mapped_column(
        Float, default=0.3, comment="推断置信度 0-1"
    )

    # === 元数据 ===
    last_inferred_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, comment="最后推断时间"
    )
    interaction_count: Mapped[int] = mapped_column(
        Integer, default=0, comment="累计互动轮数"
    )

    def to_public_dict(self) -> dict:
        """返回 UI 可见的字典（不含 MBTI 原始分数，含派生四轴）。"""
        from app.application.butler_identity_catalog import derive_four_axes

        axes = derive_four_axes(self.mbti_ei, self.mbti_sn, self.mbti_tf, self.mbti_jp)
        return {
            "user_id": self.user_id,
            "identity_primary": self.identity_primary,
            "identity_composite": self.identity_composite or self.identity_primary,
            "four_axes": axes,
            "mbti_type": self.mbti_type,
            "mbti_confidence": self.mbti_confidence,
            "interaction_count": self.interaction_count,
            "last_inferred_at": self.last_inferred_at.isoformat() if self.last_inferred_at else None,
        }

    def to_internal_dict(self) -> dict:
        """返回完整字典（含 MBTI 原始分数，供推断引擎用）。"""
        return {
            "user_id": self.user_id,
            "identity_primary": self.identity_primary,
            "identity_composite": self.identity_composite,
            "identity_vector_json": self.identity_vector_json,
            "mbti_ei": self.mbti_ei,
            "mbti_sn": self.mbti_sn,
            "mbti_tf": self.mbti_tf,
            "mbti_jp": self.mbti_jp,
            "mbti_type": self.mbti_type,
            "mbti_confidence": self.mbti_confidence,
            "last_inferred_at": self.last_inferred_at.isoformat() if self.last_inferred_at else None,
            "interaction_count": self.interaction_count,
        }
