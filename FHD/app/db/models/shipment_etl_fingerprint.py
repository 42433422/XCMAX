"""送货单 ETL 导入指纹（租户级唯一，防重复建单）。"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import IntegerPrimaryKeyMixin, TimestampMixin


class ShipmentEtlImportFingerprint(IntegerPrimaryKeyMixin, TimestampMixin, Base):
    """ETL 幂等指纹表。

    ``tenant_key`` + ``fingerprint`` 唯一：同一租户同一内容单据不可重复入库。
    tenant_key 形如 ``tenant:12`` / ``tenant:local``，兼容尚未注入 tenant_id 的桌面模式。
    """

    __tablename__ = "shipment_etl_import_fingerprints"
    __table_args__ = (
        UniqueConstraint("tenant_key", "fingerprint", name="uq_shipment_etl_tenant_fingerprint"),
    )

    tenant_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    shipment_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    unit_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    order_number: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    file_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_kind: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    meta_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
