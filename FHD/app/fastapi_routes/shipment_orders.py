"""兼容入口：canonical 实现位于 domains.shipment.shipment_orders。

保留 ``app.fastapi_routes.shipment_orders`` 导入路径与模块身份；业务语义不变。
服务替身请 patch ``domains.shipment.shipment_order_support.svc``。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # 供 mypy 看见 canonical 符号
    from app.fastapi_routes.domains.shipment.shipment_orders import (  # noqa: F401
        router,
        shipment_download,
        shipment_generate,
        shipment_print,
    )
else:
    import sys

    from app.fastapi_routes.domains.shipment import shipment_orders as _canonical

    sys.modules[__name__] = _canonical
