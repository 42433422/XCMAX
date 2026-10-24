"""兼容入口：canonical 实现位于 domains.shipment.shipment_orders。

保留 ``app.fastapi_routes.shipment_orders`` 导入路径，避免 evals/tests/tools
在迁移期 ImportError；业务语义不变。
"""

from __future__ import annotations

import sys

from app.fastapi_routes.domains.shipment import shipment_orders as _canonical

sys.modules[__name__] = _canonical
