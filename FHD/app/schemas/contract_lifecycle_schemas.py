"""合同生命周期 + 电子签 API 请求体。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ContractTransitionBody(BaseModel):
    market_user_id: int
    status: str = Field(..., min_length=1)
    username: str = ""
    note: str = ""


class EsignStartBody(BaseModel):
    market_user_id: int
    party_a: str = Field(..., min_length=1)
    username: str = ""
    party_b: str = ""


class EsignSignCompleteBody(BaseModel):
    token: str = Field(..., min_length=1)
    agree: bool = False
    signer_name: str = ""


class EsignWebhookBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    signed: bool | None = None
    market_user_id: int | None = None
    task_id: str | None = None
