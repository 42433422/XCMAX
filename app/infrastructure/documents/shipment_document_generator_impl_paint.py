"""涂料行业发货单/标签生成实现。"""
from __future__ import annotations

from app.infrastructure.documents.shipment_document_generator_impl import (
    LegacyShipmentDocumentGenerator,
)

INDUSTRY_ID = "paint"


class PaintShipmentDocumentGenerator(LegacyShipmentDocumentGenerator):
    """涂料垂直：继承通用实现，预留行业模板/单位覆写。"""

    industry_id: str = INDUSTRY_ID
