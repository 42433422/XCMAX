"""ORM 模型约束与行为测试。

验证内容：
- 表名映射正确
- 列约束（nullable / default / 类型）与模型定义一致
- 模型实例化与必填字段校验
- to_dict() 返回结构正确
- @validates 装饰器行为正确
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import inspect as sa_inspect

from app.db.models.customer import Customer
from app.db.models.product import Product
from app.db.models.shipment import ShipmentRecord

# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _column_nullable(model_cls, col_name: str) -> bool:
    """获取模型列的 nullable 属性。"""
    mapper = sa_inspect(model_cls)
    col = mapper.columns.get(col_name)
    assert col is not None, f"{model_cls.__name__} 缺少列 {col_name}"
    return col.nullable


def _column_default(model_cls, col_name: str):
    """获取模型列的 default 属性（不含 server_default）。"""
    mapper = sa_inspect(model_cls)
    col = mapper.columns.get(col_name)
    assert col is not None, f"{model_cls.__name__} 缺少列 {col_name}"
    return col.default


def _has_column(model_cls, col_name: str) -> bool:
    """检查模型是否有某列。"""
    mapper = sa_inspect(model_cls)
    return col_name in mapper.columns


# ---------------------------------------------------------------------------
# Customer 模型测试
# ---------------------------------------------------------------------------


class TestCustomerModel:
    """Customer 模型约束与行为。"""

    def test_tablename(self):
        assert Customer.__tablename__ == "customers"

    def test_inherits_timestamp_mixin(self):
        """Customer 应继承 TimestampMixin（created_at / updated_at）。"""
        assert _has_column(Customer, "created_at")
        assert _has_column(Customer, "updated_at")

    def test_customer_name_not_nullable(self):
        """customer_name 是必填字段。"""
        assert _column_nullable(Customer, "customer_name") is False

    def test_customer_name_indexed(self):
        """customer_name 有索引（查询优化）。"""
        mapper = sa_inspect(Customer)
        col = mapper.columns.get("customer_name")
        assert col is not None and col.index is True

    def test_contact_person_nullable(self):
        """contact_person 是可选字段。"""
        assert _column_nullable(Customer, "contact_person") is True

    def test_contact_phone_nullable(self):
        """contact_phone 是可选字段。"""
        assert _column_nullable(Customer, "contact_phone") is True

    def test_instantiate_with_required_fields(self):
        """仅传必填字段可实例化。"""
        customer = Customer(customer_name="甲公司")
        assert customer.customer_name == "甲公司"
        assert customer.contact_person is None
        assert customer.contact_phone is None

    def test_instantiate_with_all_fields(self):
        """传所有字段可实例化。"""
        customer = Customer(
            customer_name="乙公司",
            contact_person="张三",
            contact_phone="13800138000",
            contact_address="北京市朝阳区",
        )
        assert customer.customer_name == "乙公司"
        assert customer.contact_person == "张三"
        assert customer.contact_phone == "13800138000"


# ---------------------------------------------------------------------------
# Product 模型测试
# ---------------------------------------------------------------------------


class TestProductModel:
    """Product 模型约束与行为。"""

    def test_tablename(self):
        assert Product.__tablename__ == "products"

    def test_name_not_nullable(self):
        """name 是必填字段。"""
        assert _column_nullable(Product, "name") is False

    def test_price_default_zero(self):
        """price 默认值为 0.0。"""
        default = _column_default(Product, "price")
        assert default is not None
        assert default.arg == 0.0

    def test_unit_default_ge(self):
        """unit 默认值为 '个'。"""
        default = _column_default(Product, "unit")
        assert default is not None
        assert default.arg == "个"

    def test_is_active_default_one(self):
        """is_active 默认值为 1（上架）。"""
        default = _column_default(Product, "is_active")
        assert default is not None
        assert default.arg == 1

    def test_inherits_tenant_scoped(self):
        """Product 应继承 TenantScopedMixin（tenant_id 列）。"""
        assert _has_column(Product, "tenant_id")

    def test_table_args_has_indexes(self):
        """__table_args__ 包含 model_number 和 unit 索引。"""
        args = Product.__table_args__
        index_names = {idx.name for idx in args if hasattr(idx, "name")}
        assert "ix_products_model_number" in index_names
        assert "ix_products_unit" in index_names

    def test_instantiate_with_required_fields(self):
        """仅传必填字段可实例化，可选字段使用默认值。"""
        product = Product(name="测试产品")
        assert product.name == "测试产品"
        assert product.model_number is None
        # 默认值在 flush 时生效，实例化后可能仍为 None
        # 但 default 定义本身已在上面的测试中验证

    def test_instantiate_with_all_fields(self):
        """传所有字段可实例化。"""
        product = Product(
            name="高级涂料",
            model_number="TL-001",
            price=Decimal("99.50"),
            quantity=100,
            unit="桶",
            is_active=1,
        )
        assert product.name == "高级涂料"
        assert product.model_number == "TL-001"
        assert product.price == Decimal("99.50")
        assert product.quantity == 100
        assert product.unit == "桶"


# ---------------------------------------------------------------------------
# ShipmentRecord 模型测试
# ---------------------------------------------------------------------------


class TestShipmentRecordModel:
    """ShipmentRecord 模型约束与行为。"""

    def test_tablename(self):
        assert ShipmentRecord.__tablename__ == "shipment_records"

    def test_purchase_unit_not_nullable(self):
        """purchase_unit 是必填字段。"""
        assert _column_nullable(ShipmentRecord, "purchase_unit") is False

    def test_product_name_not_nullable(self):
        """product_name 是必填字段。"""
        assert _column_nullable(ShipmentRecord, "product_name") is False

    def test_quantity_kg_not_nullable(self):
        """quantity_kg 是必填字段。"""
        assert _column_nullable(ShipmentRecord, "quantity_kg") is False

    def test_quantity_tins_not_nullable(self):
        """quantity_tins 是必填字段。"""
        assert _column_nullable(ShipmentRecord, "quantity_tins") is False

    def test_status_default_pending(self):
        """status 默认值为 'pending'。"""
        default = _column_default(ShipmentRecord, "status")
        assert default is not None
        assert default.arg == "pending"

    def test_unit_price_default_zero(self):
        """unit_price 默认值为 0。"""
        default = _column_default(ShipmentRecord, "unit_price")
        assert default is not None
        assert default.arg == 0

    def test_inherits_tenant_scoped(self):
        """ShipmentRecord 应继承 TenantScopedMixin。"""
        assert _has_column(ShipmentRecord, "tenant_id")

    def test_instantiate_with_required_fields(self):
        """传必填字段可实例化。"""
        record = ShipmentRecord(
            purchase_unit="甲公司",
            product_name="产品A",
            quantity_kg=25.5,
            quantity_tins=50,
        )
        assert record.purchase_unit == "甲公司"
        assert record.product_name == "产品A"
        assert record.quantity_kg == 25.5
        assert record.quantity_tins == 50

    def test_to_dict_returns_all_fields(self):
        """to_dict() 返回所有业务字段。"""
        record = ShipmentRecord(
            purchase_unit="乙公司",
            product_name="产品B",
            quantity_kg=10.0,
            quantity_tins=20,
            status="shipped",
            printer_name="打印机01",
        )
        d = record.to_dict()
        assert d["purchase_unit"] == "乙公司"
        assert d["product_name"] == "产品B"
        assert d["quantity_kg"] == 10.0
        assert d["quantity_tins"] == 20
        assert d["status"] == "shipped"
        assert d["printer_name"] == "打印机01"
        # id 在 flush 前为 None
        assert "id" in d
        assert "created_at" in d
        assert "updated_at" in d

    def test_validate_unit_id_rejects_zero(self):
        """unit_id=0 应被 @validates 拒绝。"""
        record = ShipmentRecord(
            purchase_unit="丙公司",
            product_name="产品C",
            quantity_kg=1.0,
            quantity_tins=1,
        )
        with pytest.raises(ValueError, match="positive integer"):
            record.unit_id = 0

    def test_validate_unit_id_rejects_negative(self):
        """unit_id=-1 应被 @validates 拒绝。"""
        record = ShipmentRecord(
            purchase_unit="丁公司",
            product_name="产品D",
            quantity_kg=1.0,
            quantity_tins=1,
        )
        with pytest.raises(ValueError, match="positive integer"):
            record.unit_id = -1

    def test_validate_unit_id_accepts_positive(self):
        """unit_id=123 应被 @validates 接受。"""
        record = ShipmentRecord(
            purchase_unit="戊公司",
            product_name="产品E",
            quantity_kg=1.0,
            quantity_tins=1,
        )
        record.unit_id = 123
        assert record.unit_id == 123

    def test_validate_unit_id_accepts_none(self):
        """unit_id=None 应被 @validates 接受（可选字段）。"""
        record = ShipmentRecord(
            purchase_unit="己公司",
            product_name="产品F",
            quantity_kg=1.0,
            quantity_tins=1,
        )
        record.unit_id = None
        assert record.unit_id is None

    def test_validate_unit_id_rejects_string(self):
        """unit_id='abc' 应被 @validates 拒绝（类型错误）。"""
        record = ShipmentRecord(
            purchase_unit="庚公司",
            product_name="产品G",
            quantity_kg=1.0,
            quantity_tins=1,
        )
        with pytest.raises(ValueError, match="Must be integer"):
            record.unit_id = "abc"
