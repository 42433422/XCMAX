"""空企业首启演示数据：按行业 manifest subsystems 写入首笔 tenant-scoped 业务数据。

同时补齐发货单所需的 ``purchase_units``、对话打印可用的演示 SKU，并触发初始单据模板入库。
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from app.application.onboarding_seed_mapper import (
    build_customer_row,
    build_product_row,
    resolve_onboarding_seed_profile,
)
from app.db.models.customer import Customer
from app.db.models.product import Product
from app.db.models.purchase_unit import PurchaseUnit
from app.db.session import get_db
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

# 对话打印专用单位：后缀「有限公司」便于价格表槽位抽取；与教程/话术对齐
PRINT_DEMO_UNIT_NAME = "演示客户有限公司"
PRINT_DEMO_MODEL = "A001"
PRINT_DEMO_MODEL_COATING = "9803"


def _ensure_purchase_unit(
    db,
    *,
    tenant_id: int,
    unit_name: str,
    contact_person: str,
    contact_phone: str,
    address: str,
) -> dict[str, Any]:
    existing = (
        db.query(PurchaseUnit)
        .filter(PurchaseUnit.tenant_id == tenant_id, PurchaseUnit.unit_name == unit_name)
        .first()
    )
    if existing:
        return {
            "id": existing.id,
            "name": existing.unit_name,
            "existing": True,
        }
    row = PurchaseUnit(
        tenant_id=tenant_id,
        unit_name=unit_name,
        contact_person=contact_person,
        contact_phone=contact_phone,
        address=address,
        is_active=True,
    )
    db.add(row)
    db.flush()
    return {"id": row.id, "name": row.unit_name, "existing": False}


def _ensure_product(
    db,
    *,
    tenant_id: int,
    name: str,
    model_number: str,
    specification: str,
    price: Decimal | float | int | None,
    quantity: int = 10,
    category: str = "演示",
    unit: str = "桶",
) -> dict[str, Any]:
    existing = (
        db.query(Product)
        .filter(Product.tenant_id == tenant_id, Product.model_number == model_number)
        .first()
    )
    if existing is None:
        existing = (
            db.query(Product).filter(Product.tenant_id == tenant_id, Product.name == name).first()
        )
    if existing:
        # 补齐型号/单价，避免旧种子缺字段导致查价/开单失败
        changed = False
        if not (existing.model_number or "").strip():
            existing.model_number = model_number
            changed = True
        if existing.price is None and price is not None:
            existing.price = price
            changed = True
        if changed:
            db.flush()
        return {
            "id": existing.id,
            "name": existing.name,
            "model_number": existing.model_number,
            "existing": True,
        }

    prod = Product(
        tenant_id=tenant_id,
        name=name,
        model_number=model_number,
        specification=specification,
        price=price,
        quantity=quantity,
        category=category,
        brand="XCAGI",
        unit=unit,
        is_active=1,
    )
    db.add(prod)
    db.flush()
    return {
        "id": prod.id,
        "name": prod.name,
        "model_number": prod.model_number,
        "existing": False,
    }


def _demo_chat_phrases(*, customer_name: str, print_unit: str, model_number: str) -> dict[str, str]:
    return {
        "ai_prompt": (f"请列出当前租户下的演示客户「{customer_name}」并一句话总结。"),
        "price_list": f"打印{print_unit}的价格表",
        "shipment": f"打印{print_unit}发货单，编号{model_number}，规格28，一共3桶",
        "product_query": f"查一下{model_number}的价格",
        "label_print": f"帮我打印{model_number}标签",
    }


def seed_onboarding_demo_data(*, tenant_id: int, industry_id: str = "通用") -> dict[str, Any]:
    """幂等写入演示客户/购买单位/产品，并确保初始单据模板可用。"""
    tid = int(tenant_id)
    profile = resolve_onboarding_seed_profile(industry_id)
    customer_spec = build_customer_row(tenant_id=tid, profile=profile)
    product_spec = build_product_row(tenant_id=tid, profile=profile)
    demo_customer_name = str(customer_spec.get("customer_name") or profile.demo_customer_name)
    demo_product_name = str(product_spec.get("name") or profile.demo_product_name)

    # 涂料/通用走 A001；涂料额外补 9803 方便经典开单话术
    primary_model = PRINT_DEMO_MODEL
    if str(product_spec.get("model_number") or "").strip() and profile.industry_id not in {
        "通用",
        "涂料",
        "批发",
    }:
        primary_model = str(product_spec.get("model_number")).strip()

    created: dict[str, Any] = {
        "customer": None,
        "purchase_unit": None,
        "print_purchase_unit": None,
        "product": None,
        "extra_products": [],
        "templates": None,
        "industry_id": profile.industry_id,
        "mod_id": profile.mod_id,
        "subsystems": profile.subsystems_meta,
        "demo_queries": {},
    }

    with get_db() as db:
        existing_customer = (
            db.query(Customer)
            .filter(Customer.tenant_id == tid, Customer.customer_name == demo_customer_name)
            .first()
        )
        if existing_customer:
            created["customer"] = {
                "id": existing_customer.id,
                "name": existing_customer.customer_name,
                "entity": profile.customer_entity,
                "existing": True,
            }
            contact_person = existing_customer.contact_person or "演示联系人"
            contact_phone = existing_customer.contact_phone or "13800000000"
            contact_address = (
                existing_customer.contact_address or f"{profile.industry_id} · 首启演示地址"
            )
        else:
            row = Customer(
                tenant_id=tid,
                customer_name=demo_customer_name,
                contact_person=str(customer_spec.get("contact_person") or "演示联系人"),
                contact_phone=str(customer_spec.get("contact_phone") or "13800000000"),
                contact_address=str(
                    customer_spec.get("contact_address") or f"{profile.industry_id} · 首启演示地址"
                ),
            )
            db.add(row)
            db.flush()
            created["customer"] = {
                "id": row.id,
                "name": row.customer_name,
                "entity": profile.customer_entity,
                "existing": False,
            }
            contact_person = row.contact_person or "演示联系人"
            contact_phone = row.contact_phone or "13800000000"
            contact_address = row.contact_address or f"{profile.industry_id} · 首启演示地址"

        # 发货单解析走 purchase_units；与 customers 演示名对齐
        created["purchase_unit"] = _ensure_purchase_unit(
            db,
            tenant_id=tid,
            unit_name=demo_customer_name,
            contact_person=str(contact_person),
            contact_phone=str(contact_phone),
            address=str(contact_address),
        )
        created["print_purchase_unit"] = _ensure_purchase_unit(
            db,
            tenant_id=tid,
            unit_name=PRINT_DEMO_UNIT_NAME,
            contact_person=str(contact_person),
            contact_phone=str(contact_phone),
            address=str(contact_address),
        )

        price = product_spec.get("price")
        if not isinstance(price, Decimal):
            try:
                price = Decimal(str(price if price is not None else "12.50"))
            except RECOVERABLE_ERRORS:
                price = Decimal("12.50")

        created["product"] = _ensure_product(
            db,
            tenant_id=tid,
            name=demo_product_name,
            model_number=primary_model,
            specification=str(product_spec.get("specification") or "28"),
            price=price,
            quantity=int(product_spec.get("quantity") or 10),
            category=str(product_spec.get("category") or profile.industry_id),
            unit=str(product_spec.get("unit") or "桶"),
        )

        if profile.industry_id in {"涂料", "批发", "通用"}:
            extra = _ensure_product(
                db,
                tenant_id=tid,
                name="演示哑光清面漆",
                model_number=PRINT_DEMO_MODEL_COATING,
                specification="28",
                price=Decimal("18.80"),
                quantity=20,
                category=profile.industry_id,
                unit="桶",
            )
            created["extra_products"].append(extra)

        db.commit()

    created["demo_queries"] = _demo_chat_phrases(
        customer_name=demo_customer_name,
        print_unit=PRINT_DEMO_UNIT_NAME,
        model_number=primary_model,
    )

    try:
        from app.db.seeds.document_templates_seed import ensure_initial_document_templates

        created["templates"] = ensure_initial_document_templates()
    except RECOVERABLE_ERRORS as exc:
        logger.warning("onboarding 触发初始模板种子失败: %s", exc)
        created["templates"] = {"success": False, "message": str(exc)}

    logger.info(
        "onboarding seed tenant=%s industry=%s mod=%s unit=%s product=%s",
        tid,
        profile.industry_id,
        profile.mod_id,
        created.get("print_purchase_unit", {}).get("name"),
        created.get("product", {}).get("model_number"),
    )
    return created


def demo_customer_name(industry_id: str = "通用") -> str:
    return resolve_onboarding_seed_profile(industry_id).demo_customer_name
