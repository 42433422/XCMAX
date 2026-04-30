from sqlalchemy import Column, DateTime, Float, Index, Integer, String

from app.db.base import Base


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        Index("ix_products_unit", "unit"),
        Index("ix_products_model_number", "model_number"),
        {"sqlite_autoincrement": True},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_number = Column(String)
    name = Column(String, nullable=False)
    specification = Column(String)
    price = Column(Float, default=0.0)
    quantity = Column(Integer)
    description = Column(String)
    category = Column(String)
    brand = Column(String)
    unit = Column(String, default="个")
    is_active = Column(Integer, default=1)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
