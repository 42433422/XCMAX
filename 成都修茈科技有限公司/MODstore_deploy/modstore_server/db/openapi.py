"""第三方 OpenAPI 连接器与调用审计。"""

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

from modstore_server.db.base import Base


class OpenApiConnector(Base):
    __tablename__ = "openapi_connectors"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_openapi_connector_name"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, default="")
    base_url = Column(String(512), default="")
    spec_hash = Column(String(64), default="", index=True)
    spec_version = Column(String(32), default="")
    title = Column(String(256), default="")
    status = Column(String(32), default="ready", index=True)
    generated_version = Column(Integer, default=0)
    operation_count = Column(Integer, default=0)
    last_error = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class OpenApiOperation(Base):
    __tablename__ = "openapi_operations"
    __table_args__ = (
        UniqueConstraint("connector_id", "operation_id", name="uq_openapi_operation_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    connector_id = Column(Integer, ForeignKey("openapi_connectors.id"), nullable=False, index=True)
    operation_id = Column(String(128), nullable=False)
    method = Column(String(16), nullable=False)
    path = Column(String(512), nullable=False)
    summary = Column(String(512), default="")
    tags = Column(Text, default="[]")
    request_schema = Column(Text, default="{}")
    response_schema = Column(Text, default="{}")
    generated_symbol = Column(String(128), default="")
    enabled = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class OpenApiCredential(Base):
    __tablename__ = "openapi_credentials"
    __table_args__ = (
        UniqueConstraint("user_id", "connector_id", name="uq_openapi_credential_owner"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    connector_id = Column(Integer, ForeignKey("openapi_connectors.id"), nullable=False, index=True)
    auth_type = Column(String(32), nullable=False, default="none")
    config_encrypted = Column(Text, nullable=False, default="")
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class OpenApiCallLog(Base):
    __tablename__ = "openapi_call_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    connector_id = Column(Integer, ForeignKey("openapi_connectors.id"), nullable=False, index=True)
    operation_id = Column(String(128), nullable=False, index=True)
    method = Column(String(16), default="")
    path = Column(String(512), default="")
    status_code = Column(Integer, nullable=True)
    duration_ms = Column(Float, default=0.0)
    request_summary = Column(Text, default="")
    response_summary = Column(Text, default="")
    error = Column(Text, default="")
    source = Column(String(32), default="manual", index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
