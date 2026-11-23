"""Durable workspace proposals; ownership is checked against the current session."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.db_base import Base


class CodeEditProposal(Base):
    __tablename__ = "code_edit_proposals"
    __table_args__ = (Index("ix_code_edit_proposals_owner", "owner_user_id", "tenant_id"),)

    edit_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    workspace_root: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    apply_state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
