"""Tenant-checked association writes inside the caller's transaction."""

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db.models.customer_product_link import CustomerProductLink
from app.db.models.product import Product
from app.db.models.purchase_unit import PurchaseUnit
from app.infrastructure.tenant_scope import TenantScopeError, current_tenant_id


def ensure_customer_product_link(
    db: Session, purchase_unit_id: int, product_id: int
) -> tuple[CustomerProductLink, bool]:
    tenant = current_tenant_id()
    if tenant is None or tenant <= 0:
        raise TenantScopeError("客户产品关联需要明确租户")
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value <= 0
        for value in (purchase_unit_id, product_id)
    ):
        raise ValueError("客户和产品 ID 必须为正整数")
    customer = (
        db.query(PurchaseUnit)
        .filter(
            PurchaseUnit.id == purchase_unit_id,
            PurchaseUnit.tenant_id == tenant,
            PurchaseUnit.is_active.is_(True),
        )
        .first()
    )
    product = (
        db.query(Product)
        .filter(
            Product.id == product_id,
            Product.tenant_id == tenant,
            Product.is_active == 1,
        )
        .first()
    )
    if customer is None or product is None:
        raise ValueError("客户或产品不存在于当前租户或已停用")
    dialect = db.get_bind().dialect.name
    if dialect not in {"sqlite", "postgresql"}:
        raise ValueError("客户产品关联暂不支持当前数据库类型")
    statement = (
        (
            sqlite_insert(CustomerProductLink)
            if dialect == "sqlite"
            else pg_insert(CustomerProductLink)
        )
        .values(tenant_id=tenant, purchase_unit_id=purchase_unit_id, product_id=product_id)
        .on_conflict_do_nothing(index_elements=["tenant_id", "purchase_unit_id", "product_id"])
    )
    inserted_id = db.execute(statement.returning(CustomerProductLink.id)).scalar_one_or_none()
    link = (
        db.query(CustomerProductLink)
        .filter_by(tenant_id=tenant, purchase_unit_id=purchase_unit_id, product_id=product_id)
        .one()
    )
    return link, inserted_id is not None
