# ruff: noqa: E402, F401
"""
销售应用服务门面（Sales-to-Payment 闭环，W1-09）

本模块是 `sales` 能力工具的只读 / 受控写入**组合门面**（composition only），
本身**不复制**任何状态迁移、履行、库存、分配、退款或贷项通知单领域逻辑：

- 查询 / 报价创建：保留在本门面（只读检索 + 单据创建）。
- 生命周期迁移（confirm / cancel）：委托 ``SalesLifecycleService``。
- 履行动作（deliver）：委托 ``FulfillmentService``。
- 开票 / 贷项通知单（invoice / credit_note）：委托 ``app.application.invoicing_service``。
- 收款 / 退款（payment / refund）：委托 ``app.application.payment_service``（snake_case）。

门面只做参数透传与结果规整，业务副作用统一由各专属模块负责。
"""

from __future__ import annotations

import hashlib
import json
import logging
from contextlib import nullcontext
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import or_

from app.application.invoicing_service import credit_note, invoice
from app.application.payment_service import payment, refund
from app.application.sales_lifecycle_service import (
    SalesLifecycleError,
    SalesLifecycleService,
)
from app.db.models import (
    Customer,
    InventoryLedger,
    Product,
    SalesOrder,
    SalesOrderItem,
    Warehouse,
)
from app.db.models.sales import SALES_ORDER_STATUS_FLOW
from app.db.session import get_db
from app.infrastructure.tenant_scope import (
    TenantScopeError,
    current_tenant_id,
    tenant_id_for_write,
)
from app.services.fulfillment_service import FulfillmentService

logger = logging.getLogger(__name__)

# 复合幂等指纹在既有 remark 字段内的命名空间前缀（不影响顶层 idempotency 标记）。
_CLOSED_LOOP_FP_PREFIX = "w1-10-closed-loop-composite"


def _to_decimal(value: Any) -> Decimal:
    """把报价数值安全转为 Decimal，保证账务全程定点运算、无浮点伪影。"""
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (TypeError, ValueError, InvalidOperation):
        return Decimal("0")


class ClosedLoopExecutionError(RuntimeError):
    """闭环执行失败：携带失败步骤，用于触发外层事务整体回滚。"""

    def __init__(self, step: str, message: str):
        super().__init__(message)
        self.step = step
        self.message = message


from app.application.sales_app_service_salesappservice_mixin01 import _SalesAppServicePart01Mixin
from app.application.sales_app_service_salesappservice_mixin02 import _SalesAppServicePart02Mixin


class SalesAppService(_SalesAppServicePart01Mixin, _SalesAppServicePart02Mixin):
    """销售应用服务门面：组合委托，不含领域副作用逻辑。"""

    # ── 查询（保留在本门面，只读）──────────────────────────────

    # ── 报价创建（保留在本门面，单据创建）───────────────────────

    # ── 生命周期迁移（委托 SalesLifecycleService）──────────────

    # ── 履行（委托 FulfillmentService）──────────────────────────

    # ── 开票 / 贷项通知单（委托 invoicing_service）─────────────

    # ── 收款 / 退款（委托 snake_case payment_service）──────────

    # ── 组合闭环：销售→履行→开票→收款（W1-10，真实原子执行器）────

    # ── 闭环内部：结构/算数校验、实体解析、单事务编排 ──────────────

    # ── 工具内部 ───────────────────────────────────────────────


__all__ = ["SalesAppService", "SALES_ORDER_STATUS_FLOW"]
