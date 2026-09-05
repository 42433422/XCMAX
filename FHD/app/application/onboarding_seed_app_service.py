"""首次使用的数据准备：客户/产品行业幂等预置，考勤转到既有工作区核对名单。"""

from __future__ import annotations

import logging
from typing import Any

from app.application.onboarding_seed_mapper import (
    build_customer_row,
    build_product_row,
    resolve_onboarding_seed_profile,
)
from app.db.models.product import Product
from app.db.models.purchase_unit import PurchaseUnit
from app.db.session import get_db

logger = logging.getLogger(__name__)


def seed_onboarding_demo_data(*, tenant_id: int, industry_id: str = "通用") -> dict[str, Any]:
    """业务行业幂等准备客户/产品；考勤只返回工作区核对指引。"""
    tid = int(tenant_id)
    profile = resolve_onboarding_seed_profile(industry_id)
    if profile.mod_id == "attendance-industry" or profile.industry_id in {
        "考勤",
        "考勤排班",
        "attendance",
        "attendance-industry",
    }:
        # Attendance belongs to its existing workspace. No ERP rows or shared
        # private database reads/writes can establish that workspace's ownership.
        return {
            "industry_id": profile.industry_id,
            "mod_id": "attendance-industry",
            "seeded": False,
            "seed_status": "workspace_review_required",
            "customer": None,
            "product": None,
            "workspace_path": "/attendance-industry/personnel",
            "message": "请先到考勤工作区确认部门和人员名单；已有名单直接核对，尚无名单时先录入部门和人员。",
            "demo_queries": {},
        }
    customer_spec = build_customer_row(tenant_id=tid, profile=profile)
    product_spec = build_product_row(tenant_id=tid, profile=profile)
    demo_customer_name = str(customer_spec.get("customer_name") or profile.demo_customer_name)
    demo_product_name = str(product_spec.get("name") or profile.demo_product_name)

    created: dict[str, Any] = {
        "customer": None,
        "product": None,
        "industry_id": profile.industry_id,
        "mod_id": profile.mod_id,
        "subsystems": profile.subsystems_meta,
        "demo_queries": {
            "ai_prompt": (
                f"请列出当前租户下的演示{profile.customer_entity}"
                f"「{demo_customer_name}」并一句话总结。"
            ),
        },
    }

    with get_db() as db:
        existing_customer = (
            db.query(PurchaseUnit)
            .filter(PurchaseUnit.tenant_id == tid, PurchaseUnit.unit_name == demo_customer_name)
            .first()
        )
        if existing_customer:
            created["customer"] = {
                "id": existing_customer.id,
                "name": existing_customer.unit_name,
                "entity": profile.customer_entity,
                "existing": True,
            }
        else:
            row = PurchaseUnit(
                tenant_id=tid,
                unit_name=demo_customer_name,
                contact_person=str(customer_spec.get("contact_person") or "演示联系人"),
                contact_phone=str(customer_spec.get("contact_phone") or "13800000000"),
                address=str(
                    customer_spec.get("contact_address") or f"{profile.industry_id} · 首启演示地址"
                ),
                is_active=True,
            )
            db.add(row)
            db.flush()
            created["customer"] = {
                "id": row.id,
                "name": row.unit_name,
                "entity": profile.customer_entity,
                "existing": False,
            }

        existing_product = (
            db.query(Product)
            .filter(Product.tenant_id == tid, Product.name == demo_product_name)
            .first()
        )
        if existing_product:
            created["product"] = {
                "id": existing_product.id,
                "name": existing_product.name,
                "entity": profile.product_entity,
                "existing": True,
            }
        else:
            prod = Product(
                tenant_id=tid,
                name=demo_product_name,
                model_number=str(product_spec.get("model_number") or "DEMO-001"),
                specification=str(
                    product_spec.get("specification") or f"{profile.industry_id} 首启样例 SKU"
                ),
                price=product_spec.get("price"),
                quantity=int(product_spec.get("quantity") or 10),
                category=str(product_spec.get("category") or profile.industry_id),
                brand=str(product_spec.get("brand") or "XCAGI"),
                unit=str(product_spec.get("unit") or "个"),
                is_active=int(product_spec.get("is_active") or 1),
            )
            db.add(prod)
            db.flush()
            created["product"] = {
                "id": prod.id,
                "name": prod.name,
                "entity": profile.product_entity,
                "existing": False,
            }

        db.commit()

    logger.info(
        "onboarding seed tenant=%s industry=%s mod=%s",
        tid,
        profile.industry_id,
        profile.mod_id,
    )
    return created


def demo_customer_name(industry_id: str = "通用") -> str:
    return resolve_onboarding_seed_profile(industry_id).demo_customer_name
