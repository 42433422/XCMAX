"""
ShipmentRepository - 发货单仓储接口

定义发货单聚合根的持久化操作。
"""

from typing import List, Optional
from datetime import date
from decimal import Decimal
from ..aggregates.shipment_aggregate import Shipment, ShipmentStatus
from . import Repository


class ShipmentRepository(Repository[Shipment, str]):
    """
    发货单仓储接口

    定义发货单聚合根的查询和持久化操作。
    """

    def get_by_id(self, id: str) -> Optional[Shipment]:
        """根据发货单ID获取"""
        pass

    def save(self, aggregate: Shipment) -> Shipment:
        """保存发货单"""
        pass

    def delete(self, id: str) -> bool:
        """删除发货单"""
        pass

    def list_all(self, limit: int = 100, offset: int = 0) -> List[Shipment]:
        """获取发货单列表"""
        pass

    def exists(self, id: str) -> bool:
        """检查发货单是否存在"""
        pass

    # 发货单特有的查询方法

    def get_by_order_id(self, order_id: str) -> List[Shipment]:
        """
        根据订单ID获取发货单

        Args:
            order_id: 订单ID

        Returns:
            发货单列表
        """
        pass

    def get_by_customer_id(self, customer_id: str, limit: int = 100) -> List[Shipment]:
        """
        根据客户ID获取发货单

        Args:
            customer_id: 客户ID
            limit: 数量限制

        Returns:
            发货单列表
        """
        pass

    def get_by_status(self, status: ShipmentStatus, limit: int = 100) -> List[Shipment]:
        """
        根据状态获取发货单

        Args:
            status: 发货单状态
            limit: 数量限制

        Returns:
            发货单列表
        """
        pass

    def get_by_date_range(self, start_date: date, end_date: date) -> List[Shipment]:
        """
        根据日期范围获取发货单

        Args:
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            发货单列表
        """
        pass

    def get_pending_shipments(self, limit: int = 100) -> List[Shipment]:
        """
        获取待发货订单

        Args:
            limit: 数量限制

        Returns:
            发货单列表
        """
        pass

    def get_by_tracking_number(self, tracking_number: str) -> Optional[Shipment]:
        """
        根据物流单号获取发货单

        Args:
            tracking_number: 物流单号

        Returns:
            发货单实例
        """
        pass

    def get_by_purchase_unit(self, purchase_unit: str, limit: int = 100) -> List[Shipment]:
        """
        根据购买单位获取发货单

        Args:
            purchase_unit: 购买单位名称
            limit: 数量限制

        Returns:
            发货单列表
        """
        pass

    def get_total_amount_by_date_range(self, start_date: date, end_date: date) -> Decimal:
        """
        获取日期范围内的发货总金额

        Args:
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            总金额
        """
        pass

    def get_shipment_count_by_status(self, status: ShipmentStatus) -> int:
        """
        统计某状态的发货单数量

        Args:
            status: 发货单状态

        Returns:
            数量
        """
        pass

    def get_top_customers_by_shipment_count(self, limit: int = 10) -> List[tuple]:
        """
        获取发货次数最多的客户

        Args:
            limit: 数量限制

        Returns:
            [(customer_id, count), ...]
        """
        pass

    def search_by_keyword(self, keyword: str, limit: int = 20) -> List[Shipment]:
        """
        根据关键字搜索发货单

        Args:
            keyword: 搜索关键字
            limit: 数量限制

        Returns:
            发货单列表
        """
        pass
