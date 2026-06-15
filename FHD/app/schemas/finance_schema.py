"""财务凭证 Pydantic 模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FinanceTransactionCreate(BaseModel):
    transaction_type: str = Field(..., description="revenue|expense|receivable|payable|receipt|payment|adjustment")
    amount: float = Field(..., description="金额")
    description: str | None = None
    reference_id: str | None = None
    status: str | None = None


class FinanceTransactionUpdate(BaseModel):
    transaction_type: str | None = None
    amount: float | None = None
    description: str | None = None
    reference_id: str | None = None
    status: str | None = None
