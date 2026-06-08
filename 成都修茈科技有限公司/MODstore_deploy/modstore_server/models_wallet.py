from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)

from .models_base import Base


class Wallet(Base):
    __tablename__ = "wallets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    balance = Column(Numeric(12, 2), default=0)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    amount = Column(Numeric(12, 2), nullable=False)
    txn_type = Column(String(32), nullable=False)
    status = Column(String(16), default="completed")
    description = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class AccountExperienceLedger(Base):
    """账号经验流水：以 (source_type, source_order_id) 唯一标识，保证支付回调/查询补发/退款重试不重复加减。"""

    __tablename__ = "account_experience_ledger"
    __table_args__ = (
        UniqueConstraint("source_type", "source_order_id", name="uq_account_xp_source"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    source_type = Column(String(32), nullable=False, index=True)
    source_order_id = Column(String(64), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    xp_delta = Column(Integer, nullable=False)
    description = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Quota(Base):
    __tablename__ = "quotas"
    __table_args__ = (UniqueConstraint("user_id", "quota_type", name="uq_user_quota_type"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    quota_type = Column(String(64), nullable=False, index=True)
    total = Column(Integer, default=0)
    used = Column(Integer, default=0)
    reset_at = Column(DateTime, nullable=True)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class Entitlement(Base):
    __tablename__ = "entitlements"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    catalog_id = Column(Integer, ForeignKey("catalog_items.id"), nullable=True, index=True)
    entitlement_type = Column(String(32), nullable=False, index=True)
    source_order_id = Column(String(64), default="", index=True)
    metadata_json = Column(Text, default="{}")
    granted_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True, index=True)


class RiskEvent(Base):
    __tablename__ = "risk_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    ip = Column(String(64), default="", index=True)
    event_type = Column(String(64), nullable=False, index=True)
    provider = Column(String(64), default="")
    model = Column(String(256), default="")
    detail = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
