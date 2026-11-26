"""本机文件授权、索引状态与账号隔离的代码修改提案。

授权按 ``tenant_id + owner_user_id`` 隔离：只有授权目录内的文件会被读取，
撤销后立即失效；索引记录逐文件保存指纹，用于增量同步与删除清理。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.db_base import Base
from app.db.mixins import TenantScopedMixin, TimestampMixin


class CodeEditProposal(Base):
    """Immutable proposal; a committed claim fences uncertain filesystem writes."""

    __tablename__ = "code_edit_proposals"

    edit_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    scope_json: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")


class LocalFileGrant(TimestampMixin, TenantScopedMixin, Base):
    """用户对本机目录的只读授权。"""

    __tablename__ = "local_file_grants"
    __table_args__ = (
        Index("ix_local_file_grants_owner", "tenant_id", "owner_user_id"),
        UniqueConstraint(
            "tenant_id", "owner_user_id", "root_path", name="uq_local_file_grant_root"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="folder")
    root_path: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    authorized_via: Mapped[str] = mapped_column(String(32), nullable=False, default="desktop")
    last_scan_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    scan_status: Mapped[str] = mapped_column(String(24), nullable=False, default="idle")
    scan_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    indexed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class LocalFileDocument(TimestampMixin, TenantScopedMixin, Base):
    """授权目录内已处理文件的索引指纹。"""

    __tablename__ = "local_file_documents"
    __table_args__ = (
        UniqueConstraint("grant_id", "path", name="uq_local_file_document_path"),
        Index("ix_local_file_documents_grant_status", "grant_id", "status"),
        Index("ix_local_file_documents_document_id", "document_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    grant_id: Mapped[int] = mapped_column(
        ForeignKey("local_file_grants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mtime_ns: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    document_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    dataset_id: Mapped[str] = mapped_column(String(64), nullable=False, default="local-files")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="indexed")
    last_indexed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
