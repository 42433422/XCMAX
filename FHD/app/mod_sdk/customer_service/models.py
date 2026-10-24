"""Validated request bodies shared by the customer-service Mod and its route handlers."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class DemandIntakeBody(BaseModel):
    brief: str = Field(..., min_length=1, max_length=4000, description="业务背景/客户画像")
    client_name: str = Field(default="", max_length=128)
    form_url: str = Field(default="", max_length=512)
    channel: str = Field(default="wechat", max_length=32)
    use_llm: bool = False
    market_user_id: Optional[int] = Field(default=None, description="关联企业客户 ID")


class DemandFormSyncBody(BaseModel):
    market_user_id: int = Field(..., gt=0)
    landing_contact_id: Optional[int] = None
    name: str = Field(default="", max_length=128)
    email: str = Field(default="", max_length=256)
    phone: str = Field(default="", max_length=64)
    company: str = Field(default="", max_length=256)
    message: str = Field(default="", max_length=8000)
    desktop_os: str = Field(default="", max_length=16)
    need_mobile: bool = Field(default=True)
    submitted_at: str = Field(default="", max_length=64)
    campaign: str = Field(default="", max_length=128)
    medium: str = Field(default="", max_length=64)
    content: str = Field(default="", max_length=128)


class LandingFunnelSyncBody(BaseModel):
    market_user_id: Optional[int] = Field(default=None, description="无账户时仅写 CRM 线索")
    landing_contact_id: Optional[int] = None
    audit_code: str = Field(default="", max_length=32)
    name: str = Field(default="", max_length=128)
    email: str = Field(default="", max_length=256)
    phone: str = Field(default="", max_length=64)
    company: str = Field(default="", max_length=256)
    message: str = Field(default="", max_length=8000)
    desktop_os: str = Field(default="", max_length=16)
    need_mobile: bool = Field(default=True)
    submitted_at: str = Field(default="", max_length=64)
    intake_source: str = Field(default="", max_length=64)
    campaign: str = Field(default="", max_length=128)
    medium: str = Field(default="", max_length=64)
    content: str = Field(default="", max_length=128)


class ChangeRequestCreateBody(BaseModel):
    market_user_id: int = Field(..., gt=0)
    username: str = Field(default="", max_length=128)
    change_type: str = Field(..., max_length=32)
    title: str = Field(..., min_length=1, max_length=256)
    description: str = Field(default="", max_length=8000)
    priority: str = Field(default="normal", max_length=16)
    source: str = Field(default="enterprise_portal", max_length=64)


class ChangeRequestStatusBody(BaseModel):
    market_user_id: int = Field(..., gt=0)
    username: str = Field(default="", max_length=128)
    status: str = Field(..., max_length=32)
    admin_note: str = Field(default="", max_length=2000)


class ChangeRequestNotifyBody(BaseModel):
    market_user_id: int = Field(..., gt=0)
    username: str = Field(default="", max_length=128)
    contact_name: str = Field(default="", max_length=256)


class DemandFormManualBody(BaseModel):
    market_user_id: int = Field(..., gt=0)
    username: str = Field(default="", max_length=128)
    name: str = Field(default="", max_length=128)
    email: str = Field(default="", max_length=256)
    phone: str = Field(default="", max_length=64)
    company: str = Field(default="", max_length=256)
    message: str = Field(..., min_length=1, max_length=8000)
    desktop_os: str = Field(default="", max_length=16)
    need_mobile: bool = Field(default=True)


class DemandFormRedeemCodeBody(BaseModel):
    market_user_id: int = Field(..., gt=0)
    username: str = Field(default="", max_length=128)
    audit_code: str = Field(..., min_length=4, max_length=32)


class PipelineBody(BaseModel):
    market_user_id: int = Field(..., gt=0)
    username: str = Field(default="", max_length=128)
    stage: Optional[str] = Field(default=None, max_length=32)
    intake_sent: bool = False
    manual: bool = Field(default=True, description="手动改阶段时写入 timeline（source=manual）")
    note: str = Field(default="", max_length=200)
    signoff_id: Optional[int] = Field(default=None, gt=0)
    force: bool = Field(default=False, description="忽略已发送标记（如重发安装包）")


class EnterpriseCredentialsIssueBody(BaseModel):
    market_user_id: int = Field(..., gt=0)
    username: str = Field(default="", max_length=128)
    password: str = Field(default="", max_length=128, description="留空则自动生成临时密码")


class AnalyzePipelineBody(BaseModel):
    market_user_id: int = Field(..., gt=0)
    username: str = Field(default="", max_length=128)
    has_binding: bool = False
    intake_sent: bool = False


class ContractFieldsBody(BaseModel):
    market_user_id: int = Field(..., gt=0)
    username: str = Field(default="", max_length=128)
    values: Dict[str, Any] = Field(default_factory=dict)


class ContractGenerateBody(BaseModel):
    advance_stage: bool = True
    market_user_id: int = Field(..., gt=0)
    username: str = Field(default="", max_length=128)
    values: Dict[str, Any] = Field(default_factory=dict)


class DeliveryPlanBody(BaseModel):
    market_user_id: int = Field(..., gt=0)
    username: str = Field(default="", max_length=128)
    expected_delivery_at: str = Field(default="", max_length=32)
    milestones: list[Dict[str, Any]] = Field(default_factory=list)
    start_delivery: bool = False
    stage: Optional[str] = Field(default=None, max_length=32)


class DeliveryPaymentBody(BaseModel):
    market_user_id: int = Field(..., gt=0)
    username: str = Field(default="", max_length=128)
    force_confirm: bool = False
    payment_reference: str = Field(default="", max_length=200)
    advance_stage: bool = True


class WechatSendBody(BaseModel):
    market_user_id: int = Field(..., gt=0)
    contact_name: str = Field(..., min_length=1, max_length=256)
    message: str = Field(..., min_length=1, max_length=8000)
    username: str = Field(default="", max_length=128)


class ConnectedWelcomeBody(BaseModel):
    market_user_id: int = Field(..., gt=0)
    username: str = Field(default="", max_length=128)
    contact_name: str = Field(default="", max_length=256)
    force: bool = False


class IntakeNoticeBody(BaseModel):
    market_user_id: int = Field(..., gt=0)
    username: str = Field(default="", max_length=128)
    contact_name: str = Field(default="", max_length=256)
    brief: str = Field(default="", max_length=4000)
    force: bool = False
