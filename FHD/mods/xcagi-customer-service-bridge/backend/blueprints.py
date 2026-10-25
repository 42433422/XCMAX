"""Customer-service Mod: shared request models and explicit host capability assembly."""

from __future__ import annotations

import logging
import os as os
from datetime import UTC, datetime
from typing import Any, Dict, cast

from fastapi import APIRouter
from fastapi import Request as Request

from app.application.customer_service.protocols import Employee, Environment
from app.mod_sdk.customer_service.assembly import register_routes
from app.mod_sdk.customer_service.models import (
    AnalyzePipelineBody as AnalyzePipelineBody,
)
from app.mod_sdk.customer_service.models import (
    ChangeRequestCreateBody as ChangeRequestCreateBody,
)
from app.mod_sdk.customer_service.models import (
    ChangeRequestNotifyBody as ChangeRequestNotifyBody,
)
from app.mod_sdk.customer_service.models import (
    ChangeRequestStatusBody as ChangeRequestStatusBody,
)
from app.mod_sdk.customer_service.models import (
    ConnectedWelcomeBody as ConnectedWelcomeBody,
)
from app.mod_sdk.customer_service.models import (
    ContractFieldsBody as ContractFieldsBody,
)
from app.mod_sdk.customer_service.models import (
    ContractGenerateBody as ContractGenerateBody,
)
from app.mod_sdk.customer_service.models import (
    DeliveryPaymentBody as DeliveryPaymentBody,
)
from app.mod_sdk.customer_service.models import (
    DeliveryPlanBody as DeliveryPlanBody,
)
from app.mod_sdk.customer_service.models import (
    DemandFormManualBody as DemandFormManualBody,
)
from app.mod_sdk.customer_service.models import (
    DemandFormRedeemCodeBody as DemandFormRedeemCodeBody,
)
from app.mod_sdk.customer_service.models import (
    DemandFormSyncBody as DemandFormSyncBody,
)
from app.mod_sdk.customer_service.models import (
    DemandIntakeBody as DemandIntakeBody,
)
from app.mod_sdk.customer_service.models import (
    EnterpriseCredentialsIssueBody as EnterpriseCredentialsIssueBody,
)
from app.mod_sdk.customer_service.models import (
    IntakeNoticeBody as IntakeNoticeBody,
)
from app.mod_sdk.customer_service.models import (
    LandingFunnelSyncBody as LandingFunnelSyncBody,
)
from app.mod_sdk.customer_service.models import (
    PipelineBody as PipelineBody,
)
from app.mod_sdk.customer_service.models import (
    WechatSendBody as WechatSendBody,
)
from app.mod_sdk.errors import BOUNDARY_ERRORS as BOUNDARY_ERRORS

logger = logging.getLogger(__name__)
CUSTOMER_SERVICE_BRIDGE_MOD_ID = "xcagi-customer-service-bridge"


async def _run_user_cs_employee(payload: Dict[str, Any]) -> Dict[str, Any]:
    """调用 user-customer-service-officer 员工包（mods/_employees）。"""
    from app.mod_sdk.host_services import run_user_cs_employee

    return await cast(Employee, run_user_cs_employee)(payload)


def register_fastapi_routes(app, mod_id: str) -> None:
    router = APIRouter(prefix=f"/api/mod/{mod_id}", tags=[f"customer-service-bridge-{mod_id}"])
    register_routes(
        router,
        mod_id,
        lambda payload: _run_user_cs_employee(payload),
        Environment(
            now=lambda: datetime.now(UTC).isoformat(),
            logger=lambda: logger,
            boundary_errors=lambda: BOUNDARY_ERRORS,
        ),
    )
    app.include_router(router)
    logger.info("xcagi-customer-service-bridge registered: %s", mod_id)


def mod_init(app=None, mod_id: str | None = None) -> None:
    """与 ModManager 约定一致：可无参调用；勿在此注册路由（由 register_fastapi_routes 挂载）。"""
    logger.info(
        "xcagi-customer-service-bridge mod_init (K)%s", f" mod_id={mod_id}" if mod_id else ""
    )
