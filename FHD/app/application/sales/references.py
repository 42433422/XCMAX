"""Current-tenant customer, product, warehouse and inventory resolution."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Customer, InventoryLedger, Product, Warehouse

from .contracts import ClosedLoopExecutionError
from .validation import coerce_entity_id


def resolve_customer(db: Session, order: dict[str, Any], tenant_id: int) -> dict[str, Any]:
    cid = order.get("customer_id")
    if cid is not None:
        cid_int = coerce_entity_id(cid, "resolve_customer", "customer_id")
        customer = (
            db.query(Customer)
            .filter(Customer.id == cid_int, Customer.tenant_id == tenant_id)
            .first()
        )
        if customer is None:
            raise ClosedLoopExecutionError("resolve_customer", f"当前租户下客户不存在: id={cid}")
        return {"id": customer.id, "name": customer.customer_name}
    cname = order.get("customer_name")
    resolution = order.get("customer_resolution")
    if resolution != "current_tenant_exact_name":
        raise ClosedLoopExecutionError("resolve_customer", f"不支持的客户解析方式: {resolution}")
    customers = (
        db.query(Customer)
        .filter(Customer.customer_name == cname, Customer.tenant_id == tenant_id)
        .all()
    )
    matches = len(customers)
    if matches == 1:
        customer = customers[0]
        return {"id": customer.id, "name": customer.customer_name}
    if matches != 0:
        raise ClosedLoopExecutionError(
            "resolve_customer", f"客户名匹配数为 {matches}（应为恰好 1）: {cname}"
        )
    from app.db.models.purchase_unit import PurchaseUnit

    purchase_units = (
        db.query(PurchaseUnit)
        .filter(PurchaseUnit.unit_name == cname, PurchaseUnit.tenant_id == tenant_id)
        .limit(2)
        .all()
    )
    if len(purchase_units) != 1:
        raise ClosedLoopExecutionError(
            "resolve_customer", f"采购单位匹配数为 {len(purchase_units)}（应为恰好 1）: {cname}"
        )
    purchase_unit = purchase_units[0]
    customer = Customer(
        customer_name=purchase_unit.unit_name,
        contact_person=purchase_unit.contact_person,
        contact_phone=purchase_unit.contact_phone,
        contact_address=purchase_unit.address,
        tenant_id=tenant_id,
    )
    db.add(customer)
    db.flush()
    return {"id": customer.id, "name": customer.customer_name}


def resolve_products(db: Session, order: dict[str, Any], tenant_id: int) -> list[dict[str, Any]]:
    resolved = []
    for idx, item in enumerate(order["items"]):
        pid = item.get("product_id")
        if pid is not None:
            pid_int = coerce_entity_id(pid, "resolve_product", "product_id")
            product = (
                db.query(Product)
                .filter(Product.id == pid_int, Product.tenant_id == tenant_id)
                .first()
            )
            if product is None:
                raise ClosedLoopExecutionError("resolve_product", f"当前租户下产品不存在: id={pid}")
        else:
            pname = item.get("product_name")
            resolution = item.get("product_resolution")
            if resolution != "current_tenant_exact_name":
                raise ClosedLoopExecutionError(
                    "resolve_product", f"不支持的产品解析方式: {resolution}"
                )
            products = (
                db.query(Product)
                .filter(Product.name == pname, Product.tenant_id == tenant_id)
                .all()
            )
            matches = len(products)
            if matches != 1:
                raise ClosedLoopExecutionError(
                    "resolve_product", f"产品名匹配数为 {matches}（应为恰好 1）: {pname}"
                )
            product = products[0]
        unit = item.get("unit")
        if product.unit and product.unit != unit:
            raise ClosedLoopExecutionError(
                "resolve_product", f"产品单位不匹配: 产品={product.unit} vs 载荷={unit}"
            )
        resolved.append(
            {
                "product_id": product.id,
                "unit": unit,
                "quantity": Decimal(str(item["quantity"])),
                "unit_price": Decimal(str(item["unit_price"])),
                "product_name": product.name,
            }
        )
    return resolved


def resolve_warehouse(db: Session, fulfillment: dict[str, Any], tenant_id: int) -> dict[str, Any]:
    wid = fulfillment.get("warehouse_id")
    if wid is not None:
        wid_int = coerce_entity_id(wid, "resolve_warehouse", "warehouse_id")
        wh = (
            db.query(Warehouse)
            .filter(Warehouse.id == wid_int, Warehouse.tenant_id == tenant_id)
            .first()
        )
        if wh is None:
            raise ClosedLoopExecutionError("resolve_warehouse", f"当前租户下仓库不存在: id={wid}")
        return {"id": wh.id, "code": wh.code}
    resolution = fulfillment.get("warehouse_resolution")
    if resolution != "current_tenant_default":
        raise ClosedLoopExecutionError("resolve_warehouse", f"不支持的仓库解析方式: {resolution}")
    wh = (
        db.query(Warehouse)
        .filter(Warehouse.status == "active", Warehouse.tenant_id == tenant_id)
        .order_by(Warehouse.id.asc())
        .first()
    )
    if wh is None:
        raise ClosedLoopExecutionError(
            "resolve_warehouse",
            "当前租户下无可用仓库：请先在「库存管理」点击「初始化默认仓库」，为要销售的产品办理入库后，再重新提交这笔销售",
        )
    return {"id": wh.id, "code": wh.code}


def resolve_inventory_source(
    db: Session, *, product_id: int, warehouse_id: int, quantity: Decimal, tenant_id: int
) -> dict[str, Any]:
    """解析闭环交付使用的唯一库存批次，避免把有批次库存误判为不存在。

    桌面正常入库允许填写批次号，而库存扣减服务按 ``batch_no`` 精确匹配。
    闭环载荷未显式指定批次时，只接受当前租户、产品、仓库下恰好一个库存充足
    的台账；缺失或多个候选均 fail-closed，绝不静默挑选错误批次。
    """
    ledgers = (
        db.query(InventoryLedger)
        .filter(
            InventoryLedger.product_id == product_id,
            InventoryLedger.warehouse_id == warehouse_id,
            InventoryLedger.tenant_id == tenant_id,
            InventoryLedger.available_quantity >= quantity,
        )
        .order_by(InventoryLedger.id.asc())
        .limit(2)
        .all()
    )
    if not ledgers:
        raise ClosedLoopExecutionError(
            "resolve_inventory",
            "可交付库存台账匹配数为 0（应为恰好 1）：该仓库里这个产品没有足够的可用库存，请先在「库存管理 → 入库」登记库存",
        )
    if len(ledgers) != 1:
        raise ClosedLoopExecutionError(
            "resolve_inventory", f"可交付库存台账匹配数为 {len(ledgers)}（应为恰好 1）"
        )
    ledger = ledgers[0]
    return {"batch_no": ledger.batch_no, "location_id": ledger.location_id}
