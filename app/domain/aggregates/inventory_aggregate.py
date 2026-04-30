"""
Inventory 聚合根 - 富血模型实现

Level 3 领域模型:
- 自包含库存业务规则
- 库存数量准确性保证
- 状态变更时发布领域事件
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from typing import Any, Dict, List, Optional


class InventoryStatus(Enum):
    """库存状态枚举"""
    NORMAL = "normal"           # 正常
    LOW_STOCK = "low_stock"     # 库存不足
    OUT_OF_STOCK = "out_of_stock"  # 缺货
    OVERSTOCK = "overstock"     # 积压
    RESERVED = "reserved"       # 部分预留


class TransactionType(Enum):
    """交易类型枚举"""
    STOCK_IN = "stock_in"           # 入库
    STOCK_OUT = "stock_out"         # 出库
    TRANSFER_IN = "transfer_in"     # 调入
    TRANSFER_OUT = "transfer_out"   # 调出
    ADJUSTMENT = "adjustment"       # 调整
    RESERVE = "reserve"             # 预留
    RELEASE = "release"             # 释放


@dataclass(frozen=True)
class InventoryTransaction:
    """库存交易记录值对象"""
    transaction_type: TransactionType
    quantity: int
    reference_id: Optional[str] = None
    reference_type: Optional[str] = None
    operator: Optional[str] = None
    remark: Optional[str] = None
    timestamp: str = ""
    
    def __post_init__(self):
        if not self.timestamp:
            object.__setattr__(self, 'timestamp', datetime.now().isoformat())


class Inventory:
    """
    库存聚合根（富血模型）
    
    Level 3 领域模型:
    - 自包含库存业务规则
    - 数量一致性保证（总库存 = 可用 + 预留 + 锁定）
    - 库存预警
    - 批次追踪
    """
    
    def __init__(
        self,
        product_id: str,
        warehouse_id: str,
        location_id: Optional[str] = None,
        quantity: int = 0,
        available_quantity: int = 0,
        reserved_quantity: int = 0,
        locked_quantity: int = 0,
        min_stock: int = 0,
        max_stock: Optional[int] = None,
        batch_no: Optional[str] = None,
        unit_price: float = 0.0,
    ):
        self._product_id = product_id
        self._warehouse_id = warehouse_id
        self._location_id = location_id
        self._quantity = quantity
        self._available_quantity = available_quantity
        self._reserved_quantity = reserved_quantity
        self._locked_quantity = locked_quantity
        self._min_stock = min_stock
        self._max_stock = max_stock
        self._batch_no = batch_no
        self._unit_price = unit_price
        
        self._status = InventoryStatus.NORMAL
        self._updated_at = datetime.now()
        self._transactions: List[InventoryTransaction] = []
        
        self._domain_events: List[Dict[str, Any]] = []
        
        # 验证库存一致性
        self._validate_quantity()
        self._update_status()
    
    # ========== 属性访问器 ==========
    
    @property
    def product_id(self) -> str:
        return self._product_id
    
    @property
    def warehouse_id(self) -> str:
        return self._warehouse_id
    
    @property
    def location_id(self) -> Optional[str]:
        return self._location_id
    
    @property
    def quantity(self) -> int:
        """总库存数量"""
        return self._quantity
    
    @property
    def available_quantity(self) -> int:
        """可用库存数量"""
        return self._available_quantity
    
    @property
    def reserved_quantity(self) -> int:
        """预留库存数量"""
        return self._reserved_quantity
    
    @property
    def locked_quantity(self) -> int:
        """锁定库存数量（用于正在处理中的订单）"""
        return self._locked_quantity
    
    @property
    def status(self) -> InventoryStatus:
        return self._status
    
    @property
    def is_available(self) -> bool:
        """是否有可用库存"""
        return self._available_quantity > 0
    
    @property
    def is_low_stock(self) -> bool:
        """是否库存不足"""
        return self._available_quantity <= self._min_stock
    
    @property
    def domain_events(self) -> List[Dict[str, Any]]:
        """获取领域事件并清空"""
        events = self._domain_events.copy()
        self._domain_events.clear()
        return events
    
    # ========== 领域方法 ==========
    
    def stock_in(self, quantity: int, unit_price: Optional[float] = None,
                 reference_type: Optional[str] = None, reference_id: Optional[str] = None,
                 operator: Optional[str] = None, remark: Optional[str] = None) -> None:
        """入库"""
        if quantity <= 0:
            raise ValueError("入库数量必须大于0")
        
        # 更新数量
        self._quantity += quantity
        self._available_quantity += quantity
        
        # 更新成本价（加权平均）
        if unit_price and self._quantity > 0:
            current_value = self._unit_price * (self._quantity - quantity)
            new_value = unit_price * quantity
            self._unit_price = (current_value + new_value) / self._quantity
        
        # 记录交易
        transaction = InventoryTransaction(
            transaction_type=TransactionType.STOCK_IN,
            quantity=quantity,
            reference_type=reference_type,
            reference_id=reference_id,
            operator=operator,
            remark=remark
        )
        self._transactions.append(transaction)
        
        self._updated_at = datetime.now()
        self._update_status()
        
        self._record_event("inventory.stock_in", {
            "product_id": self._product_id,
            "warehouse_id": self._warehouse_id,
            "quantity": quantity,
            "new_total": self._quantity,
            "reference_type": reference_type,
            "reference_id": reference_id
        })
    
    def stock_out(self, quantity: int, reference_type: Optional[str] = None,
                  reference_id: Optional[str] = None, operator: Optional[str] = None,
                  remark: Optional[str] = None) -> None:
        """出库"""
        if quantity <= 0:
            raise ValueError("出库数量必须大于0")
        
        if quantity > self._available_quantity:
            raise ValueError(f"可用库存不足: 需要 {quantity}, 可用 {self._available_quantity}")
        
        # 更新数量
        self._quantity -= quantity
        self._available_quantity -= quantity
        
        # 记录交易
        transaction = InventoryTransaction(
            transaction_type=TransactionType.STOCK_OUT,
            quantity=-quantity,  # 负值表示出库
            reference_type=reference_type,
            reference_id=reference_id,
            operator=operator,
            remark=remark
        )
        self._transactions.append(transaction)
        
        self._updated_at = datetime.now()
        self._update_status()
        
        self._record_event("inventory.stock_out", {
            "product_id": self._product_id,
            "warehouse_id": self._warehouse_id,
            "quantity": quantity,
            "new_total": self._quantity,
            "reference_type": reference_type,
            "reference_id": reference_id
        })
    
    def reserve(self, quantity: int, reference_id: str) -> None:
        """预留库存"""
        if quantity <= 0:
            raise ValueError("预留数量必须大于0")
        
        if quantity > self._available_quantity:
            raise ValueError(f"可用库存不足: 需要 {quantity}, 可用 {self._available_quantity}")
        
        self._available_quantity -= quantity
        self._reserved_quantity += quantity
        
        transaction = InventoryTransaction(
            transaction_type=TransactionType.RESERVE,
            quantity=quantity,
            reference_id=reference_id,
            remark=f"预留库存: {reference_id}"
        )
        self._transactions.append(transaction)
        
        self._updated_at = datetime.now()
        self._update_status()
        
        self._record_event("inventory.reserved", {
            "product_id": self._product_id,
            "warehouse_id": self._warehouse_id,
            "quantity": quantity,
            "reference_id": reference_id,
            "available": self._available_quantity,
            "reserved": self._reserved_quantity
        })
    
    def release(self, quantity: int, reference_id: str) -> None:
        """释放预留库存"""
        if quantity <= 0:
            raise ValueError("释放数量必须大于0")
        
        if quantity > self._reserved_quantity:
            raise ValueError(f"释放数量超过预留数量: {quantity} > {self._reserved_quantity}")
        
        self._available_quantity += quantity
        self._reserved_quantity -= quantity
        
        transaction = InventoryTransaction(
            transaction_type=TransactionType.RELEASE,
            quantity=quantity,
            reference_id=reference_id,
            remark=f"释放预留: {reference_id}"
        )
        self._transactions.append(transaction)
        
        self._updated_at = datetime.now()
        self._update_status()
        
        self._record_event("inventory.released", {
            "product_id": self._product_id,
            "warehouse_id": self._warehouse_id,
            "quantity": quantity,
            "reference_id": reference_id,
            "available": self._available_quantity,
            "reserved": self._reserved_quantity
        })
    
    def commit_reservation(self, quantity: int, reference_id: str) -> None:
        """确认预留（从预留转为实际出库）"""
        if quantity <= 0:
            raise ValueError("确认数量必须大于0")
        
        if quantity > self._reserved_quantity:
            raise ValueError(f"确认数量超过预留数量: {quantity} > {self._reserved_quantity}")
        
        # 从预留中扣除
        self._reserved_quantity -= quantity
        # 从总库存中扣除
        self._quantity -= quantity
        
        transaction = InventoryTransaction(
            transaction_type=TransactionType.STOCK_OUT,
            quantity=-quantity,
            reference_id=reference_id,
            remark=f"确认预留出库: {reference_id}"
        )
        self._transactions.append(transaction)
        
        self._updated_at = datetime.now()
        self._update_status()
        
        self._record_event("inventory.reservation_committed", {
            "product_id": self._product_id,
            "warehouse_id": self._warehouse_id,
            "quantity": quantity,
            "reference_id": reference_id,
            "new_total": self._quantity,
            "reserved": self._reserved_quantity
        })
    
    def adjust(self, new_quantity: int, reason: str, operator: Optional[str] = None) -> None:
        """库存调整"""
        old_quantity = self._quantity
        delta = new_quantity - old_quantity
        
        if delta == 0:
            return
        
        # 更新数量
        self._quantity = new_quantity
        if delta > 0:
            self._available_quantity += delta
        else:
            # 减少库存，优先从可用库存扣减
            if abs(delta) <= self._available_quantity:
                self._available_quantity -= abs(delta)
            else:
                raise ValueError("可用库存不足以支持此调整")
        
        transaction = InventoryTransaction(
            transaction_type=TransactionType.ADJUSTMENT,
            quantity=delta,
            operator=operator,
            remark=reason
        )
        self._transactions.append(transaction)
        
        self._updated_at = datetime.now()
        self._update_status()
        
        self._record_event("inventory.adjusted", {
            "product_id": self._product_id,
            "warehouse_id": self._warehouse_id,
            "old_quantity": old_quantity,
            "new_quantity": new_quantity,
            "delta": delta,
            "reason": reason
        })
    
    def transfer_in(self, quantity: int, from_warehouse: str, transfer_id: str) -> None:
        """调入库存"""
        if quantity <= 0:
            raise ValueError("调入数量必须大于0")
        
        self._quantity += quantity
        self._available_quantity += quantity
        
        transaction = InventoryTransaction(
            transaction_type=TransactionType.TRANSFER_IN,
            quantity=quantity,
            reference_id=transfer_id,
            remark=f"从 {from_warehouse} 调入"
        )
        self._transactions.append(transaction)
        
        self._updated_at = datetime.now()
        self._update_status()
        
        self._record_event("inventory.transfer_in", {
            "product_id": self._product_id,
            "warehouse_id": self._warehouse_id,
            "from_warehouse": from_warehouse,
            "quantity": quantity,
            "transfer_id": transfer_id
        })
    
    def transfer_out(self, quantity: int, to_warehouse: str, transfer_id: str) -> None:
        """调出库存"""
        if quantity <= 0:
            raise ValueError("调出数量必须大于0")
        
        if quantity > self._available_quantity:
            raise ValueError(f"可用库存不足: 需要 {quantity}, 可用 {self._available_quantity}")
        
        self._quantity -= quantity
        self._available_quantity -= quantity
        
        transaction = InventoryTransaction(
            transaction_type=TransactionType.TRANSFER_OUT,
            quantity=-quantity,
            reference_id=transfer_id,
            remark=f"调出至 {to_warehouse}"
        )
        self._transactions.append(transaction)
        
        self._updated_at = datetime.now()
        self._update_status()
        
        self._record_event("inventory.transfer_out", {
            "product_id": self._product_id,
            "warehouse_id": self._warehouse_id,
            "to_warehouse": to_warehouse,
            "quantity": quantity,
            "transfer_id": transfer_id
        })
    
    # ========== 内部方法 ==========
    
    def _validate_quantity(self) -> None:
        """验证库存数量一致性"""
        expected = self._available_quantity + self._reserved_quantity + self._locked_quantity
        if self._quantity != expected:
            raise ValueError(f"库存数量不一致: 总计 {self._quantity} != 可用 {self._available_quantity} + 预留 {self._reserved_quantity} + 锁定 {self._locked_quantity}")
        
        if self._available_quantity < 0 or self._reserved_quantity < 0 or self._locked_quantity < 0:
            raise ValueError("库存数量不能为负数")
    
    def _update_status(self) -> None:
        """更新库存状态"""
        old_status = self._status
        
        if self._available_quantity <= 0:
            self._status = InventoryStatus.OUT_OF_STOCK
        elif self._available_quantity <= self._min_stock:
            self._status = InventoryStatus.LOW_STOCK
        elif self._max_stock and self._quantity > self._max_stock:
            self._status = InventoryStatus.OVERSTOCK
        elif self._reserved_quantity > 0:
            self._status = InventoryStatus.RESERVED
        else:
            self._status = InventoryStatus.NORMAL
        
        # 触发预警事件
        if old_status != self._status and self._status == InventoryStatus.LOW_STOCK:
            self._record_event("inventory.low_stock_alert", {
                "product_id": self._product_id,
                "warehouse_id": self._warehouse_id,
                "current_stock": self._available_quantity,
                "threshold": self._min_stock
            })
    
    def _record_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        """记录领域事件"""
        self._domain_events.append({
            "event_type": event_type,
            "payload": payload,
            "timestamp": datetime.now().isoformat()
        })
    
    # ========== 序列化/反序列化 ==========
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "product_id": self._product_id,
            "warehouse_id": self._warehouse_id,
            "location_id": self._location_id,
            "quantity": self._quantity,
            "available_quantity": self._available_quantity,
            "reserved_quantity": self._reserved_quantity,
            "locked_quantity": self._locked_quantity,
            "min_stock": self._min_stock,
            "max_stock": self._max_stock,
            "batch_no": self._batch_no,
            "unit_price": self._unit_price,
            "status": self._status.value,
            "updated_at": self._updated_at.isoformat(),
            "recent_transactions": [t.__dict__ for t in self._transactions[-5:]]
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Inventory':
        """从字典恢复库存"""
        inventory = cls(
            product_id=data["product_id"],
            warehouse_id=data["warehouse_id"],
            location_id=data.get("location_id"),
            quantity=data.get("quantity", 0),
            available_quantity=data.get("available_quantity", 0),
            reserved_quantity=data.get("reserved_quantity", 0),
            locked_quantity=data.get("locked_quantity", 0),
            min_stock=data.get("min_stock", 0),
            max_stock=data.get("max_stock"),
            batch_no=data.get("batch_no"),
            unit_price=data.get("unit_price", 0.0)
        )
        
        inventory._status = InventoryStatus(data.get("status", "normal"))
        
        return inventory


class InventoryFactory:
    """库存工厂"""
    
    @staticmethod
    def create_inventory(
        product_id: str,
        warehouse_id: str,
        location_id: Optional[str] = None,
        initial_quantity: int = 0,
        min_stock: int = 0,
        max_stock: Optional[int] = None,
        batch_no: Optional[str] = None
    ) -> Inventory:
        """创建新库存记录"""
        return Inventory(
            product_id=product_id,
            warehouse_id=warehouse_id,
            location_id=location_id,
            quantity=initial_quantity,
            available_quantity=initial_quantity,
            reserved_quantity=0,
            locked_quantity=0,
            min_stock=min_stock,
            max_stock=max_stock,
            batch_no=batch_no
        )
