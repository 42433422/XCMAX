from __future__ import annotations

from app.application.ports.purchase_unit_query import PurchaseUnitQueryPort
from app.db.models import PurchaseUnit
from app.db.session import get_db
from app.infrastructure.tenant_scope import apply_tenant_filter


class SQLAlchemyPurchaseUnitQuery(PurchaseUnitQueryPort):
    """从 products.db.purchase_units 表读取客户名称列表（去重保序）。"""

    def list_purchase_units(self) -> list[str]:
        with get_db() as db:
            query = apply_tenant_filter(db.query(PurchaseUnit.unit_name), PurchaseUnit)
            rows = query.filter(PurchaseUnit.is_active == True).all()
            names: list[str] = [c[0] for c in rows if c and c[0]]
            seen = set()
            result: list[str] = []
            for n in names:
                if n in seen:
                    continue
                seen.add(n)
                result.append(n)
            return result
