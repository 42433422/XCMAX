"""空企业首启演示数据：按行业写入首笔 tenant-scoped 业务数据。"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from app.db.models.customer import Customer
from app.db.models.product import Product
from app.db.session import get_db

logger = logging.getLogger(__name__)

_DEMO_CUSTOMER = "XC 演示客户"
_DEMO_PRODUCT = "XC 演示产品"


def seed_onboarding_demo_data(*, tenant_id: int, industry_id: str = "通用") -> dict[str, Any]:
    """幂等写入 1 客户 + 1 产品；已存在则跳过。"""
    tid = int(tenant_id)
    industry = str(industry_id or "通用").strip() or "通用"
    created: dict[str, Any] = {"customer": None, "product": None, "industry_id": industry}

    with get_db() as db:
        existing_customer = (
            db.query(Customer)
            .filter(Customer.tenant_id == tid, Customer.customer_name == _DEMO_CUSTOMER)
            .first()
        )
        if existing_customer:
            created["customer"] = {
                "id": existing_customer.id,
                "name": existing_customer.customer_name,
                "existing": True,
            }
        else:
            row = Customer(
                tenant_id=tid,
                customer_name=_DEMO_CUSTOMER,
                contact_person="演示联系人",
                contact_phone="13800000000",
                contact_address=f"{industry} · 首启演示地址",
            )
            db.add(row)
            db.flush()
            created["customer"] = {"id": row.id, "name": row.customer_name, "existing": False}

        existing_product = (
            db.query(Product)
            .filter(Product.tenant_id == tid, Product.name == _DEMO_PRODUCT)
            .first()
        )
        if existing_product:
            created["product"] = {
                "id": existing_product.id,
                "name": existing_product.name,
                "existing": True,
            }
        else:
            prod = Product(
                tenant_id=tid,
                name=_DEMO_PRODUCT,
                model_number="DEMO-001",
                specification=f"{industry} 首启样例 SKU",
                price=Decimal("99.00"),
                quantity=10,
                category=industry,
                brand="XCAGI",
                unit="个",
                is_active=1,
            )
            db.add(prod)
            db.flush()
            created["product"] = {"id": prod.id, "name": prod.name, "existing": False}

        db.commit()

    logger.info("onboarding seed tenant=%s industry=%s", tid, industry)
    return created


def demo_customer_name() -> str:
    return _DEMO_CUSTOMER
