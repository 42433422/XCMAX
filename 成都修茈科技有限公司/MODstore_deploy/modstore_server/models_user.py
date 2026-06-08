from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from .models_base import Base


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
    deleted_at = Column(DateTime, nullable=True, index=True)
    avatar_path = Column(String(512), nullable=False, default="")
    avatar_version = Column(Integer, default=0, nullable=False)


class UserLlmCredential(Base):
    """用户 BYOK：各 provider 的 API Key（Fernet 密文）与可选 base_url。"""

    __tablename__ = "user_llm_credentials"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_user_llm_provider"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    provider = Column(String(32), nullable=False)
    api_key_encrypted = Column(Text, nullable=False, default="")
    base_url_encrypted = Column(Text, nullable=True)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class DeveloperToken(Base):
    """开发者 Personal Access Token (PAT)。

    明文形如 ``pat_<32 字符随机字符串>``，**仅在创建时返回一次**；
    DB 仅保存 sha256 反向哈希用于校验。``token_prefix`` 是头 8 位 (含 ``pat_``)，
    用于 UI 上做 "pat_abcdef…" 这种部分掩码展示。

    ``scopes_json`` 是 JSON 字符串数组，例如 ``["workflow:read", "workflow:execute"]``。
    当前 PR-C 暂不强制路由级 scope 校验，由 PR-D / 后续逐步落地，
    避免一次改动击穿太多现有接口。
    """

    __tablename__ = "developer_tokens"
    __table_args__ = (UniqueConstraint("token_hash", name="uq_developer_token_hash"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(128), nullable=False, default="")
    token_prefix = Column(String(16), nullable=False, default="")
    token_hash = Column(String(128), nullable=False, index=True)
    scopes_json = Column(Text, default="[]")
    expires_at = Column(DateTime, nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class DeveloperKeyExportEvent(Base):
    """开发者密钥导出/桌面投递审计（不落密钥明文）。"""

    __tablename__ = "developer_key_export_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    client_ip = Column(String(64), nullable=False, default="")
    user_agent = Column(String(512), nullable=False, default="")
    action = Column(String(64), nullable=False, default="")
    token_ids_json = Column(Text, nullable=False, default="[]")
    token_count = Column(Integer, nullable=False, default=0)
    success = Column(Boolean, nullable=False, default=False)
    detail = Column(String(512), nullable=False, default="")
    algorithm = Column(String(64), nullable=False, default="")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    kind = Column("type", String(32), nullable=False)
    title = Column(String(256), nullable=False)
    content = Column(Text, nullable=False)
    data_json = Column(Text, default="{}")
    is_read = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


# 与 modstore_server.db.identity.LandingContactSubmission 同一表；请从 modstore_server.models 导入。
from modstore_server.db.identity import LandingContactSubmission  # noqa: F401


class EmployeeExecutionMetric(Base):
    __tablename__ = "employee_execution_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    employee_id = Column(String(128), nullable=False, index=True)
    task = Column(String(128), default="")
    status = Column(String(32), default="success")
    duration_ms = Column(Float, default=0.0)
    llm_tokens = Column(Integer, default=0)
    error = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
