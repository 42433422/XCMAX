from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class ShipmentItem(BaseModel):
    product_id: int
    quantity: int = Field(..., gt=0)
    product_name: Optional[str] = None
    unit_price: Optional[float] = None
    amount: Optional[float] = None


class ShipmentGenerateRequest(BaseModel):
    customer_name: Optional[str] = None
    items: List[ShipmentItem] = Field(default_factory=list)
    notes: Optional[str] = None


class ShipmentPrintRequest(BaseModel):
    shipment_id: int
    printer_name: Optional[str] = None
    copies: int = Field(default=1, ge=1, le=10)
