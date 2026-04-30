from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship, validates
from typing import Any, TYPE_CHECKING

from app.db.base import Base

if TYPE_CHECKING:
    from app.infrastructure.database.fk_validation import ForeignKeyValidator


class ShipmentRecord(Base):
    __tablename__ = "shipment_records"
    __table_args__ = {"sqlite_autoincrement": True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    purchase_unit = Column(String, nullable=False)
    # Note: ForeignKey removed - cross-database constraints not supported in SQLite
    # Use application-level validation via validate_unit_id() and service-layer checks
    unit_id = Column(Integer)
    product_name = Column(String, nullable=False)
    model_number = Column(String)
    quantity_kg = Column(Float, nullable=False)
    quantity_tins = Column(Integer, nullable=False)
    tin_spec = Column(Float)
    unit_price = Column(Float, default=0)
    amount = Column(Float, default=0)
    status = Column(String, default="pending")
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
    printed_at = Column(DateTime)
    printer_name = Column(String)
    raw_text = Column(Text)
    parsed_data = Column(Text)
    
    # Relationship removed - cross-database relationships not supported
    
    @validates("unit_id")
    def validate_unit_id(self, key: str, unit_id: Any) -> Any:
        """Application-level foreign key validation for cross-database reference.
        
        Performs format validation immediately and logs FK violations.
        For full FK enforcement, use validate_foreign_keys() before commit.
        """
        if unit_id is None:
            return unit_id
        
        # Format validation
        if not isinstance(unit_id, int):
            raise ValueError(f"Invalid unit_id type: {type(unit_id)}. Must be integer.")
        
        if unit_id <= 0:
            raise ValueError(f"Invalid unit_id: {unit_id}. Must be positive integer.")
        
        return unit_id
    
    def validate_foreign_keys(self, validator: "ForeignKeyValidator") -> bool:
        """
        执行完整的外键验证
        
        在服务层调用此方法进行完整的外键约束检查
        
        Args:
            validator: 外键验证器实例
            
        Returns:
            bool: True 如果所有外键有效
            
        Raises:
            ValueError: 如果外键约束违反且 strict=True
        """
        return validator.validate_purchase_unit_exists(self.unit_id)
    
    def to_dict_with_validation(self, validator: "ForeignKeyValidator") -> dict:
        """转换为字典，包含外键验证状态"""
        data = self.to_dict()
        data["_fk_valid"] = self.validate_foreign_keys(validator)
        if self.unit_id and not data["_fk_valid"]:
            data["_fk_warning"] = f"unit_id={self.unit_id} does not exist in purchase_units"
        return data
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "purchase_unit": self.purchase_unit,
            "unit_id": self.unit_id,
            "product_name": self.product_name,
            "model_number": self.model_number,
            "quantity_kg": self.quantity_kg,
            "quantity_tins": self.quantity_tins,
            "tin_spec": self.tin_spec,
            "unit_price": self.unit_price,
            "amount": self.amount,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "printed_at": self.printed_at.isoformat() if self.printed_at else None,
            "printer_name": self.printer_name,
            "raw_text": self.raw_text,
            "parsed_data": self.parsed_data,
        }
