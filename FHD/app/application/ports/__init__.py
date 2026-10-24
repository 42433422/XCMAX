"""Application-layer re-exports of domain ports (compatibility).

Canonical definitions live under ``app.domain.<ctx>.ports``.
This package must not grow new port modules (structure gate G5).
"""

from __future__ import annotations

from app.domain.excel.ports import ExtractLogStorePort as ExtractLogStoreChannel
from app.domain.excel.ports import FileAnalysisPort as FileAnalysisChannel
from app.domain.excel.ports import VectorStorePort as VectorStoreChannel
from app.domain.ports.embedder import EmbedderPort as EmbedderChannel
from app.domain.product.ports import MaterialRepository as MaterialChannel
from app.domain.product.ports import ProductRepository as ProductChannel
from app.domain.shipment.ports import PurchaseUnitQueryPort as PurchaseUnitQueryChannel
from app.domain.shipment.ports import (
    ShipmentDocumentGeneratorPort as ShipmentDocumentGeneratorChannel,
)
from app.domain.shipment.ports import (
    ShipmentRecordCommandPort as ShipmentRecordCommandChannel,
)
from app.domain.shipment.ports import (
    ShipmentRecordQueryPort as ShipmentRecordQueryChannel,
)
from app.domain.shipment.ports import (
    ShipmentRecordStorePort as ShipmentRecordStoreChannel,
)
from app.domain.shipment.ports import ShipmentRepository as ShipmentChannel
from app.domain.template.ports import TemplateStorePort as TemplateStoreChannel

MaterialRepository = MaterialChannel
ProductRepository = ProductChannel
ShipmentRepository = ShipmentChannel
ShipmentDocumentGeneratorPort = ShipmentDocumentGeneratorChannel
ShipmentRecordCommandPort = ShipmentRecordCommandChannel
ShipmentRecordQueryPort = ShipmentRecordQueryChannel
ShipmentRecordStorePort = ShipmentRecordStoreChannel
PurchaseUnitQueryPort = PurchaseUnitQueryChannel
TemplateStorePort = TemplateStoreChannel
ExtractLogStorePort = ExtractLogStoreChannel
FileAnalysisPort = FileAnalysisChannel
EmbedderPort = EmbedderChannel
VectorStorePort = VectorStoreChannel

__all__ = [
    "MaterialChannel",
    "ProductChannel",
    "ShipmentChannel",
    "ShipmentDocumentGeneratorChannel",
    "ShipmentRecordCommandChannel",
    "ShipmentRecordQueryChannel",
    "ShipmentRecordStoreChannel",
    "PurchaseUnitQueryChannel",
    "TemplateStoreChannel",
    "ExtractLogStoreChannel",
    "FileAnalysisChannel",
    "EmbedderChannel",
    "VectorStoreChannel",
    "MaterialRepository",
    "ProductRepository",
    "ShipmentRepository",
    "ShipmentDocumentGeneratorPort",
    "ShipmentRecordCommandPort",
    "ShipmentRecordQueryPort",
    "ShipmentRecordStorePort",
    "PurchaseUnitQueryPort",
    "TemplateStorePort",
    "ExtractLogStorePort",
    "FileAnalysisPort",
    "EmbedderPort",
    "VectorStorePort",
]
