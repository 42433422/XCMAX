"""
领域聚合根 - Level 3 富血模型

包含所有核心业务聚合根，实现领域驱动设计的富血模型：
- 自包含业务规则
- 状态变更时发布领域事件
- 维护聚合边界内的一致性
- 使用值对象封装业务概念
"""

# 值对象层（Level 3）
from app.domain.value_objects import (
    Money,
    Currency,
    Quantity,
    UnitOfMeasure,
    Address,
    ContactInfo,
    DateRange,
    Percentage,
    Email,
    PhoneNumber,
)

# 聚合根
from app.domain.aggregates.shipment_aggregate import (
    Shipment,
    ShipmentItem,
    ShipmentStatus,
    ShipmentFactory,
)

from app.domain.aggregates.product_aggregate import (
    Product,
    ProductSpecification,
    ProductStatus,
    ProductFactory,
    ProductPricingService,
)

from app.domain.aggregates.order_aggregate import (
    Order,
    OrderItem,
    OrderStatus,
    PaymentStatus,
    OrderFactory,
)

from app.domain.aggregates.customer_aggregate import (
    Customer,
    CustomerStatus,
    CustomerLevel,
    CustomerFactory,
)

from app.domain.aggregates.inventory_aggregate import (
    Inventory,
    InventoryStatus,
    TransactionType,
    InventoryTransaction,
    InventoryFactory,
)

# 仓储接口（Level 3）
from app.domain.repositories import (
    Repository,
    OrderRepository,
    CustomerRepository,
    ProductRepository,
    InventoryRepository,
    ShipmentRepository,
)

__all__ = [
    # 值对象层 (Level 3)
    "Money",
    "Currency",
    "Quantity",
    "UnitOfMeasure",
    "Address",
    "ContactInfo",
    "DateRange",
    "Percentage",
    "Email",
    "PhoneNumber",
    # 仓储接口 (Level 3)
    "Repository",
    "OrderRepository",
    "CustomerRepository",
    "ProductRepository",
    "InventoryRepository",
    "ShipmentRepository",
    # Shipment 聚合根
    "Shipment",
    "ShipmentItem",
    "ShipmentStatus",
    "ShipmentFactory",
    # Product 聚合根
    "Product",
    "ProductSpecification",
    "ProductStatus",
    "ProductFactory",
    "ProductPricingService",
    # Order 聚合根
    "Order",
    "OrderItem",
    "OrderStatus",
    "PaymentStatus",
    "OrderFactory",
    # Customer 聚合根
    "Customer",
    "CustomerStatus",
    "CustomerLevel",
    "CustomerFactory",
    # Inventory 聚合根
    "Inventory",
    "InventoryStatus",
    "TransactionType",
    "InventoryTransaction",
    "InventoryFactory",
]
