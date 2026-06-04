"""按当前行业解析发货单文档生成器（配置 → 代码注册）。"""
from __future__ import annotations

from app.application.ports.shipment_document_generator import ShipmentDocumentGeneratorPort
from app.domain.value_objects_industry import get_current_industry
from app.infrastructure.documents.shipment_document_generator_impl import (
    LegacyShipmentDocumentGenerator,
)
from app.infrastructure.documents.shipment_document_generator_impl_paint import (
    PaintShipmentDocumentGenerator,
)
from app.infrastructure.documents.shipment_document_generator_impl_poultry import (
    PoultryShipmentDocumentGenerator,
)

_PAINT_IDS = frozenset({"paint", "涂料", "coating"})
_POULTRY_IDS = frozenset({"poultry", "烤禽", "roast_poultry"})


def resolve_shipment_document_generator() -> ShipmentDocumentGeneratorPort:
    industry = (get_current_industry() or "").strip().lower()
    if industry in _PAINT_IDS:
        return PaintShipmentDocumentGenerator()
    if industry in _POULTRY_IDS:
        return PoultryShipmentDocumentGenerator()
    return LegacyShipmentDocumentGenerator()
