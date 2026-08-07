"""
客户/供应商 CRM（Task 4：upgrade-erp-modules-odoo18）单元测试

覆盖：
- CustomerAddress 客户地址模型（送货/发票、默认地址）
- Customer 信用额度字段（credit_limit / credit_used / is_credit_limited）
- CustomerApplicationService.add_address / get_addresses / set_credit_limit
- 供应商查询薄封装 get_suppliers / get_supplier
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.customer_app_service import CustomerApplicationService
from app.db.base import Base
from app.db.models.crm import ADDRESS_TYPES, CustomerAddress
from app.db.models.customer import Customer


@pytest.fixture(scope="function")
def test_engine():
    return create_engine("sqlite:///:memory:")


@pytest.fixture(scope="function")
def test_session(test_engine):
    Base.metadata.create_all(test_engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="function")
def service(test_session, monkeypatch):
    """把服务会话固定到内存库，隔离真实 DB。"""
    svc = CustomerApplicationService()
    monkeypatch.setattr(CustomerApplicationService, "_get_session", lambda self: test_session)
    return svc


def _seed_customer(db, name="客户甲") -> Customer:
    c = Customer(customer_name=name)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


class TestCustomerAddressModel:
    def test_create_delivery_address(self, test_session):
        """创建客户送货地址。"""
        customer = _seed_customer(test_session)
        addr = CustomerAddress(
            customer_id=customer.id,
            address_type="delivery",
            contact_person="张三",
            phone="13800000000",
            address="上海市浦东新区XX路1号",
            is_default=1,
        )
        test_session.add(addr)
        test_session.commit()
        test_session.refresh(addr)

        assert addr.id is not None
        assert addr.customer_id == customer.id
        assert addr.address_type == "delivery"
        assert addr.is_default == 1
        assert addr.to_dict()["address"] == "上海市浦东新区XX路1号"

    def test_address_types(self):
        """地址类型集合包含送货与发票。"""
        assert {"invoice", "delivery"} <= ADDRESS_TYPES

    def test_invoice_address(self, test_session):
        """创建发票地址。"""
        customer = _seed_customer(test_session)
        addr = CustomerAddress(
            customer_id=customer.id, address_type="invoice", address="北京市朝阳区XX街2号"
        )
        test_session.add(addr)
        test_session.commit()
        test_session.refresh(addr)
        assert addr.address_type == "invoice"


class TestCustomerCreditFields:
    def test_default_credit_fields(self, test_session):
        """客户信用额度字段默认值。"""
        customer = _seed_customer(test_session)
        assert customer.credit_limit == Decimal("0")
        assert customer.credit_used == Decimal("0")
        assert customer.is_credit_limited == 0

    def test_set_credit_limit(self, test_session):
        """设置信用额度后字段更新。"""
        customer = _seed_customer(test_session)
        customer.credit_limit = Decimal("50000.00")
        customer.is_credit_limited = 1
        test_session.commit()
        test_session.refresh(customer)
        assert float(customer.credit_limit) == 50000.0
        assert customer.is_credit_limited == 1


class TestCustomerAddressService:
    def test_add_delivery_address(self, service):
        """通过服务添加送货地址。"""
        c = _seed_customer(service._get_session())
        result = service.add_address(
            {
                "customer_id": c.id,
                "address_type": "delivery",
                "contact_person": "李四",
                "phone": "13900000000",
                "address": "广州市天河区XX路3号",
                "is_default": 1,
            }
        )
        assert result["success"] is True
        assert result["data"]["address_type"] == "delivery"
        assert result["data"]["is_default"] == 1

    def test_add_invoice_address(self, service):
        """通过服务添加发票地址。"""
        c = _seed_customer(service._get_session())
        result = service.add_address(
            {"customer_id": c.id, "address_type": "invoice", "address": "深圳市南山区XX路4号"}
        )
        assert result["success"] is True
        assert result["data"]["address_type"] == "invoice"

    def test_default_address_unique(self, service):
        """默认地址唯一：新默认地址会取消旧默认。"""
        c = _seed_customer(service._get_session())
        cid = c.id
        service.add_address(
            {"customer_id": cid, "address_type": "delivery", "address": "地址A", "is_default": 1}
        )
        service.add_address(
            {"customer_id": cid, "address_type": "delivery", "address": "地址B", "is_default": 1}
        )
        result = service.get_addresses(cid)
        defaults = [a for a in result["data"] if a["is_default"] == 1]
        assert len(result["data"]) == 2
        assert len(defaults) == 1
        assert defaults[0]["address"] == "地址B"

    def test_get_addresses(self, service):
        """查询客户地址列表。"""
        c = _seed_customer(service._get_session())
        cid = c.id
        service.add_address(
            {"customer_id": cid, "address_type": "delivery", "address": "地址1", "is_default": 1}
        )
        service.add_address({"customer_id": cid, "address_type": "invoice", "address": "地址2"})
        result = service.get_addresses(cid)
        assert result["success"] is True
        assert result["count"] == 2
        # 默认地址排在最前
        assert result["data"][0]["is_default"] == 1

    def test_add_address_customer_not_found(self, service):
        """地址指向不存在的客户时失败。"""
        result = service.add_address({"customer_id": 99999, "address_type": "delivery"})
        assert result["success"] is False

    def test_add_address_invalid_type(self, service):
        """非法地址类型被拒绝。"""
        c = _seed_customer(service._get_session())
        result = service.add_address({"customer_id": c.id, "address_type": "billing"})
        assert result["success"] is False


class TestCustomerCreditService:
    def test_set_credit_limit(self, service):
        """通过服务设置信用额度。"""
        c = _seed_customer(service._get_session())
        result = service.set_credit_limit(c.id, 80000.0)
        assert result["success"] is True
        assert result["data"]["credit_limit"] == 80000.0
        assert result["data"]["is_credit_limited"] == 1

    def test_set_credit_limit_zero(self, service):
        """额度清零时解除信用限制。"""
        c = _seed_customer(service._get_session())
        service.set_credit_limit(c.id, 80000.0)
        result = service.set_credit_limit(c.id, 0)
        assert result["success"] is True
        assert result["data"]["credit_limit"] == 0.0
        assert result["data"]["is_credit_limited"] == 0


class TestSupplierWrapper:
    def test_get_suppliers_wrapper(self, service, monkeypatch):
        """供应商查询薄封装复用 PurchaseService。"""
        import app.services.purchase_service as ps

        fake = ps.PurchaseService()
        fake.get_suppliers = lambda status=None, keyword=None: {
            "success": True,
            "data": [{"id": 1, "name": "供应商A"}],
            "count": 1,
        }
        monkeypatch.setattr(ps, "PurchaseService", lambda: fake)
        result = service.get_suppliers()
        assert result["success"] is True
        assert result["count"] == 1

    def test_get_supplier_wrapper(self, service, monkeypatch):
        """供应商详情薄封装复用 PurchaseService。"""
        import app.services.purchase_service as ps

        fake = ps.PurchaseService()
        fake.get_supplier = lambda supplier_id: {
            "success": True,
            "data": {"id": supplier_id, "name": "供应商B"},
        }
        monkeypatch.setattr(ps, "PurchaseService", lambda: fake)
        result = service.get_supplier(7)
        assert result["success"] is True
        assert result["data"]["id"] == 7