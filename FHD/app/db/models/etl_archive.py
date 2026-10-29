"""Tenant-scoped archive storage metadata; archived bytes never live in SQL."""

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.db_base import Base
from app.db.mixins import TenantScopedMixin, TimestampMixin


class EtlArchiveQuota(TimestampMixin, TenantScopedMixin, Base):
    __tablename__ = "etl_archive_quotas"
    tenant_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    limit_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reserved_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class EtlArchiveAsset(TimestampMixin, TenantScopedMixin, Base):
    __tablename__ = "etl_archive_assets"
    __table_args__ = (
        Index("ix_etl_archive_owner", "tenant_id", "owner_user_id"),
        UniqueConstraint("tenant_id", "owner_user_id", "request_key", name="uq_etl_archive_request"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    retention_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    request_key: Mapped[str] = mapped_column(String(80), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="active")


class EtlArchiveVersion(TimestampMixin, TenantScopedMixin, Base):
    __tablename__ = "etl_archive_versions"
    __table_args__ = (
        UniqueConstraint("asset_id", "version", name="uq_etl_archive_asset_version"),
        UniqueConstraint("tenant_id", "owner_user_id", "request_key", name="uq_etl_archive_version_request"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("etl_archive_assets.id"), nullable=False)
    owner_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    classification_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    request_key: Mapped[str] = mapped_column(String(80), nullable=False)
