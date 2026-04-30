"""
Customer 聚合根 - 富血模型实现

Level 3 领域模型:
- 自包含客户业务规则
- 状态变更时发布领域事件
- 维护聚合边界内的一致性
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Set


class CustomerStatus(Enum):
    """客户状态枚举"""
    ACTIVE = "active"         # 活跃
    INACTIVE = "inactive"     # 非活跃
    SUSPENDED = "suspended"   # 暂停
    DEACTIVATED = "deactivated"  # 停用


class CustomerLevel(Enum):
    """客户等级枚举"""
    REGULAR = "regular"       # 普通
    BRONZE = "bronze"         # 青铜
    SILVER = "silver"         # 白银
    GOLD = "gold"             # 黄金
    PLATINUM = "platinum"     # 铂金


@dataclass(frozen=True)
class ContactInfo:
    """联系信息值对象"""
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    wechat_id: Optional[str] = None
    
    def __post_init__(self):
        if self.phone:
            # 简单验证手机号格式
            phone = self.phone.strip().replace("-", "").replace(" ", "")
            if not phone.isdigit() or len(phone) < 7:
                raise ValueError(f"无效的电话号码: {self.phone}")
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "phone": self.phone,
            "email": self.email,
            "address": self.address,
            "wechat_id": self.wechat_id
        }


@dataclass(frozen=True)
class PurchasePreference:
    """购买偏好值对象"""
    preferred_products: List[str] = field(default_factory=list)
    preferred_units: List[str] = field(default_factory=list)
    payment_terms: Optional[str] = None  # 付款条件
    delivery_requirements: Optional[str] = None  # 交付要求
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "preferred_products": list(self.preferred_products),
            "preferred_units": list(self.preferred_units),
            "payment_terms": self.payment_terms,
            "delivery_requirements": self.delivery_requirements
        }


class Customer:
    """
    客户聚合根（富血模型）
    
    Level 3 领域模型:
    - 自包含客户业务规则
    - 状态转换验证
    - 信用额度管理
    - 购买历史追踪
    - 领域事件发布
    """
    
    def __init__(
        self,
        customer_id: str,
        customer_name: str,
        contact_info: Optional[ContactInfo] = None,
        purchase_unit: Optional[str] = None,
        status: CustomerStatus = CustomerStatus.ACTIVE,
        level: CustomerLevel = CustomerLevel.REGULAR,
        credit_limit: float = 0.0,
        remark: Optional[str] = None,
        created_by: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self._customer_id = customer_id
        self._customer_name = customer_name
        self._contact_info = contact_info or ContactInfo()
        self._purchase_units: Set[str] = {purchase_unit} if purchase_unit else set()
        self._status = status
        self._level = level
        self._credit_limit = credit_limit
        self._current_credit = 0.0  # 当前已用信用额度
        self._remark = remark
        self._created_by = created_by
        self._metadata = metadata or {}
        
        self._created_at = datetime.now()
        self._updated_at = datetime.now()
        self._last_order_at: Optional[datetime] = None
        self._total_orders = 0
        self._total_amount = 0.0
        
        self._preferences = PurchasePreference()
        self._order_history: List[Dict[str, Any]] = []
        self._notes: List[Dict[str, Any]] = []  # 客户备注记录
        
        self._domain_events: List[Dict[str, Any]] = []
        
        # 验证并记录创建事件
        self._validate()
        self._record_event("customer.created", {
            "customer_id": self._customer_id,
            "customer_name": self._customer_name,
            "purchase_unit": purchase_unit,
            "status": self._status.value
        })
    
    # ========== 属性访问器 ==========
    
    @property
    def customer_id(self) -> str:
        return self._customer_id
    
    @property
    def customer_name(self) -> str:
        return self._customer_name
    
    @customer_name.setter
    def customer_name(self, value: str) -> None:
        if not value or not value.strip():
            raise ValueError("客户名称不能为空")
        old_name = self._customer_name
        self._customer_name = value.strip()
        self._updated_at = datetime.now()
        self._record_event("customer.name_changed", {
            "customer_id": self._customer_id,
            "old_name": old_name,
            "new_name": value.strip()
        })
    
    @property
    def status(self) -> CustomerStatus:
        return self._status
    
    @property
    def level(self) -> CustomerLevel:
        return self._level
    
    @property
    def contact_info(self) -> ContactInfo:
        return self._contact_info
    
    @property
    def purchase_units(self) -> Set[str]:
        return set(self._purchase_units)
    
    @property
    def credit_limit(self) -> float:
        return self._credit_limit
    
    @property
    def available_credit(self) -> float:
        """可用信用额度"""
        return max(0, self._credit_limit - self._current_credit)
    
    @property
    def is_active(self) -> bool:
        return self._status == CustomerStatus.ACTIVE
    
    @property
    def domain_events(self) -> List[Dict[str, Any]]:
        """获取领域事件并清空"""
        events = self._domain_events.copy()
        self._domain_events.clear()
        return events
    
    # ========== 领域方法 ==========
    
    def update_contact_info(self, contact_info: ContactInfo) -> None:
        """更新联系信息"""
        old_info = self._contact_info
        self._contact_info = contact_info
        self._updated_at = datetime.now()
        
        self._record_event("customer.contact_info_updated", {
            "customer_id": self._customer_id,
            "old_phone": old_info.phone,
            "new_phone": contact_info.phone,
            "new_email": contact_info.email
        })
    
    def bind_purchase_unit(self, purchase_unit: str) -> None:
        """绑定购买单位"""
        if not purchase_unit:
            raise ValueError("购买单位不能为空")
        
        if purchase_unit in self._purchase_units:
            raise ValueError(f"客户已绑定单位: {purchase_unit}")
        
        self._purchase_units.add(purchase_unit)
        self._updated_at = datetime.now()
        
        self._record_event("customer.purchase_unit_bound", {
            "customer_id": self._customer_id,
            "purchase_unit": purchase_unit
        })
    
    def unbind_purchase_unit(self, purchase_unit: str) -> None:
        """解绑购买单位"""
        if purchase_unit not in self._purchase_units:
            raise ValueError(f"客户未绑定单位: {purchase_unit}")
        
        if len(self._purchase_units) <= 1:
            raise ValueError("客户必须至少绑定一个单位")
        
        self._purchase_units.discard(purchase_unit)
        self._updated_at = datetime.now()
        
        self._record_event("customer.purchase_unit_unbound", {
            "customer_id": self._customer_id,
            "purchase_unit": purchase_unit
        })
    
    def update_preferences(self, preferences: PurchasePreference) -> None:
        """更新购买偏好"""
        self._preferences = preferences
        self._updated_at = datetime.now()
        
        self._record_event("customer.preferences_updated", {
            "customer_id": self._customer_id,
            "preferred_units": list(preferences.preferred_units),
            "payment_terms": preferences.payment_terms
        })
    
    def set_credit_limit(self, limit: float) -> None:
        """设置信用额度"""
        if limit < 0:
            raise ValueError("信用额度不能为负数")
        
        if limit < self._current_credit:
            raise ValueError(f"信用额度不能低于当前已用额度 {self._current_credit}")
        
        old_limit = self._credit_limit
        self._credit_limit = limit
        self._updated_at = datetime.now()
        
        self._record_event("customer.credit_limit_changed", {
            "customer_id": self._customer_id,
            "old_limit": old_limit,
            "new_limit": limit
        })
    
    def use_credit(self, amount: float) -> None:
        """使用信用额度"""
        if amount <= 0:
            raise ValueError("使用额度必须为正数")
        
        if amount > self.available_credit:
            raise ValueError(f"可用额度不足: 需要 {amount}, 可用 {self.available_credit}")
        
        self._current_credit += amount
        self._updated_at = datetime.now()
        
        self._record_event("customer.credit_used", {
            "customer_id": self._customer_id,
            "amount": amount,
            "current_credit": self._current_credit,
            "available_credit": self.available_credit
        })
    
    def release_credit(self, amount: float) -> None:
        """释放信用额度"""
        if amount <= 0:
            raise ValueError("释放额度必须为正数")
        
        if amount > self._current_credit:
            raise ValueError(f"释放额度不能超过已用额度 {self._current_credit}")
        
        self._current_credit -= amount
        self._updated_at = datetime.now()
        
        self._record_event("customer.credit_released", {
            "customer_id": self._customer_id,
            "amount": amount,
            "current_credit": self._current_credit,
            "available_credit": self.available_credit
        })
    
    def record_order(self, order_id: str, amount: float, order_date: Optional[datetime] = None) -> None:
        """记录订单历史"""
        order_record = {
            "order_id": order_id,
            "amount": amount,
            "order_date": (order_date or datetime.now()).isoformat()
        }
        self._order_history.append(order_record)
        self._total_orders += 1
        self._total_amount += amount
        self._last_order_at = order_date or datetime.now()
        self._updated_at = datetime.now()
        
        # 自动升级客户等级
        self._auto_upgrade_level()
        
        self._record_event("customer.order_recorded", {
            "customer_id": self._customer_id,
            "order_id": order_id,
            "amount": amount,
            "total_orders": self._total_orders
        })
    
    def _auto_upgrade_level(self) -> None:
        """根据订单历史自动升级客户等级"""
        old_level = self._level
        
        # 简单的升级规则
        if self._total_amount >= 1000000:  # 100万
            self._level = CustomerLevel.PLATINUM
        elif self._total_amount >= 500000:  # 50万
            self._level = CustomerLevel.GOLD
        elif self._total_amount >= 100000:  # 10万
            self._level = CustomerLevel.SILVER
        elif self._total_amount >= 50000:  # 5万
            self._level = CustomerLevel.BRONZE
        
        if self._level != old_level:
            self._record_event("customer.level_upgraded", {
                "customer_id": self._customer_id,
                "old_level": old_level.value,
                "new_level": self._level.value,
                "total_amount": self._total_amount
            })
    
    def add_note(self, content: str, author: Optional[str] = None) -> None:
        """添加客户备注"""
        note = {
            "content": content,
            "author": author,
            "created_at": datetime.now().isoformat()
        }
        self._notes.append(note)
        self._updated_at = datetime.now()
        
        self._record_event("customer.note_added", {
            "customer_id": self._customer_id,
            "note_id": len(self._notes) - 1,
            "author": author
        })
    
    def deactivate(self, reason: Optional[str] = None) -> None:
        """停用客户"""
        if self._status == CustomerStatus.DEACTIVATED:
            raise ValueError("客户已停用")
        
        if self._current_credit > 0:
            raise ValueError(f"客户有未结清信用额度 {self._current_credit}，无法停用")
        
        old_status = self._status
        self._status = CustomerStatus.DEACTIVATED
        self._updated_at = datetime.now()
        
        self._record_event("customer.deactivated", {
            "customer_id": self._customer_id,
            "old_status": old_status.value,
            "reason": reason
        })
    
    def reactivate(self) -> None:
        """重新激活客户"""
        if self._status != CustomerStatus.DEACTIVATED:
            raise ValueError("客户未停用")
        
        old_status = self._status
        self._status = CustomerStatus.ACTIVE
        self._updated_at = datetime.now()
        
        self._record_event("customer.reactivated", {
            "customer_id": self._customer_id,
            "old_status": old_status.value
        })
    
    def suspend(self, reason: str) -> None:
        """暂停客户（临时）"""
        if self._status in (CustomerStatus.DEACTIVATED, CustomerStatus.SUSPENDED):
            raise ValueError(f"客户当前状态 {self._status.value} 不允许暂停")
        
        old_status = self._status
        self._status = CustomerStatus.SUSPENDED
        self._updated_at = datetime.now()
        
        self._record_event("customer.suspended", {
            "customer_id": self._customer_id,
            "old_status": old_status.value,
            "reason": reason
        })
    
    def unsuspend(self) -> None:
        """解除暂停"""
        if self._status != CustomerStatus.SUSPENDED:
            raise ValueError("客户未暂停")
        
        old_status = self._status
        self._status = CustomerStatus.ACTIVE
        self._updated_at = datetime.now()
        
        self._record_event("customer.unsuspended", {
            "customer_id": self._customer_id,
            "old_status": old_status.value
        })
    
    # ========== 内部方法 ==========
    
    def _validate(self) -> None:
        """验证客户有效性"""
        if not self._customer_id:
            raise ValueError("客户ID不能为空")
        if not self._customer_name or not self._customer_name.strip():
            raise ValueError("客户名称不能为空")
    
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
            "customer_id": self._customer_id,
            "customer_name": self._customer_name,
            "contact_info": self._contact_info.to_dict(),
            "purchase_units": list(self._purchase_units),
            "status": self._status.value,
            "level": self._level.value,
            "credit_limit": self._credit_limit,
            "current_credit": self._current_credit,
            "available_credit": self.available_credit,
            "remark": self._remark,
            "created_by": self._created_by,
            "created_at": self._created_at.isoformat(),
            "updated_at": self._updated_at.isoformat(),
            "last_order_at": self._last_order_at.isoformat() if self._last_order_at else None,
            "total_orders": self._total_orders,
            "total_amount": self._total_amount,
            "preferences": self._preferences.to_dict(),
            "order_history": self._order_history[-10:],  # 最近10条
            "notes_count": len(self._notes),
            "metadata": self._metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Customer':
        """从字典恢复客户"""
        contact_info_data = data.get("contact_info", {})
        contact_info = ContactInfo(
            phone=contact_info_data.get("phone"),
            email=contact_info_data.get("email"),
            address=contact_info_data.get("address"),
            wechat_id=contact_info_data.get("wechat_id")
        )
        
        customer = cls(
            customer_id=data["customer_id"],
            customer_name=data["customer_name"],
            contact_info=contact_info,
            purchase_unit=None,  # 从 purchase_units 中恢复
            status=CustomerStatus(data.get("status", "active")),
            level=CustomerLevel(data.get("level", "regular")),
            credit_limit=data.get("credit_limit", 0.0),
            remark=data.get("remark"),
            created_by=data.get("created_by"),
            metadata=data.get("metadata", {})
        )
        
        # 恢复购买单位
        customer._purchase_units = set(data.get("purchase_units", []))
        customer._current_credit = data.get("current_credit", 0.0)
        customer._total_orders = data.get("total_orders", 0)
        customer._total_amount = data.get("total_amount", 0.0)
        customer._order_history = data.get("order_history", [])
        customer._notes = data.get("notes", [])
        
        # 恢复偏好
        pref_data = data.get("preferences", {})
        customer._preferences = PurchasePreference(
            preferred_products=pref_data.get("preferred_products", []),
            preferred_units=pref_data.get("preferred_units", []),
            payment_terms=pref_data.get("payment_terms"),
            delivery_requirements=pref_data.get("delivery_requirements")
        )
        
        return customer


class CustomerFactory:
    """客户工厂"""
    
    @staticmethod
    def create_customer(
        customer_name: str,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        address: Optional[str] = None,
        purchase_unit: Optional[str] = None,
        credit_limit: float = 0.0,
        remark: Optional[str] = None,
        created_by: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Customer:
        """创建新客户"""
        customer_id = f"CUST{datetime.now().strftime('%Y%m%d%H%M%S')}{id(object()) % 1000:03d}"
        
        contact_info = ContactInfo(
            phone=phone,
            email=email,
            address=address
        )
        
        return Customer(
            customer_id=customer_id,
            customer_name=customer_name,
            contact_info=contact_info,
            purchase_unit=purchase_unit,
            status=CustomerStatus.ACTIVE,
            level=CustomerLevel.REGULAR,
            credit_limit=credit_limit,
            remark=remark,
            created_by=created_by,
            metadata=metadata
        )
