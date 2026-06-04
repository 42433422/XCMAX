"""Apply tenant data scopes to query filters (ABAC subset)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Query

from app.db.models.tenant import DataScope
from app.db.session import get_db


def get_scope_for_tenant(tenant_id: int, resource_type: str) -> dict[str, Any]:
    with get_db() as db:
        row = (
            db.query(DataScope)
            .filter(DataScope.tenant_id == tenant_id, DataScope.resource_type == resource_type)
            .order_by(DataScope.id.desc())
            .first()
        )
        if not row:
            return {}
        try:
            return json.loads(row.scope_json or "{}")
        except json.JSONDecodeError:
            return {}


def apply_data_scope(query: Query, *, tenant_id: int | None, resource_type: str) -> Query:
    """Narrow ``query`` when scope defines ``department_ids`` list on a matching column."""
    if tenant_id is None:
        return query
    scope = get_scope_for_tenant(tenant_id, resource_type)
    dept_ids = scope.get("department_ids")
    if not dept_ids:
        return query
    model = query.column_descriptions[0]["entity"]
    if hasattr(model, "department_id"):
        return query.filter(model.department_id.in_(dept_ids))
    return query
