"""支付基础设施层(模型支付 / 支付宝等)。

原位置 ``backend/services/model_payment_*`` 已于 2026-04-20 随 ``backend/`` 一同删除;
旧 shim 不再存在,所有调用方必须直接从本包导入:

    from app.infrastructure.payment import alipay, order_store
"""

from __future__ import annotations

from app.infrastructure.payment import alipay, order_store

__all__ = ["alipay", "order_store"]
