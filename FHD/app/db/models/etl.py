"""通用 ETL V1 持久化模型。

所有用户可见资源同时按 ``tenant_id`` 与 ``owner_user_id`` 隔离。模板版本与
运行逐行快照只追加、不原地覆盖，为预演、审计与撤销提供确定性依据。
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

from app.db.base import Base
from app.db.mixins import TenantScopedMixin, TimestampMixin


class EtlUpload(TimestampMixin, TenantScopedMixin, Base):
    __tablename__ = "etl_uploads"
    __table_args__ = (
        Index("ix_etl_upload_owner", "tenant_id", "owner_user_id"),
        Index("ix_etl_upload_sha256", "tenant_id", "owner_user_id", "sha256"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    suffix: Mapped[str] = mapped_column(String(16), nullable=False)
    content_type: Mapped[Optional[str]] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class EtlTemplate(TimestampMixin, TenantScopedMixin, Base):
    __tablename__ = "etl_templates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "owner_user_id", "name", name="uq_etl_template_owner_name"),
        Index("ix_etl_template_owner", "tenant_id", "owner_user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: Mapped[Optional[str]] = mapped_column(Text)


class EtlTemplateVersion(TenantScopedMixin, Base):
    __tablename__ = "etl_template_versions"
    __table_args__ = (
        UniqueConstraint("template_id", "version", name="uq_etl_template_version"),
        Index("ix_etl_template_version_owner", "tenant_id", "owner_user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    template_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("etl_templates.id"), nullable=False, index=True
    )
    owner_user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_features_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    field_mappings_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    validation_rules_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    match_keys_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    allowed_update_fields_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    action_rules_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )


class EtlRun(TimestampMixin, TenantScopedMixin, Base):
    __tablename__ = "etl_runs"
    __table_args__ = (
        Index("ix_etl_run_owner_created", "tenant_id", "owner_user_id", "created_at"),
        Index("ix_etl_run_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    upload_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("etl_uploads.id"), nullable=False, index=True
    )
    template_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("etl_templates.id"), index=True
    )
    template_version_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("etl_template_versions.id"), index=True
    )
    target_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_features_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    draft_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    summary_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    receipt_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    error_code: Mapped[Optional[str]] = mapped_column(String(64))
    error_message: Mapped[Optional[str]] = mapped_column(String(500))
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    new_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    update_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skip_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    executed_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reversible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rollback_status: Mapped[Optional[str]] = mapped_column(String(32))
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    rolled_back_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class EtlRunRow(TenantScopedMixin, Base):
    __tablename__ = "etl_run_rows"
    __table_args__ = (
        UniqueConstraint("run_id", "source_sheet", "source_row", name="uq_etl_run_source_row"),
        Index("ix_etl_run_rows_owner", "tenant_id", "owner_user_id"),
        Index("ix_etl_run_rows_run_action", "run_id", "final_action"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("etl_runs.id"), nullable=False, index=True
    )
    owner_user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    source_sheet: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    source_row: Mapped[int] = mapped_column(Integer, nullable=False)
    source_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    normalized_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    provenance_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    validation_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    llm_suggestion_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    suggested_action: Mapped[str] = mapped_column(String(16), nullable=False, default="skip")
    final_action: Mapped[str] = mapped_column(String(16), nullable=False, default="skip")
    action_overridden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    match_ref: Mapped[Optional[str]] = mapped_column(String(128))
    before_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    after_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    execution_status: Mapped[Optional[str]] = mapped_column(String(32))
    execution_error_code: Mapped[Optional[str]] = mapped_column(String(64))
    execution_error_message: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class EtlTargetConfig(TimestampMixin, TenantScopedMixin, Base):
    __tablename__ = "etl_target_configs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "owner_user_id", "name", name="uq_etl_target_config_owner_name"
        ),
        Index("ix_etl_target_config_owner", "tenant_id", "owner_user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False, default="webhook")
    endpoint_url: Mapped[str] = mapped_column(Text, nullable=False)
    headers_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    secret_ref: Mapped[Optional[str]] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
