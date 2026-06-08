"""发货相关 Pydantic 模型（供测试与后续路由校验复用）。"""

from app.fastapi_routes.shipment.schemas import (
    ShipmentGenerateRequest,
    ShipmentItem,
    ShipmentPrintRequest,
)

__all__ = [
    "ShipmentGenerateRequest",
    "ShipmentItem",
    "ShipmentPrintRequest",
]
