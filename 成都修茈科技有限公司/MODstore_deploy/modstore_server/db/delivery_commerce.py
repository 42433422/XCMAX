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


class AssetInstallCommand(Base):
    """Durable paid-asset delivery command consumed by an authenticated desktop.

    ``installation_id='*'`` means the first desktop for the owning account may
    claim the command.  Once claimed, the command is bound to that installation
    so a second device cannot install it by replaying the command id.
    """

    __tablename__ = "asset_install_commands"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_asset_install_command_idempotency"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    purchase_id = Column(Integer, ForeignKey("purchases.id"), nullable=False, index=True)
    catalog_id = Column(Integer, ForeignKey("catalog_items.id"), nullable=False, index=True)
    installation_id = Column(String(64), default="*", nullable=False, index=True)
    idempotency_key = Column(String(192), nullable=False, index=True)
    source = Column(String(32), default="user_click", nullable=False, index=True)
    source_event_id = Column(String(192), default="", nullable=False, index=True)
    status = Column(String(32), default="pending", nullable=False, index=True)
    attempt_count = Column(Integer, default=0, nullable=False)
    result_json = Column(Text, default="{}", nullable=False)
    error = Column(Text, default="", nullable=False)
    claimed_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False, index=True)
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
