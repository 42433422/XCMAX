"""
库存管理服务模块

提供仓库、库位、库存台账、库存流水等业务逻辑。
"""

import logging

from app.db.models import (
    InventoryLedger as InventoryLedger,
)
from app.db.models import (
    InventoryTransaction as InventoryTransaction,
)
from app.db.models import (
    Product as Product,
)
from app.db.models import (
    StorageLocation as StorageLocation,
)
from app.db.models import (
    Warehouse as Warehouse,
)
from app.db.session import get_db as get_db

logger = logging.getLogger(__name__)


from app.services.inventory_counting import InventoryCountingMixin
from app.services.inventory_lookup import InventoryLookupMixin
from app.services.inventory_movements import InventoryMovementsMixin
from app.services.inventory_orders import InventoryOrdersMixin
from app.services.inventory_warehouses import InventoryWarehouseMixin


class InventoryService(
    InventoryWarehouseMixin,
    InventoryLookupMixin,
    InventoryMovementsMixin,
    InventoryCountingMixin,
    InventoryOrdersMixin,
):
    """库存管理服务类，由仓库、流水、盘点和订单库存职责组合。"""


# NEURO-DDD: 为 Services 层类添加 instrumentation
from app.neuro_bus.neuro_service_instrumentation import instrument_service_layer_class

instrument_service_layer_class(InventoryService, "app.services.inventory_service")
