"""Atomic customer deletion; cascading is a separately authenticated cross-domain write."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import and_, inspect, or_

from app.infrastructure.tenant_scope import apply_tenant_filter, current_tenant_id, owned_tenant_id
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def cascade_tenant(context):
    from app.domain.shared_services.auth_service import get_auth_service
    from app.infrastructure.auth.agent_mod_scope import _bound_actor

    actor = _bound_actor(dict(context or {}))
    tenant = actor.tenant_id
    if type(tenant) is not int or tenant <= 0 or str(tenant) != str(context.get("tenant_id")):
        raise PermissionError("级联删除需要可信企业归属")
    active = owned_tenant_id() or current_tenant_id()
    if active != tenant:
        raise PermissionError("级联删除的当前租户与登录归属不一致")
    permissions = get_auth_service().get_user_permissions(actor)
    if not {"product.edit", "shipment.edit"}.issubset(permissions):
        raise PermissionError("级联删除还需要产品及发货编辑权限")
    return tenant


def valid_customer_delete_ids(ids: Any) -> bool:
    return (
        isinstance(ids, (list, tuple))
        and bool(ids)
        and all(type(value) is int and value > 0 for value in ids)
    )


def delete_customers(session, ids, *, force=False, runtime_context=None) -> dict[str, Any]:
    from app.db.models.product import Product
    from app.db.models.purchase_unit import PurchaseUnit
    from app.db.models.shipment import ShipmentRecord
    from app.db.models.shipment_elt_fingerprint import ShipmentEltImportFingerprint

    if not valid_customer_delete_ids(ids):
        return {"success": False, "message": "客户 ID 必须为非空正整数列表", "deleted_count": 0}
    if not runtime_context and not (owned_tenant_id() or current_tenant_id()):
        raise PermissionError("删除客户缺少可信身份或企业范围")
    tenant = cascade_tenant(runtime_context) if force else None
    null_owner = False
    if runtime_context and not force:
        from app.domain.shared_services.auth_service import get_auth_service
        from app.infrastructure.auth.agent_mod_scope import _bound_actor
        from app.mod_sdk.product_skus import resolve_product_sku

        actor = _bound_actor(runtime_context)
        tenant = actor.tenant_id
        if tenant is None:
            if (
                resolve_product_sku() != "enterprise"
                or actor.role != "admin"
                or actor.tier != "admin"
                or "customer.edit" not in get_auth_service().get_user_permissions(actor)
            ):
                raise PermissionError("无租户客户删除仅支持已授权平台管理员")
            null_owner = True
        elif (
            type(tenant) is not int
            or tenant <= 0
            or str(tenant) != str(runtime_context.get("tenant_id"))
        ):
            raise PermissionError("客户删除归属与签名身份不一致")
    query = session.query(PurchaseUnit)
    if current_tenant_id() is not None or owned_tenant_id() is not None:
        query = apply_tenant_filter(query, PurchaseUnit)
    if null_owner:
        query = query.filter(PurchaseUnit.tenant_id.is_(None)).execution_options(
            skip_tenant_filter=True
        )
    elif tenant is not None:
        query = query.filter(PurchaseUnit.tenant_id == tenant)
    units = query.filter(PurchaseUnit.id.in_(ids)).all()
    # A mixed foreign/missing batch must not silently partially delete local rows.
    if {unit.id for unit in units} != set(ids):
        return {
            "success": False,
            "message": "客户不存在或不属于当前范围，未删除客户",
            "deleted_count": 0,
        }
    inspector = inspect(session.connection())
    has_products = inspector.has_table(Product.__tablename__)
    has_shipments = inspector.has_table(ShipmentRecord.__tablename__)
    plans = []
    if not force:
        # The old one-COUNT-per-customer preflight scaled as 2*N queries.
        # These three GROUP BY reads have a constant query budget for any batch.
        from sqlalchemy import func

        names = [unit.unit_name for unit in units]
        unit_ids = [unit.id for unit in units]
        tenants = {unit.tenant_id for unit in units}

        def scoped_counts(query, model):
            # Only the exceptional, authenticated platform-admin path can
            # see legacy NULL-owned data, with its explicit IS NULL predicate.
            if null_owner:
                return query.filter(model.tenant_id.is_(None)).execution_options(
                    skip_tenant_filter=True
                )
            scopes = [model.tenant_id.in_([tid for tid in tenants if tid is not None])]
            if None in tenants:
                scopes.append(model.tenant_id.is_(None))
            return query.filter(or_(*scopes))

        product_counts = {}
        if has_products:
            rows = scoped_counts(
                session.query(Product.tenant_id, Product.unit, func.count(Product.id))
                .filter(Product.unit.in_(names))
                .group_by(Product.tenant_id, Product.unit),
                Product,
            ).all()
            product_counts = {(tid, name): int(count) for tid, name, count in rows}

        shipment_by_id = {}
        shipment_by_name = {}
        if has_shipments:
            rows = scoped_counts(
                session.query(
                    ShipmentRecord.tenant_id,
                    ShipmentRecord.unit_id,
                    func.count(ShipmentRecord.id),
                )
                .filter(ShipmentRecord.unit_id.in_(unit_ids))
                .group_by(ShipmentRecord.tenant_id, ShipmentRecord.unit_id),
                ShipmentRecord,
            ).all()
            shipment_by_id = {(tid, ident): int(count) for tid, ident, count in rows}
            rows = scoped_counts(
                session.query(
                    ShipmentRecord.tenant_id,
                    ShipmentRecord.purchase_unit,
                    func.count(ShipmentRecord.id),
                )
                .filter(
                    ShipmentRecord.unit_id.is_(None),
                    ShipmentRecord.purchase_unit.in_(names),
                )
                .group_by(ShipmentRecord.tenant_id, ShipmentRecord.purchase_unit),
                ShipmentRecord,
            ).all()
            shipment_by_name = {(tid, name): int(count) for tid, name, count in rows}

        affected = []
        for unit in units:
            product_count = product_counts.get((unit.tenant_id, unit.unit_name), 0)
            shipment_count = shipment_by_id.get((unit.tenant_id, unit.id), 0)
            shipment_count += shipment_by_name.get((unit.tenant_id, unit.unit_name), 0)
            if product_count or shipment_count:
                affected.append(
                    {
                        "id": unit.id,
                        "unit_name": unit.unit_name,
                        "product_count": product_count,
                        "shipment_count": shipment_count,
                    }
                )
        if affected:
            return {
                "success": False,
                "message": "客户存在关联产品或发货记录，未删除客户",
                "deleted_count": 0,
                "has_associations": True,
                "affected_units": affected,
                "association_details": affected[0],
            }
        plans = [(unit, None, None) for unit in units]
    else:
        # The destructive branch retains the existing permission checks and
        # original per-customer deletion queries, without redundant COUNTs.
        for unit in units:
            products = (
                session.query(Product).filter(
                    Product.tenant_id == unit.tenant_id, Product.unit == unit.unit_name
                )
                if has_products
                else None
            )
            shipments = (
                session.query(ShipmentRecord).filter(
                    ShipmentRecord.tenant_id == unit.tenant_id,
                    or_(
                        ShipmentRecord.unit_id == unit.id,
                        and_(
                            ShipmentRecord.unit_id.is_(None),
                            ShipmentRecord.purchase_unit == unit.unit_name,
                        ),
                    ),
                )
                if has_shipments
                else None
            )
            plans.append((unit, products, shipments))
    # No writes until all rows and associations have been checked. One caller-owned transaction.
    for unit, products, shipments in plans:
        if force:
            if shipments is not None:
                shipment_ids = [row[0] for row in shipments.with_entities(ShipmentRecord.id).all()]
                if shipment_ids and inspector.has_table(ShipmentEltImportFingerprint.__tablename__):
                    session.query(ShipmentEltImportFingerprint).filter(
                        ShipmentEltImportFingerprint.tenant_key == f"tenant:{unit.tenant_id}",
                        ShipmentEltImportFingerprint.shipment_id.in_(shipment_ids),
                    ).delete(synchronize_session=False)
                shipments.delete(synchronize_session=False)
            if products is not None:
                products.delete(synchronize_session=False)
        session.delete(unit)
    session.commit()
    try:
        from app.neuro_bus.application_neuro_bridge import neuro_notify_customer_changed

        for unit in units:
            neuro_notify_customer_changed(
                "deleted", customer_id=unit.id, customer_name=unit.unit_name
            )
    except RECOVERABLE_ERRORS:
        logger.debug("neuro_notify_customer_changed skipped", exc_info=True)
    return {
        "success": True,
        "message": f"成功删除 {len(units)} 条客户记录",
        "deleted_count": len(units),
        "has_associations": False,
    }
