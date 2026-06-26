"""移动端 API 扩展 — Pydantic 请求模型。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DeviceRegisterBody(BaseModel):
    fcm_token: str = Field(..., min_length=8)
    push_provider: str = Field(default="fcm", max_length=16)
    push_token: str = Field(default="", max_length=512)
    product_sku: str = Field(default="personal", max_length=32)
    device_label: str = Field(default="", max_length=200)
    platform: str = Field(default="android", max_length=32)


class PairingExchangeBody(BaseModel):
    nonce: str = Field(default="", max_length=128)
    code: str = Field(default="", max_length=16)


class PairingLookupBody(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)


class PairingIssueBody(BaseModel):
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=5000, ge=1, le=65535)


class RelayDesktopRegisterBody(BaseModel):
    label: str = Field(default="", max_length=200)
    device_id: str = Field(default="", max_length=128)
    relay_base_url: str = Field(default="", max_length=512)
    capabilities: dict[str, Any] = Field(default_factory=dict)


class RelayMobileConfirmBody(BaseModel):
    relay_id: str = Field(..., min_length=8, max_length=80)
    code: str = Field(..., min_length=4, max_length=16)


class RelayMobileConfirmCodeBody(BaseModel):
    code: str = Field(..., min_length=4, max_length=16)


class RelayMobileBindAccountBody(BaseModel):
    relay_id: str = Field(..., min_length=8, max_length=80)


class RelayTaskCreateBody(BaseModel):
    relay_id: str = Field(..., min_length=8, max_length=80)
    kind: str = Field(default="codex.invoke", max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)


class RelayDesktopPollBody(BaseModel):
    relay_id: str = Field(..., min_length=8, max_length=80)
    desktop_token: str = Field(..., min_length=16, max_length=256)
    max_tasks: int = Field(default=5, ge=1, le=20)


class RelayDesktopCompleteBody(BaseModel):
    relay_id: str = Field(..., min_length=8, max_length=80)
    desktop_token: str = Field(..., min_length=16, max_length=256)
    status: str = Field(default="completed", max_length=32)
    result: dict[str, Any] = Field(default_factory=dict)


class CodexSuperEmployeeMobileMessageBody(BaseModel):
    message: str = Field(default="", max_length=4000)
    body: str = Field(default="", max_length=4000)
    context: dict[str, Any] = Field(default_factory=dict)


class ClaudeSuperEmployeeMobileMessageBody(BaseModel):
    message: str = Field(default="", max_length=4000)
    body: str = Field(default="", max_length=4000)
    context: dict[str, Any] = Field(default_factory=dict)


class CursorSuperEmployeeMobileMessageBody(BaseModel):
    message: str = Field(default="", max_length=4000)
    body: str = Field(default="", max_length=4000)
    context: dict[str, Any] = Field(default_factory=dict)


class TraeSuperEmployeeMobileMessageBody(BaseModel):
    message: str = Field(default="", max_length=4000)
    body: str = Field(default="", max_length=4000)
    context: dict[str, Any] = Field(default_factory=dict)


class AiGroupCreateBody(BaseModel):
    name: str = Field(default="", max_length=60)


class AiGroupMemberBody(BaseModel):
    employee_id: str = Field(default="", max_length=120)
    mod_id: str = Field(default="", max_length=120)
    name: str = Field(default="", max_length=60)
    avatar: str = Field(default="", max_length=1024)
    summary: str = Field(default="", max_length=280)


class AiGroupMessageBody(BaseModel):
    message: str = Field(default="", max_length=4000)
    sender_name: str = Field(default="我", max_length=60)
    mentions: list[str] = Field(default_factory=list)
    dispatch: bool = Field(default=False)
    branch_context: str = Field(default="", max_length=180)
    branch: str = Field(default="", max_length=180)
    context: dict[str, Any] = Field(default_factory=dict)


class MobileServiceBridgeRespondBody(BaseModel):
    response: str
    responded_by: str | None = None
    status: str = Field(default="resolved", max_length=32)


class SyncPullBody(BaseModel):
    since_cursor: int = Field(default=0, ge=0)


class SyncPushItem(BaseModel):
    entity_type: str = Field(..., min_length=1, max_length=64)
    entity_id: str = Field(..., min_length=1, max_length=128)
    operation: str = Field(default="update", max_length=32)
    payload: dict[str, Any] = Field(default_factory=dict)


class SyncPushBody(BaseModel):
    items: list[SyncPushItem] = Field(default_factory=list)


class SyncAckBody(BaseModel):
    cursor: int = Field(default=0, ge=0)


class AuthQrConfirmBody(BaseModel):
    qr_id: str = Field(..., min_length=8)
    username: str = Field(default="", max_length=128)
    password: str = Field(default="", max_length=256)
    account_kind: str = Field(default="enterprise", max_length=32)


class OidcExchangeBody(BaseModel):
    code: str = Field(..., min_length=4)
    state: str = Field(..., min_length=8)


class AiCirclePostBody(BaseModel):
    body: str = Field(..., min_length=1, max_length=2000)


class AiCircleCommentBody(BaseModel):
    body: str = Field(..., min_length=1, max_length=500)
