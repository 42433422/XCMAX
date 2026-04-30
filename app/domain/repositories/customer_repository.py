"""
CustomerRepository - 客户仓储接口

定义客户聚合根的持久化操作。
"""

from typing import List, Optional
from ..aggregates.customer_aggregate import Customer, CustomerStatus
from . import Repository


class CustomerRepository(Repository[Customer, str]):
    """
    客户仓储接口

    定义客户聚合根的查询和持久化操作。
    """

    def get_by_id(self, id: str) -> Optional[Customer]:
        """根据客户ID获取"""
        pass

    def save(self, aggregate: Customer) -> Customer:
        """保存客户"""
        pass

    def delete(self, id: str) -> bool:
        """删除客户"""
        pass

    def list_all(self, limit: int = 100, offset: int = 0) -> List[Customer]:
        """获取客户列表"""
        pass

    def exists(self, id: str) -> bool:
        """检查客户是否存在"""
        pass

    # 客户特有的查询方法

    def get_by_name(self, name: str) -> Optional[Customer]:
        """
        根据名称获取客户

        Args:
            name: 客户名称

        Returns:
            客户实例，不存在则返回 None
        """
        pass

    def search_by_name(self, keyword: str, limit: int = 20) -> List[Customer]:
        """
        根据名称关键字搜索客户

        Args:
            keyword: 搜索关键字
            limit: 数量限制

        Returns:
            客户列表
        """
        pass

    def get_by_status(self, status: CustomerStatus, limit: int = 100) -> List[Customer]:
        """
        根据状态获取客户列表

        Args:
            status: 客户状态
            limit: 数量限制

        Returns:
            客户列表
        """
        pass

    def get_active_customers(self, limit: int = 100) -> List[Customer]:
        """
        获取活跃客户

        Args:
            limit: 数量限制

        Returns:
            活跃客户列表
        """
        pass

    def get_by_credit_limit_range(self, min_limit: float, max_limit: float) -> List[Customer]:
        """
        根据信用额度范围获取客户

        Args:
            min_limit: 最小额度
            max_limit: 最大额度

        Returns:
            客户列表
        """
        pass

    def exists_by_name(self, name: str) -> bool:
        """
        检查名称是否已存在

        Args:
            name: 客户名称

        Returns:
            是否存在
        """
        pass

    def get_top_customers_by_order_count(self, limit: int = 10) -> List[Customer]:
        """
        获取订单量最多的客户

        Args:
            limit: 数量限制

        Returns:
            客户列表
        """
        pass

    def get_customers_with_overdue_balance(self) -> List[Customer]:
        """
        获取有逾期欠款的客户

        Returns:
            客户列表
        """
        pass
