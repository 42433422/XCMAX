"""用户身份、钱包、经验流水。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)

from modstore_server.db.base import Base


class VerificationCode(Base):
    __tablename__ = "verification_codes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(128), nullable=False, index=True)
    code = Column(String(8), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    email = Column(String(128), unique=True, nullable=True)
    phone = Column(String(32), unique=True, nullable=True, index=True)
    password_hash = Column(String(256), nullable=False)
    is_admin = Column(Boolean, default=False)
    is_enterprise = Column(Boolean, default=False, nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    default_llm_json = Column(Text, default="")
    experience = Column(Integer, default=0, nullable=False)


class Wallet(Base):
    __tablename__ = "wallets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    balance = Column(Numeric(12, 2), default=0.0)
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


class LandingContactSubmission(Base):
    """官网 / 落地页公开联系表单（无登录）。"""

    __tablename__ = "landing_contact_submissions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    email = Column(String(256), nullable=False, index=True)
    phone = Column(String(64), default="")
    company = Column(String(256), default="")
    message = Column(Text, default="")
    source = Column(String(64), default="home", index=True)
    meta_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class AccountExperienceLedger(Base):
    """账号经验流水：以 (source_type, source_order_id) 唯一标识。"""

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
