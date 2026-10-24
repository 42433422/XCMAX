"""兼容入口：canonical 实现位于 domains.shipment.shipment_orders。

保留 ``app.fastapi_routes.shipment_orders`` 导入路径，避免 evals/tests/tools
在迁移期 ImportError；业务语义不变。
"""
from __future__ import annotations

from app.fastapi_routes.domains.shipment.shipment_orders import *  # noqa: F403
from app.fastapi_routes.domains.shipment import shipment_orders as _canonical

# 显式再导出常用符号，便于静态检查与 from-import
router = _canonical.router
