"""
Product 富血模型聚合根

Level 3 领域模型实现:
- 富血模型：业务规则封装在领域对象中
- 聚合根：维护产品数据和业务规则的一致性边界
- 值对象：价格和规格作为值对象
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4


class ProductStatus(Enum):
    """产品状态枚举"""
    ACTIVE = "active"       # 在售
    INACTIVE = "inactive"   # 停售
    DISCONTINUED = "discontinued"  # 停产


@dataclass(frozen=True)
class ProductSpecification:
    """
    产品规格（值对象）
    
    值对象特征：
    - 不可变（frozen=True）
    - 通过属性值判断相等
    - 无唯一标识
    """
    model_number: str
    specification: Optional[str] = None
    unit: str = "桶"  # 默认单位
    
    def __str__(self) -> str:
        if self.specification:
            return f"{self.model_number} ({self.specification})"
        return self.model_number


@dataclass(frozen=True)
class Money:
    """
    金额（值对象）
    
    封装货币计算规则：
    - 精度处理
    - 算术运算
    - 验证规则
    """
    amount: float
    currency: str = "CNY"
    
    def __post_init__(self):
        if self.amount < 0:
            raise ValueError(f"金额不能为负数: {self.amount}")
    
    def __add__(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValueError("不同货币不能直接相加")
        return Money(self.amount + other.amount, self.currency)
    
    def __mul__(self, quantity: int) -> "Money":
        if quantity < 0:
            raise ValueError("数量不能为负数")
        return Money(self.amount * quantity, self.currency)
    
    @property
    def formatted(self) -> str:
        """格式化金额显示"""
        symbols = {"CNY": "¥", "USD": "$", "EUR": "€"}
        symbol = symbols.get(self.currency, self.currency)
        return f"{symbol}{self.amount:.2f}"


class Product:
    """
    产品聚合根（富血模型）
    
    Level 3 领域模型:
    - 自包含产品业务规则
    - 价格变更追踪
    - 状态转换验证
    - 发布领域事件
    """
    
    def __init__(
        self,
        product_id: str,
        unit_name: str,
        product_name: str,
        model_number: str,
        price: Money,
        specification: Optional[ProductSpecification] = None,
        status: ProductStatus = ProductStatus.ACTIVE,
        created_by: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.product_id = product_id
        self.unit_name = unit_name
        self.product_name = product_name
        self.model_number = model_number
        self._price = price
        self._specification = specification or ProductSpecification(model_number)
        self._status = status
        self.created_by = created_by
        self.metadata = metadata or {}
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        
        # 价格历史（用于追踪）
        self._price_history: List[Dict[str, Any]] = [
            {
                "price": price.amount,
                "changed_at": self.created_at.isoformat(),
                "reason": "created",
            }
        ]
        
        # 领域事件
        self._domain_events: List[Dict[str, Any]] = []
        
        # 验证
        self._validate()
        
        # 记录创建事件
        self._record_event("product.created", {
            "product_id": self.product_id,
            "unit_name": self.unit_name,
            "product_name": self.product_name,
            "model_number": self.model_number,
            "price": self._price.amount,
        })
    
    # ========== 领域规则验证 ==========
    
    def _validate(self):
        """验证产品有效性"""
        if not self.product_id:
            raise ValueError("产品 ID 不能为空")
        if not self.unit_name:
            raise ValueError("单位名称不能为空")
        if not self.product_name:
            raise ValueError("产品名称不能为空")
        if not self.model_number:
            raise ValueError("型号不能为空")
    
    def _validate_status_transition(self, new_status: ProductStatus):
        """验证状态转换"""
        invalid_transitions = {
            ProductStatus.DISCONTINUED: [ProductStatus.ACTIVE],  # 停产后不能恢复在售
        }
        
        invalid = invalid_transitions.get(self._status, [])
        if new_status in invalid:
            raise ValueError(
                f"非法状态转换: {self._status.value} -> {new_status.value}"
            )
    
    # ========== 领域事件 ==========
    
    def _record_event(self, event_type: str, payload: Dict[str, Any]):
        """记录领域事件"""
        self._domain_events.append({
            "event_type": event_type,
            "payload": payload,
            "timestamp": datetime.now().isoformat(),
        })
    
    def get_domain_events(self) -> List[Dict[str, Any]]:
        """获取待发布的领域事件"""
        return self._domain_events.copy()
    
    def clear_domain_events(self):
        """清空领域事件"""
        self._domain_events.clear()
    
    # ========== 业务行为方法 ==========
    
    def change_price(self, new_price: Money, reason: str = "manual") -> "Product":
        """
        变更价格
        
        业务规则:
        - 记录价格历史
        - 发布价格变更事件
        """
        if new_price.currency != self._price.currency:
            raise ValueError("不能改变货币类型")
        
        old_price = self._price
        self._price = new_price
        self.updated_at = datetime.now()
        
        # 记录价格历史
        self._price_history.append({
            "price": new_price.amount,
            "changed_at": self.updated_at.isoformat(),
            "reason": reason,
        })
        
        # 记录领域事件
        self._record_event("product.price_changed", {
            "product_id": self.product_id,
            "old_price": old_price.amount,
            "new_price": new_price.amount,
            "change_rate": round((new_price.amount - old_price.amount) / old_price.amount, 4) if old_price.amount else 0,
            "reason": reason,
        })
        
        return self
    
    def update_info(
        self,
        product_name: Optional[str] = None,
        specification: Optional[ProductSpecification] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "Product":
        """
        更新产品信息
        
        业务规则:
        - 停售产品不能修改信息
        """
        if self._status == ProductStatus.DISCONTINUED:
            raise ValueError("停产产品不能修改信息")
        
        if product_name:
            self.product_name = product_name
        if specification:
            self._specification = specification
        if metadata:
            self.metadata.update(metadata)
        
        self.updated_at = datetime.now()
        
        self._record_event("product.info_updated", {
            "product_id": self.product_id,
            "changes": {
                "product_name": product_name is not None,
                "specification": specification is not None,
                "metadata": metadata is not None,
            },
        })
        
        return self
    
    def activate(self) -> "Product":
        """激活产品"""
        self._validate_status_transition(ProductStatus.ACTIVE)
        
        old_status = self._status
        self._status = ProductStatus.ACTIVE
        self.updated_at = datetime.now()
        
        self._record_event("product.activated", {
            "product_id": self.product_id,
            "old_status": old_status.value,
        })
        
        return self
    
    def deactivate(self, reason: str = "") -> "Product":
        """停售产品"""
        self._validate_status_transition(ProductStatus.INACTIVE)
        
        old_status = self._status
        self._status = ProductStatus.INACTIVE
        self.updated_at = datetime.now()
        
        self._record_event("product.deactivated", {
            "product_id": self.product_id,
            "old_status": old_status.value,
            "reason": reason,
        })
        
        return self
    
    def discontinue(self, reason: str = "") -> "Product":
        """
        停产产品
        
        业务规则:
        - 永久停售，不能恢复
        """
        old_status = self._status
        self._status = ProductStatus.DISCONTINUED
        self.updated_at = datetime.now()
        
        self._record_event("product.discontinued", {
            "product_id": self.product_id,
            "old_status": old_status.value,
            "reason": reason,
        })
        
        return self
    
    # ========== 计算属性 ==========
    
    @property
    def price(self) -> Money:
        """当前价格"""
        return self._price
    
    @property
    def specification(self) -> ProductSpecification:
        """产品规格"""
        return self._specification
    
    @property
    def status(self) -> ProductStatus:
        """当前状态"""
        return self._status
    
    @property
    def is_active(self) -> bool:
        """是否在售"""
        return self._status == ProductStatus.ACTIVE
    
    @property
    def is_available(self) -> bool:
        """是否可用（在售或停售）"""
        return self._status in [ProductStatus.ACTIVE, ProductStatus.INACTIVE]
    
    @property
    def price_history(self) -> List[Dict[str, Any]]:
        """价格历史"""
        return self._price_history.copy()
    
    def calculate_total(self, quantity: int) -> Money:
        """计算指定数量的总价"""
        if quantity <= 0:
            raise ValueError("数量必须大于 0")
        return self._price * quantity
    
    def compare_price(self, other: "Product") -> Dict[str, Any]:
        """与另一产品比价"""
        if self._price.currency != other._price.currency:
            return {
                "comparable": False,
                "reason": "货币类型不同",
            }
        
        diff = self._price.amount - other._price.amount
        return {
            "comparable": True,
            "price_diff": diff,
            "cheaper": "self" if diff < 0 else "other" if diff > 0 else "equal",
            "cheaper_by": abs(diff),
            "cheaper_by_percent": abs(diff) / other._price.amount if other._price.amount else 0,
        }
    
    # ========== 序列化 ==========
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "product_id": self.product_id,
            "unit_name": self.unit_name,
            "product_name": self.product_name,
            "model_number": self.model_number,
            "price": self._price.amount,
            "currency": self._price.currency,
            "formatted_price": self._price.formatted,
            "specification": str(self._specification),
            "model": self._specification.model_number,
            "spec": self._specification.specification,
            "unit": self._specification.unit,
            "status": self._status.value,
            "is_active": self.is_active,
            "is_available": self.is_available,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "price_history": self._price_history,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Product":
        """从字典创建实例"""
        price = Money(
            amount=data.get("price", 0),
            currency=data.get("currency", "CNY"),
        )
        
        spec = ProductSpecification(
            model_number=data.get("model_number", ""),
            specification=data.get("spec"),
            unit=data.get("unit", "桶"),
        )
        
        product = cls(
            product_id=data["product_id"],
            unit_name=data["unit_name"],
            product_name=data["product_name"],
            model_number=data["model_number"],
            price=price,
            specification=spec,
            status=ProductStatus(data.get("status", "active")),
            created_by=data.get("created_by"),
            metadata=data.get("metadata", {}),
        )
        
        # 恢复历史
        if "price_history" in data:
            product._price_history = data["price_history"]
        if "created_at" in data:
            product.created_at = datetime.fromisoformat(data["created_at"])
        if "updated_at" in data:
            product.updated_at = datetime.fromisoformat(data["updated_at"])
        
        return product


# ========== 领域工厂 ==========

class ProductFactory:
    """产品工厂"""
    
    @staticmethod
    def create(
        unit_name: str,
        product_name: str,
        model_number: str,
        price: float,
        specification: Optional[str] = None,
        unit: str = "桶",
        created_by: Optional[str] = None,
    ) -> Product:
        """创建新产品"""
        product_id = f"PR{datetime.now().strftime('%Y%m%d%H%M%S')}{str(uuid4())[:6]}"
        
        spec = ProductSpecification(
            model_number=model_number,
            specification=specification,
            unit=unit,
        )
        
        return Product(
            product_id=product_id,
            unit_name=unit_name,
            product_name=product_name,
            model_number=model_number,
            price=Money(price),
            specification=spec,
            status=ProductStatus.ACTIVE,
            created_by=created_by,
        )
    
    @staticmethod
    def create_from_import(
        unit_name: str,
        import_data: Dict[str, Any],
    ) -> Product:
        """从导入数据创建产品"""
        return ProductFactory.create(
            unit_name=unit_name,
            product_name=import_data.get("product_name", ""),
            model_number=import_data.get("model_number", ""),
            price=import_data.get("price", 0),
            specification=import_data.get("specification"),
            unit=import_data.get("unit", "桶"),
            created_by=import_data.get("imported_by"),
        )


# ========== 领域服务 ==========

class ProductPricingService:
    """
    产品定价领域服务
    
    处理跨聚合的定价逻辑
    """
    
    @staticmethod
    def calculate_bulk_discount(products: List[Product], quantities: List[int]) -> float:
        """计算批量折扣"""
        if len(products) != len(quantities):
            raise ValueError("产品列表和数量列表长度必须相同")
        
        total = sum(
            p.calculate_total(q).amount
            for p, q in zip(products, quantities)
        )
        
        # 阶梯折扣
        if total >= 50000:
            return 0.15  # 15% 折扣
        elif total >= 20000:
            return 0.10  # 10% 折扣
        elif total >= 5000:
            return 0.05  # 5% 折扣
        
        return 0.0
    
    @staticmethod
    def find_cheaper_alternative(
        target: Product,
        alternatives: List[Product],
        min_savings_percent: float = 0.05,
    ) -> Optional[Product]:
        """寻找更便宜的替代产品"""
        best: Optional[Product] = None
        best_savings = 0.0
        
        for alt in alternatives:
            if not alt.is_available:
                continue
            
            comparison = target.compare_price(alt)
            if not comparison["comparable"]:
                continue
            
            if comparison["cheaper"] == "other":
                savings_percent = comparison["cheaper_by_percent"]
                if savings_percent >= min_savings_percent and savings_percent > best_savings:
                    best = alt
                    best_savings = savings_percent
        
        return best
