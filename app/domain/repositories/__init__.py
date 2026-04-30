"""
仓储层 (Repositories)

领域驱动设计中的仓储模式，用于抽象聚合根的持久化操作。
仓储接口定义在领域层，实现定义在基础设施层。

Level 3 领域模型关键组件
"""

from typing import TypeVar, Generic, List, Optional, Protocol
from abc import ABC, abstractmethod

T = TypeVar('T')
ID = TypeVar('ID')


class Repository(ABC, Generic[T, ID]):
    """
    仓储接口基类

    定义聚合根的基本 CRUD 操作。
    所有具体仓储接口都应继承此类。

    Type Parameters:
        T: 聚合根类型
        ID: 标识符类型
    """

    @abstractmethod
    def get_by_id(self, id: ID) -> Optional[T]:
        """
        根据 ID 获取聚合根

        Args:
            id: 聚合根标识符

        Returns:
            聚合根实例，如果不存在则返回 None
        """
        pass

    @abstractmethod
    def save(self, aggregate: T) -> T:
        """
        保存聚合根（新增或更新）

        Args:
            aggregate: 聚合根实例

        Returns:
            保存后的聚合根
        """
        pass

    @abstractmethod
    def delete(self, id: ID) -> bool:
        """
        删除聚合根

        Args:
            id: 聚合根标识符

        Returns:
            是否删除成功
        """
        pass

    @abstractmethod
    def list_all(self, limit: int = 100, offset: int = 0) -> List[T]:
        """
        获取聚合根列表

        Args:
            limit: 返回数量限制
            offset: 偏移量

        Returns:
            聚合根列表
        """
        pass

    @abstractmethod
    def exists(self, id: ID) -> bool:
        """
        检查聚合根是否存在

        Args:
            id: 聚合根标识符

        Returns:
            是否存在
        """
        pass


# 导入具体仓储接口
from .order_repository import OrderRepository
from .customer_repository import CustomerRepository
from .product_repository import ProductRepository
from .inventory_repository import InventoryRepository
from .shipment_repository import ShipmentRepository

__all__ = [
    # 基类
    "Repository",
    # 具体仓储接口
    "OrderRepository",
    "CustomerRepository",
    "ProductRepository",
    "InventoryRepository",
    "ShipmentRepository",
]
