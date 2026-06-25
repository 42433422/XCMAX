"""会议纪要 SSOT 表：一段会议转写 → 三级派生（剧本式 / 架构图式 / 说人话）。

单一真相链：raw_transcript（真相源）→ level1_script → level2_architecture → level3_plain。
下游永远只读上游产物，``source_hash`` 用于检测原文变更、判定下游是否陈旧。
业务模型 → 继承 ``TenantScopedMixin`` 自动多租户隔离（tenant_id 由 before_flush 打标）。
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import IntegerPrimaryKeyMixin, TenantScopedMixin, TimestampMixin

# 状态机：pending（已建未跑）→ generating（派生中）→ completed / degraded（LLM 不可用）/ failed
MEETING_STATUS_PENDING = "pending"
MEETING_STATUS_GENERATING = "generating"
MEETING_STATUS_COMPLETED = "completed"
MEETING_STATUS_DEGRADED = "degraded"
MEETING_STATUS_FAILED = "failed"


class MeetingMinute(IntegerPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    __tablename__ = "meeting_minutes"
    __table_args__ = (Index("ix_meeting_minutes_user_status", "user_id", "status"),)

    title: Mapped[Optional[str]] = mapped_column(String(256))
    user_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)

    # 真相源：录音转写后的原文
    raw_transcript: Mapped[str] = mapped_column(Text, nullable=False)
    # sha256(raw_transcript)：原文指纹，下游陈旧检测
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # 三级派生产物（可空：尚未生成 / 降级时为空）
    level1_script: Mapped[Optional[str]] = mapped_column(Text)  # 剧本式实录（派生自 raw）
    level2_architecture: Mapped[Optional[str]] = mapped_column(Text)  # 架构图式总结（派生自 L1）
    level3_plain: Mapped[Optional[str]] = mapped_column(Text)  # 说人话（派生自 L2）

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=MEETING_STATUS_PENDING, index=True
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text)

    # tenant_id 由 TenantScopedMixin 提供；created_at / updated_at 由 TimestampMixin 提供。

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "user_id": self.user_id,
            "raw_transcript": self.raw_transcript,
            "source_hash": self.source_hash,
            "level1_script": self.level1_script,
            "level2_architecture": self.level2_architecture,
            "level3_plain": self.level3_plain,
            "status": self.status,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def is_stale(self) -> bool:
        """下游产物是否陈旧：原文指纹与当前 raw 不一致。"""
        from app.services.meeting_minutes.pipeline import compute_source_hash

        return self.source_hash != compute_source_hash(self.raw_transcript or "")
