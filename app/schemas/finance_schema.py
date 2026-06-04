"""Finance Pydantic schemas."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class FinanceTransactionCreate(BaseModel):
    transaction_type: str = Field(..., min_length=1)
    amount: Decimal | float
    currency: str = "CNY"
    reference_type: str | None = None
    reference_id: int | None = None
    description: str | None = None
    transaction_date: datetime | str | None = None
    due_date: datetime | str | None = None
    status: str = "pending"
    counterparty_name: str | None = None
    counterparty_id: int | None = None
    created_by: str | None = None


class FinanceTransactionUpdate(BaseModel):
    transaction_type: str | None = None
    amount: Decimal | float | None = None
    currency: str | None = None
    reference_type: str | None = None
    reference_id: int | None = None
    description: str | None = None
    transaction_date: datetime | str | None = None
    due_date: datetime | str | None = None
    status: str | None = None
    counterparty_name: str | None = None
    counterparty_id: int | None = None
