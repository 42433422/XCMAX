"""合同生命周期 API 请求体。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ContractTransitionBody(BaseModel):
    market_user_id: int = Field(..., ge=1)
    status: str = Field(..., min_length=1)
    username: str = ""
    note: str = ""


class EsignStartBody(BaseModel):
    market_user_id: int = Field(..., ge=1)
    username: str = ""
    party_a: str = ""
    party_b: str = ""


class EsignWebhookBody(BaseModel):
    model_config = {"extra": "allow"}

    event: str = ""
    contract_id: str = ""
    status: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class EsignSignCompleteBody(BaseModel):
    token: str = Field(..., min_length=8)
    signer_name: str = ""
    agree: bool = False
