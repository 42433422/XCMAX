# -*- coding: utf-8 -*-
"""
历史 ORM：表名 ``customers``。

业务上「客户」主数据为 ``purchase_units``（见 ``CustomerApplicationService``、
产品表 ``products.unit``）。新代码请使用 ``purchase_unit.PurchaseUnit``；本模型仅保留以免
旧迁移/外键引用断裂。
"""
from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.sql import func

from app.db.base import Base


class Customer(Base):
    """客户模型"""
    __tablename__ = "customers"
    
    id = Column(Integer, primary_key=True, index=True)
    customer_name = Column(String(255), nullable=False, index=True)
    contact_person = Column(String(100))
    contact_phone = Column(String(50))
    contact_address = Column(String(500))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
