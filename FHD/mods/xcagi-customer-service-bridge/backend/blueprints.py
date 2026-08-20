# ruff: noqa: E402, F401
"""客服业务页桥接 Mod（里程碑 K）— 页面经 Mod 路由，数据 API 仍走宿主/其它 bridge。"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.mod_sdk.errors import BOUNDARY_ERRORS

logger = logging.getLogger(__name__)
CUSTOMER_SERVICE_BRIDGE_MOD_ID = "xcagi-customer-service-bridge"


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


class PassivePollBody(BaseModel):
    market_user_id: int = Field(..., gt=0)
    username: str = Field(default="", max_length=128)
    dry_run: bool = Field(default=True, description="True=只探测不发送")
    auto_reply: bool = Field(default=True)
    max_replies: int = Field(default=0, ge=0, le=5, description="0=按绑定群数每群 1 条")
    use_llm: bool = Field(default=True, description="True=用 LLM 生成回复，失败则回退模板")
    skip_sync: bool = Field(
        default=False,
        description="True=跳过服务端同步（由前端先调 refresh_messages，与数据来源按钮一致）",
    )
    refresh_count_new: int | None = Field(default=None, ge=0)
    refresh_latest_label: str = Field(default="", max_length=32)
    catch_up_latest: bool = Field(
        default=False, description="True=手动被动回复时可补答游标时刻的最新一条他人消息"
    )


class PassiveLoopConfigBody(BaseModel):
    market_user_id: int = Field(..., gt=0)
    username: str = Field(default="", max_length=128)
    poll_enabled: bool = False
    poll_interval_sec: int = Field(default=60, ge=10, le=600)


async def _run_user_cs_employee(payload: Dict[str, Any]) -> Dict[str, Any]:
    """调用 user-customer-service-officer 员工包（mods/_employees）。"""
    from app.mod_sdk.host_services import run_user_cs_employee

    return await run_user_cs_employee(payload)


import sys

from app.mod_sdk.customer_service_bridge_routes_part01 import _register_routes_part01
from app.mod_sdk.customer_service_bridge_routes_part02 import _register_routes_part02
from app.mod_sdk.customer_service_bridge_routes_part03 import _register_routes_part03


def register_fastapi_routes(app, mod_id: str) -> None:
    router = APIRouter(prefix=f"/api/mod/{mod_id}", tags=[f"customer-service-bridge-{mod_id}"])
    _register_routes_part01(router, mod_id, sys.modules[__name__])
    _register_routes_part02(router, mod_id, sys.modules[__name__])
    _register_routes_part03(router, mod_id, sys.modules[__name__])
    app.include_router(router)
    logger.info("xcagi-customer-service-bridge registered: %s", mod_id)


def mod_init(app=None, mod_id: str | None = None) -> None:
    """与 ModManager 约定一致：可无参调用；勿在此注册路由（由 register_fastapi_routes 挂载）。"""
    logger.info(
        "xcagi-customer-service-bridge mod_init (K)%s", f" mod_id={mod_id}" if mod_id else ""
    )
