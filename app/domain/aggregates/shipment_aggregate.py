"""
Shipment 富血模型聚合根

Level 3 领域模型实现:
- 富血模型：业务规则封装在领域对象中
- 聚合根：维护聚合内的一致性边界
- 领域事件：状态变更时自动发布领域事件

与贫血模型的区别：
- 贫血：对象只有 getter/setter，业务逻辑在 Service 层
- 富血：对象包含业务行为和规则，自包含、自验证
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4


class ShipmentStatus(Enum):
    """发货单状态枚举"""
    DRAFT = "draft"           # 草稿
    PENDING = "pending"       # 待处理
    CONFIRMED = "confirmed"   # 已确认
    PRINTED = "printed"       # 已打印
    SHIPPED = "shipped"       # 已发货
    CANCELLED = "cancelled"   # 已取消


class ShipmentItem:
    """发货单项（值对象）"""
    
    def __init__(
        self,
        product_id: str,
        product_name: str,
        model_number: str,
        quantity: int,
        unit_price: float = 0.0,
        specification: Optional[str] = None,
    ):
        self.product_id = product_id
        self.product_name = product_name
        self.model_number = model_number
        self.quantity = quantity
        self.unit_price = unit_price
        self.specification = specification
        self._validate()
    
    def _validate(self):
        """验证项数据有效性"""
        if self.quantity <= 0:
            raise ValueError(f"发货单项数量必须大于 0: {self.quantity}")
        if self.unit_price < 0:
            raise ValueError(f"发货单项单价不能为负数: {self.unit_price}")
    
    @property
    def total_amount(self) -> float:
        """计算项总金额"""
        return self.unit_price * self.quantity
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "product_id": self.product_id,
            "product_name": self.product_name,
            "model_number": self.model_number,
            "quantity": self.quantity,
            "unit_price": self.unit_price,
            "specification": self.specification,
            "total_amount": self.total_amount,
        }


class Shipment:
    """
    发货单聚合根（富血模型）
    
    Level 3 领域模型:
    - 自包含业务规则
    - 状态变更时发布领域事件
    - 维护聚合边界内的一致性
    """
    
    def __init__(
        self,
        shipment_id: str,
        unit_name: str,
        items: Optional[List[ShipmentItem]] = None,
        status: ShipmentStatus = ShipmentStatus.DRAFT,
        created_by: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.shipment_id = shipment_id
        self.unit_name = unit_name
        self._items: List[ShipmentItem] = items or []
        self._status = status
        self.created_by = created_by
        self.metadata = metadata or {}
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        self._printed_at: Optional[datetime] = None
        self._cancelled_at: Optional[datetime] = None
        self._cancel_reason: Optional[str] = None
        self._domain_events: List[Dict[str, Any]] = []
        
        # 验证聚合根有效性
        self._validate()
        
        # 记录创建事件
        self._record_event("shipment.created", {
            "shipment_id": self.shipment_id,
            "unit_name": self.unit_name,
            "item_count": len(self._items),
        })
    
    # ========== 领域规则验证 ==========
    
    def _validate(self):
        """验证聚合根有效性"""
        if not self.shipment_id:
            raise ValueError("发货单 ID 不能为空")
        if not self.unit_name:
            raise ValueError("购买单位不能为空")
    
    def _validate_state_transition(self, new_status: ShipmentStatus):
        """验证状态转换是否合法"""
        valid_transitions = {
            ShipmentStatus.DRAFT: [ShipmentStatus.PENDING, ShipmentStatus.CANCELLED],
            ShipmentStatus.PENDING: [ShipmentStatus.CONFIRMED, ShipmentStatus.CANCELLED],
            ShipmentStatus.CONFIRMED: [ShipmentStatus.PRINTED, ShipmentStatus.CANCELLED],
            ShipmentStatus.PRINTED: [ShipmentStatus.SHIPPED, ShipmentStatus.CANCELLED],
            ShipmentStatus.SHIPPED: [],  # 终态
            ShipmentStatus.CANCELLED: [],  # 终态
        }
        
        allowed = valid_transitions.get(self._status, [])
        if new_status not in allowed and new_status != self._status:
            raise ValueError(
                f"非法状态转换: {self._status.value} -> {new_status.value}"
            )
    
    # ========== 领域事件记录 ==========
    
    def _record_event(self, event_type: str, payload: Dict[str, Any]):
        """记录领域事件（待发布）"""
        self._domain_events.append({
            "event_type": event_type,
            "payload": payload,
            "timestamp": datetime.now().isoformat(),
        })
    
    def get_domain_events(self) -> List[Dict[str, Any]]:
        """获取待发布的领域事件"""
        return self._domain_events.copy()
    
    def clear_domain_events(self):
        """清空领域事件（发布成功后调用）"""
        self._domain_events.clear()
    
    # ========== 业务行为方法（富血模型核心） ==========
    
    def add_item(self, item: ShipmentItem) -> "Shipment":
        """
        添加发货单项
        
        业务规则:
        - 只有 DRAFT 或 PENDING 状态可以添加项
        - 自动更新总金额
        """
        if self._status not in [ShipmentStatus.DRAFT, ShipmentStatus.PENDING]:
            raise ValueError(f"当前状态 {self._status.value} 不允许添加项")
        
        self._items.append(item)
        self.updated_at = datetime.now()
        
        # 记录领域事件
        self._record_event("shipment.item_added", {
            "shipment_id": self.shipment_id,
            "product_id": item.product_id,
            "quantity": item.quantity,
            "unit_price": item.unit_price,
        })
        
        return self
    
    def remove_item(self, product_id: str) -> "Shipment":
        """
        移除发货单项
        
        业务规则:
        - 只有 DRAFT 状态可以移除项
        """
        if self._status != ShipmentStatus.DRAFT:
            raise ValueError(f"当前状态 {self._status.value} 不允许移除项")
        
        original_count = len(self._items)
        self._items = [item for item in self._items if item.product_id != product_id]
        
        if len(self._items) == original_count:
            raise ValueError(f"未找到产品 ID: {product_id}")
        
        self.updated_at = datetime.now()
        
        self._record_event("shipment.item_removed", {
            "shipment_id": self.shipment_id,
            "product_id": product_id,
        })
        
        return self
    
    def confirm(self) -> "Shipment":
        """
        确认发货单
        
        业务规则:
        - 至少有一项产品
        - 从 PENDING 状态转换
        """
        self._validate_state_transition(ShipmentStatus.CONFIRMED)
        
        if not self._items:
            raise ValueError("确认前必须至少有一项产品")
        
        self._status = ShipmentStatus.CONFIRMED
        self.updated_at = datetime.now()
        
        self._record_event("shipment.confirmed", {
            "shipment_id": self.shipment_id,
            "total_amount": self.total_amount,
            "item_count": len(self._items),
        })
        
        return self
    
    def mark_printed(self, printer_name: str = "default") -> "Shipment":
        """
        标记为已打印
        
        业务规则:
        - 从 CONFIRMED 或 PENDING 状态转换
        - 记录打印时间和打印机
        """
        self._validate_state_transition(ShipmentStatus.PRINTED)
        
        self._status = ShipmentStatus.PRINTED
        self._printed_at = datetime.now()
        self.updated_at = datetime.now()
        
        self._record_event("shipment.printed", {
            "shipment_id": self.shipment_id,
            "printer_name": printer_name,
            "printed_at": self._printed_at.isoformat(),
        })
        
        return self
    
    def cancel(self, reason: str, restore_inventory: bool = True) -> "Shipment":
        """
        取消发货单
        
        业务规则:
        - SHIPPED 状态不能取消
        - 必须提供取消原因
        - 可选择是否恢复库存
        """
        if self._status == ShipmentStatus.SHIPPED:
            raise ValueError("已发货订单不能取消")
        
        if not reason:
            raise ValueError("取消必须提供原因")
        
        self._status = ShipmentStatus.CANCELLED
        self._cancelled_at = datetime.now()
        self._cancel_reason = reason
        self.updated_at = datetime.now()
        
        self._record_event("shipment.cancelled", {
            "shipment_id": self.shipment_id,
            "reason": reason,
            "restore_inventory": restore_inventory,
            "cancelled_at": self._cancelled_at.isoformat(),
        })
        
        return self
    
    def ship(self) -> "Shipment":
        """
        标记为已发货
        
        业务规则:
        - 从 PRINTED 状态转换
        - 发货后不能修改
        """
        self._validate_state_transition(ShipmentStatus.SHIPPED)
        
        self._status = ShipmentStatus.SHIPPED
        self.updated_at = datetime.now()
        
        self._record_event("shipment.shipped", {
            "shipment_id": self.shipment_id,
            "shipped_at": datetime.now().isoformat(),
        })
        
        return self
    
    # ========== 计算属性 ==========
    
    @property
    def status(self) -> ShipmentStatus:
        """当前状态"""
        return self._status
    
    @property
    def items(self) -> List[ShipmentItem]:
        """发货单项列表（只读副本）"""
        return self._items.copy()
    
    @property
    def total_amount(self) -> float:
        """总金额"""
        return sum(item.total_amount for item in self._items)
    
    @property
    def total_quantity(self) -> int:
        """总数量"""
        return sum(item.quantity for item in self._items)
    
    @property
    def is_editable(self) -> bool:
        """是否可编辑"""
        return self._status in [ShipmentStatus.DRAFT, ShipmentStatus.PENDING]
    
    @property
    def is_cancelled(self) -> bool:
        """是否已取消"""
        return self._status == ShipmentStatus.CANCELLED
    
    @property
    def is_final(self) -> bool:
        """是否终态（不可修改）"""
        return self._status in [ShipmentStatus.SHIPPED, ShipmentStatus.CANCELLED]
    
    # ========== 序列化 ==========
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "shipment_id": self.shipment_id,
            "unit_name": self.unit_name,
            "status": self._status.value,
            "items": [item.to_dict() for item in self._items],
            "total_amount": self.total_amount,
            "total_quantity": self.total_quantity,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "printed_at": self._printed_at.isoformat() if self._printed_at else None,
            "cancelled_at": self._cancelled_at.isoformat() if self._cancelled_at else None,
            "cancel_reason": self._cancel_reason,
            "is_editable": self.is_editable,
            "is_final": self.is_final,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Shipment":
        """从字典创建实例"""
        items = [
            ShipmentItem(
                product_id=item["product_id"],
                product_name=item["product_name"],
                model_number=item["model_number"],
                quantity=item["quantity"],
                unit_price=item.get("unit_price", 0),
                specification=item.get("specification"),
            )
            for item in data.get("items", [])
        ]
        
        shipment = cls(
            shipment_id=data["shipment_id"],
            unit_name=data["unit_name"],
            items=items,
            status=ShipmentStatus(data.get("status", "draft")),
            created_by=data.get("created_by"),
            metadata=data.get("metadata", {}),
        )
        
        # 恢复时间戳
        if "created_at" in data:
            shipment.created_at = datetime.fromisoformat(data["created_at"])
        if "updated_at" in data:
            shipment.updated_at = datetime.fromisoformat(data["updated_at"])
        
        return shipment


# ========== 领域工厂 ==========

class ShipmentFactory:
    """发货单工厂"""
    
    @staticmethod
    def create(
        unit_name: str,
        items: List[Dict[str, Any]],
        created_by: Optional[str] = None,
    ) -> Shipment:
        """创建新发货单"""
        shipment_id = f"SH{datetime.now().strftime('%Y%m%d%H%M%S')}{str(uuid4())[:6]}"
        
        shipment_items = [
            ShipmentItem(
                product_id=item["product_id"],
                product_name=item.get("product_name", ""),
                model_number=item.get("model_number", ""),
                quantity=item["quantity"],
                unit_price=item.get("unit_price", 0),
                specification=item.get("specification"),
            )
            for item in items
        ]
        
        return Shipment(
            shipment_id=shipment_id,
            unit_name=unit_name,
            items=shipment_items,
            status=ShipmentStatus.DRAFT,
            created_by=created_by,
        )
    
    @staticmethod
    def create_empty(unit_name: str, created_by: Optional[str] = None) -> Shipment:
        """创建空发货单（用于后续添加项）"""
        shipment_id = f"SH{datetime.now().strftime('%Y%m%d%H%M%S')}{str(uuid4())[:6]}"
        
        return Shipment(
            shipment_id=shipment_id,
            unit_name=unit_name,
            items=[],
            status=ShipmentStatus.DRAFT,
            created_by=created_by,
        )
