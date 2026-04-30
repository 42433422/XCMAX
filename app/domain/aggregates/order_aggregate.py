"""
Order 聚合根 - 富血模型实现

Level 3 领域模型:
- 自包含订单业务规则
- 状态变更时发布领域事件
- 维护聚合边界内的一致性
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum, auto
from typing import Any, Dict, List, Optional


class OrderStatus(Enum):
    """订单状态枚举"""
    DRAFT = "draft"           # 草稿
    SUBMITTED = "submitted"   # 已提交
    CONFIRMED = "confirmed"   # 已确认
    PAID = "paid"             # 已支付
    PROCESSING = "processing" # 处理中
    SHIPPED = "shipped"       # 已发货
    FULFILLED = "fulfilled"   # 已完成
    CANCELLED = "cancelled"   # 已取消
    REFUNDED = "refunded"     # 已退款


class PaymentStatus(Enum):
    """支付状态枚举"""
    PENDING = "pending"       # 待支付
    PAID = "paid"             # 已支付
    PARTIAL = "partial"       # 部分支付
    FAILED = "failed"         # 支付失败
    REFUNDED = "refunded"     # 已退款
    PARTIAL_REFUNDED = "partial_refunded"  # 部分退款


@dataclass(frozen=True)
class Money:
    """金额值对象"""
    amount: Decimal
    currency: str = "CNY"
    
    def __post_init__(self):
        if self.amount < 0:
            raise ValueError("金额不能为负数")
    
    def add(self, other: 'Money') -> 'Money':
        """金额相加"""
        if self.currency != other.currency:
            raise ValueError("货币类型不匹配")
        return Money(self.amount + other.amount, self.currency)
    
    def subtract(self, other: 'Money') -> 'Money':
        """金额相减"""
        if self.currency != other.currency:
            raise ValueError("货币类型不匹配")
        result = self.amount - other.amount
        if result < 0:
            raise ValueError("金额不足")
        return Money(result, self.currency)
    
    def multiply(self, quantity: int) -> 'Money':
        """金额乘以数量"""
        return Money(self.amount * quantity, self.currency)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "amount": float(self.amount),
            "currency": self.currency
        }


@dataclass(frozen=True)
class OrderItem:
    """订单项值对象"""
    product_id: str
    product_name: str
    model_number: str
    quantity: int
    unit_price: Money
    specification: Optional[str] = None
    remark: Optional[str] = None
    
    def __post_init__(self):
        if self.quantity <= 0:
            raise ValueError("数量必须大于0")
    
    @property
    def subtotal(self) -> Money:
        """计算小计"""
        return self.unit_price.multiply(self.quantity)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "product_id": self.product_id,
            "product_name": self.product_name,
            "model_number": self.model_number,
            "quantity": self.quantity,
            "unit_price": self.unit_price.to_dict(),
            "specification": self.specification,
            "remark": self.remark,
            "subtotal": self.subtotal.to_dict()
        }


class Order:
    """
    订单聚合根（富血模型）
    
    Level 3 领域模型:
    - 自包含订单业务规则
    - 状态转换验证
    - 金额计算准确性
    - 领域事件发布
    """
    
    def __init__(
        self,
        order_id: str,
        customer_id: str,
        customer_name: str,
        items: Optional[List[OrderItem]] = None,
        status: OrderStatus = OrderStatus.DRAFT,
        remark: Optional[str] = None,
        created_by: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self._order_id = order_id
        self._customer_id = customer_id
        self._customer_name = customer_name
        self._items: List[OrderItem] = items or []
        self._status = status
        self._payment_status = PaymentStatus.PENDING
        self._remark = remark
        self._created_by = created_by
        self._metadata = metadata or {}
        
        self._created_at = datetime.now()
        self._updated_at = datetime.now()
        self._submitted_at: Optional[datetime] = None
        self._confirmed_at: Optional[datetime] = None
        self._paid_at: Optional[datetime] = None
        self._shipped_at: Optional[datetime] = None
        self._fulfilled_at: Optional[datetime] = None
        self._cancelled_at: Optional[datetime] = None
        self._cancel_reason: Optional[str] = None
        
        self._payments: List[Dict[str, Any]] = []
        self._shipments: List[Dict[str, Any]] = []
        self._refunds: List[Dict[str, Any]] = []
        
        self._domain_events: List[Dict[str, Any]] = []
        
        # 验证并记录创建事件
        self._validate()
        self._record_event("order.created", {
            "order_id": self._order_id,
            "customer_id": self._customer_id,
            "customer_name": self._customer_name,
            "item_count": len(self._items),
            "total_amount": float(self.total_amount.amount) if self._items else 0
        })
    
    # ========== 属性访问器 ==========
    
    @property
    def order_id(self) -> str:
        return self._order_id
    
    @property
    def customer_id(self) -> str:
        return self._customer_id
    
    @property
    def customer_name(self) -> str:
        return self._customer_name
    
    @property
    def status(self) -> OrderStatus:
        return self._status
    
    @property
    def payment_status(self) -> PaymentStatus:
        return self._payment_status
    
    @property
    def items(self) -> List[OrderItem]:
        return list(self._items)  # 返回副本防止外部修改
    
    @property
    def total_amount(self) -> Money:
        """计算订单总金额"""
        total = Money(Decimal("0"))
        for item in self._items:
            total = total.add(item.subtotal)
        return total
    
    @property
    def paid_amount(self) -> Money:
        """已支付金额"""
        total = Decimal("0")
        for payment in self._payments:
            total += Decimal(str(payment.get("amount", 0)))
        return Money(total)
    
    @property
    def refund_amount(self) -> Money:
        """已退款金额"""
        total = Decimal("0")
        for refund in self._refunds:
            total += Decimal(str(refund.get("amount", 0)))
        return Money(total)
    
    @property
    def outstanding_amount(self) -> Money:
        """未付金额"""
        return self.total_amount.subtract(self.paid_amount)
    
    @property
    def is_paid(self) -> bool:
        """是否已全额支付"""
        return self._payment_status == PaymentStatus.PAID
    
    @property
    def is_cancelled(self) -> bool:
        return self._status == OrderStatus.CANCELLED
    
    @property
    def is_fulfilled(self) -> bool:
        return self._status == OrderStatus.FULFILLED
    
    @property
    def domain_events(self) -> List[Dict[str, Any]]:
        """获取领域事件并清空"""
        events = self._domain_events.copy()
        self._domain_events.clear()
        return events
    
    # ========== 领域方法 ==========
    
    def add_item(self, item: OrderItem) -> None:
        """添加订单项"""
        if self._status not in (OrderStatus.DRAFT, OrderStatus.SUBMITTED):
            raise ValueError(f"当前状态 {self._status.value} 不允许添加订单项")
        
        # 检查是否已存在相同产品
        existing = next((i for i in self._items if i.product_id == item.product_id), None)
        if existing:
            raise ValueError(f"产品 {item.product_name} 已存在于订单中")
        
        self._items.append(item)
        self._updated_at = datetime.now()
        
        self._record_event("order.item_added", {
            "order_id": self._order_id,
            "product_id": item.product_id,
            "product_name": item.product_name,
            "quantity": item.quantity
        })
    
    def remove_item(self, product_id: str) -> None:
        """移除订单项"""
        if self._status not in (OrderStatus.DRAFT, OrderStatus.SUBMITTED):
            raise ValueError(f"当前状态 {self._status.value} 不允许移除订单项")
        
        item = next((i for i in self._items if i.product_id == product_id), None)
        if not item:
            raise ValueError(f"产品 {product_id} 不存在于订单中")
        
        self._items.remove(item)
        self._updated_at = datetime.now()
        
        self._record_event("order.item_removed", {
            "order_id": self._order_id,
            "product_id": product_id,
            "product_name": item.product_name
        })
    
    def submit(self) -> None:
        """提交订单"""
        if self._status != OrderStatus.DRAFT:
            raise ValueError(f"当前状态 {self._status.value} 不允许提交")
        
        if not self._items:
            raise ValueError("订单不能为空")
        
        self._status = OrderStatus.SUBMITTED
        self._submitted_at = datetime.now()
        self._updated_at = datetime.now()
        
        self._record_event("order.submitted", {
            "order_id": self._order_id,
            "customer_id": self._customer_id,
            "total_amount": float(self.total_amount.amount),
            "item_count": len(self._items)
        })
    
    def confirm(self, confirmed_by: Optional[str] = None) -> None:
        """确认订单"""
        if self._status != OrderStatus.SUBMITTED:
            raise ValueError(f"当前状态 {self._status.value} 不允许确认")
        
        self._status = OrderStatus.CONFIRMED
        self._confirmed_at = datetime.now()
        self._updated_at = datetime.now()
        
        self._record_event("order.confirmed", {
            "order_id": self._order_id,
            "confirmed_by": confirmed_by,
            "confirmed_at": self._confirmed_at.isoformat()
        })
    
    def pay(self, amount: Money, payment_method: str, 
            transaction_id: Optional[str] = None,
            paid_by: Optional[str] = None) -> None:
        """支付订单"""
        if self._status not in (OrderStatus.CONFIRMED, OrderStatus.SUBMITTED, OrderStatus.PROCESSING):
            raise ValueError(f"当前状态 {self._status.value} 不允许支付")
        
        if self._status == OrderStatus.CANCELLED:
            raise ValueError("已取消的订单不能支付")
        
        # 记录支付
        payment = {
            "payment_id": f"PAY{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "amount": float(amount.amount),
            "currency": amount.currency,
            "payment_method": payment_method,
            "transaction_id": transaction_id,
            "paid_by": paid_by,
            "paid_at": datetime.now().isoformat()
        }
        self._payments.append(payment)
        
        # 更新支付状态
        total_paid = self.paid_amount
        if total_paid.amount >= self.total_amount.amount:
            self._payment_status = PaymentStatus.PAID
        elif total_paid.amount > 0:
            self._payment_status = PaymentStatus.PARTIAL
        
        self._paid_at = datetime.now()
        self._updated_at = datetime.now()
        
        # 如果已确认且已支付，进入处理中状态
        if self._status == OrderStatus.CONFIRMED and self._payment_status == PaymentStatus.PAID:
            self._status = OrderStatus.PAID
        
        self._record_event("order.paid", {
            "order_id": self._order_id,
            "payment_id": payment["payment_id"],
            "amount": float(amount.amount),
            "payment_method": payment_method,
            "total_paid": float(total_paid.amount),
            "outstanding": float(self.outstanding_amount.amount)
        })
    
    def mark_shipped(self, shipment_id: str, tracking_number: str,
                     carrier: str, shipped_by: Optional[str] = None) -> None:
        """标记订单发货"""
        if self._status not in (OrderStatus.PAID, OrderStatus.PROCESSING):
            raise ValueError(f"当前状态 {self._status.value} 不允许发货")
        
        shipment = {
            "shipment_id": shipment_id,
            "tracking_number": tracking_number,
            "carrier": carrier,
            "shipped_by": shipped_by,
            "shipped_at": datetime.now().isoformat()
        }
        self._shipments.append(shipment)
        
        self._status = OrderStatus.SHIPPED
        self._shipped_at = datetime.now()
        self._updated_at = datetime.now()
        
        self._record_event("order.shipped", {
            "order_id": self._order_id,
            "shipment_id": shipment_id,
            "tracking_number": tracking_number,
            "carrier": carrier
        })
    
    def fulfill(self, completed_by: Optional[str] = None) -> None:
        """完成订单"""
        if self._status not in (OrderStatus.SHIPPED, OrderStatus.PAID, OrderStatus.PROCESSING):
            raise ValueError(f"当前状态 {self._status.value} 不允许完成")
        
        self._status = OrderStatus.FULFILLED
        self._fulfilled_at = datetime.now()
        self._updated_at = datetime.now()
        
        self._record_event("order.fulfilled", {
            "order_id": self._order_id,
            "completed_by": completed_by,
            "completed_at": self._fulfilled_at.isoformat()
        })
    
    def cancel(self, reason: Optional[str] = None, cancelled_by: Optional[str] = None) -> None:
        """取消订单"""
        if self._status in (OrderStatus.FULFILLED, OrderStatus.CANCELLED):
            raise ValueError(f"当前状态 {self._status.value} 不允许取消")
        
        # 如果已支付，需要退款
        if self._payment_status == PaymentStatus.PAID:
            raise ValueError("已支付订单请先退款再取消")
        
        self._status = OrderStatus.CANCELLED
        self._cancel_reason = reason
        self._cancelled_at = datetime.now()
        self._updated_at = datetime.now()
        
        self._record_event("order.cancelled", {
            "order_id": self._order_id,
            "reason": reason,
            "cancelled_by": cancelled_by,
            "cancelled_at": self._cancelled_at.isoformat()
        })
    
    def refund(self, amount: Money, reason: str, refunded_by: Optional[str] = None) -> None:
        """退款"""
        if self._payment_status not in (PaymentStatus.PAID, PaymentStatus.PARTIAL):
            raise ValueError("订单未支付，无法退款")
        
        if amount.amount > self.paid_amount.amount:
            raise ValueError("退款金额不能超过已支付金额")
        
        refund = {
            "refund_id": f"REF{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "amount": float(amount.amount),
            "reason": reason,
            "refunded_by": refunded_by,
            "refunded_at": datetime.now().isoformat()
        }
        self._refunds.append(refund)
        
        # 更新支付状态
        total_refunded = self.refund_amount
        if total_refunded.amount >= self.paid_amount.amount:
            self._payment_status = PaymentStatus.REFUNDED
        else:
            self._payment_status = PaymentStatus.PARTIAL_REFUNDED
        
        self._updated_at = datetime.now()
        
        self._record_event("order.refunded", {
            "order_id": self._order_id,
            "refund_id": refund["refund_id"],
            "amount": float(amount.amount),
            "reason": reason,
            "total_refunded": float(total_refunded.amount)
        })
    
    # ========== 内部方法 ==========
    
    def _validate(self) -> None:
        """验证订单有效性"""
        if not self._order_id:
            raise ValueError("订单ID不能为空")
        if not self._customer_id:
            raise ValueError("客户ID不能为空")
    
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
            "order_id": self._order_id,
            "customer_id": self._customer_id,
            "customer_name": self._customer_name,
            "status": self._status.value,
            "payment_status": self._payment_status.value,
            "items": [item.to_dict() for item in self._items],
            "total_amount": self.total_amount.to_dict(),
            "paid_amount": self.paid_amount.to_dict(),
            "outstanding_amount": self.outstanding_amount.to_dict(),
            "remark": self._remark,
            "created_by": self._created_by,
            "created_at": self._created_at.isoformat(),
            "updated_at": self._updated_at.isoformat(),
            "submitted_at": self._submitted_at.isoformat() if self._submitted_at else None,
            "confirmed_at": self._confirmed_at.isoformat() if self._confirmed_at else None,
            "paid_at": self._paid_at.isoformat() if self._paid_at else None,
            "shipped_at": self._shipped_at.isoformat() if self._shipped_at else None,
            "fulfilled_at": self._fulfilled_at.isoformat() if self._fulfilled_at else None,
            "cancelled_at": self._cancelled_at.isoformat() if self._cancelled_at else None,
            "cancel_reason": self._cancel_reason,
            "payments": self._payments,
            "shipments": self._shipments,
            "refunds": self._refunds,
            "metadata": self._metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Order':
        """从字典恢复订单"""
        items = []
        for item_data in data.get("items", []):
            unit_price_data = item_data.get("unit_price", {})
            unit_price = Money(
                Decimal(str(unit_price_data.get("amount", 0))),
                unit_price_data.get("currency", "CNY")
            )
            items.append(OrderItem(
                product_id=item_data["product_id"],
                product_name=item_data["product_name"],
                model_number=item_data["model_number"],
                quantity=item_data["quantity"],
                unit_price=unit_price,
                specification=item_data.get("specification"),
                remark=item_data.get("remark")
            ))
        
        order = cls(
            order_id=data["order_id"],
            customer_id=data["customer_id"],
            customer_name=data.get("customer_name", ""),
            items=items,
            status=OrderStatus(data.get("status", "draft")),
            remark=data.get("remark"),
            created_by=data.get("created_by"),
            metadata=data.get("metadata", {})
        )
        
        # 恢复支付状态
        order._payment_status = PaymentStatus(data.get("payment_status", "pending"))
        order._payments = data.get("payments", [])
        order._shipments = data.get("shipments", [])
        order._refunds = data.get("refunds", [])
        
        return order


class OrderFactory:
    """订单工厂"""
    
    @staticmethod
    def create_order(
        customer_id: str,
        customer_name: str,
        items: List[Dict[str, Any]],
        remark: Optional[str] = None,
        created_by: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Order:
        """创建新订单"""
        order_id = f"ORD{datetime.now().strftime('%Y%m%d%H%M%S')}{id(object()) % 1000:03d}"
        
        order_items = []
        for item_data in items:
            unit_price = Decimal(str(item_data.get("unit_price", 0)))
            order_items.append(OrderItem(
                product_id=item_data["product_id"],
                product_name=item_data.get("product_name", ""),
                model_number=item_data.get("model_number", ""),
                quantity=item_data.get("quantity", 1),
                unit_price=Money(unit_price),
                specification=item_data.get("specification"),
                remark=item_data.get("remark")
            ))
        
        return Order(
            order_id=order_id,
            customer_id=customer_id,
            customer_name=customer_name,
            items=order_items,
            status=OrderStatus.DRAFT,
            remark=remark,
            created_by=created_by,
            metadata=metadata
        )
