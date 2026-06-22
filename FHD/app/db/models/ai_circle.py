"""Persistent AI circle posts, reactions, and comments."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class AiCirclePost(Base):
    __tablename__ = "ai_circle_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    author_kind: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    author_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    employee_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    author_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    author_avatar: Mapped[str | None] = mapped_column(Text, nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(48), nullable=False, default="manual")
    source_ref: Mapped[str | None] = mapped_column(String(160), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp(), index=True
    )


class AiCircleReaction(Base):
    __tablename__ = "ai_circle_reactions"
    __table_args__ = (UniqueConstraint("post_id", "user_id", "kind", name="uq_ai_circle_reaction"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False, default="like")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )


class AiCircleComment(Base):
    __tablename__ = "ai_circle_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    author_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp(), index=True
    )
