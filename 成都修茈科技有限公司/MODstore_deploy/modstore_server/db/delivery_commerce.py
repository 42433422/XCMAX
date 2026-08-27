"""客户端更新安装回执与管理端经营操作审计。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from modstore_server.db.base import Base


class UpdateInstallationReceipt(Base):
    __tablename__ = "update_installation_receipts"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_update_install_receipt_idempotency"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    installation_id = Column(String(64), nullable=False, index=True)
    idempotency_key = Column(String(192), nullable=False, index=True)
    channel = Column(String(32), default="stable", nullable=False, index=True)
    platform = Column(String(32), default="", nullable=False)
    target_version = Column(String(64), default="", nullable=False, index=True)
    target_build_sha = Column(String(128), default="", nullable=False, index=True)
    installed_version = Column(String(64), default="", nullable=False)
    installed_build_sha = Column(String(128), default="", nullable=False)
    status = Column(String(32), default="installed", nullable=False, index=True)
    error = Column(Text, default="", nullable=False)
    source = Column(String(32), default="desktop_ota", nullable=False)
    reported_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )


class CommerceAdminAction(Base):
    __tablename__ = "commerce_admin_actions"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_commerce_admin_action_idempotency"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    actor_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    action = Column(String(48), nullable=False, index=True)
    aggregate_type = Column(String(48), nullable=False, index=True)
    aggregate_id = Column(String(128), nullable=False, index=True)
    idempotency_key = Column(String(192), nullable=False, index=True)
    status = Column(String(32), default="completed", nullable=False, index=True)
    reason = Column(Text, default="", nullable=False)
    before_json = Column(Text, default="{}", nullable=False)
    after_json = Column(Text, default="{}", nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False, index=True)
