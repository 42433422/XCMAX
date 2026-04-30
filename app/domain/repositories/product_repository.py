"""
ProductRepository - 产品仓储接口

定义产品聚合根的持久化操作。
"""

from typing import List, Optional
from decimal import Decimal
from ..aggregates.product_aggregate import Product
from . import Repository


class ProductRepository(Repository[Product, str]):
    """
    产品仓储接口

    定义产品聚合根的查询和持久化操作。
    """

    def get_by_id(self, id: str) -> Optional[Product]:
        """根据产品ID获取"""
        pass

    def save(self, aggregate: Product) -> Product:
        """保存产品"""
        pass

    def delete(self, id: str) -> bool:
        """删除产品"""
        pass

    def list_all(self, limit: int = 100, offset: int = 0) -> List[Product]:
        """获取产品列表"""
        pass

    def exists(self, id: str) -> bool:
        """检查产品是否存在"""
        pass

    # 产品特有的查询方法

    def get_by_model_number(self, model_number: str) -> Optional[Product]:
        """
        根据型号获取产品

        Args:
            model_number: 产品型号

        Returns:
            产品实例，不存在则返回 None
        """
        pass

    def search_by_name(self, keyword: str, limit: int = 20) -> List[Product]:
        """
        根据名称搜索产品

        Args:
            keyword: 搜索关键字
            limit: 数量限制

        Returns:
            产品列表
        """
        pass

    def get_by_category(self, category: str, limit: int = 100) -> List[Product]:
        """
        根据分类获取产品

        Args:
            category: 产品分类
            limit: 数量限制

        Returns:
            产品列表
        """
        pass

    def get_active_products(self, limit: int = 100) -> List[Product]:
        """
        获取在售产品

        Args:
            limit: 数量限制

        Returns:
            产品列表
        """
        pass

    def get_by_price_range(self, min_price: Decimal, max_price: Decimal) -> List[Product]:
        """
        根据价格范围获取产品

        Args:
            min_price: 最低价格
            max_price: 最高价格

        Returns:
            产品列表
        """
        pass

    def get_low_stock_products(self, threshold: int = 10) -> List[Product]:
        """
        获取库存不足的产品

        Args:
            threshold: 库存阈值

        Returns:
            产品列表
        """
        pass

    def exists_by_model_number(self, model_number: str) -> bool:
        """
        检查型号是否已存在

        Args:
            model_number: 产品型号

        Returns:
            是否存在
        """
        pass

    def get_top_selling_products(self, limit: int = 10) -> List[Product]:
        """
        获取热销产品

        Args:
            limit: 数量限制

        Returns:
            产品列表
        """
        pass
