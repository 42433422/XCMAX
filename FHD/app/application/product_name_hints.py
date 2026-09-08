"""Resolve product hints from scoped business rows without guessing ambiguous IDs."""

from sqlalchemy import or_, select

from app.db.models.product import Product
from app.db.session import get_db


def resolve_product_name_hints(tenant_id: int, hints: list[str]) -> list[dict]:
    table = Product.__table__
    base = (table.c.tenant_id == tenant_id, table.c.is_active == 1)
    result = []
    with get_db() as db:
        for hint in hints:
            exact = or_(table.c.name == hint, table.c.model_number == hint)
            query = select(table.c.id, table.c.name, table.c.model_number, table.c.specification)
            rows = (
                db.execute(query.where(*base, exact).order_by(table.c.id).limit(21))
                .mappings()
                .all()
            )
            exact_match = bool(rows)
            if not rows:
                partial = or_(
                    table.c.name.icontains(hint, autoescape=True),
                    table.c.model_number.icontains(hint, autoescape=True),
                )
                rows = (
                    db.execute(query.where(*base, partial).order_by(table.c.id).limit(21))
                    .mappings()
                    .all()
                )
            status = (
                "resolved"
                if exact_match and len(rows) == 1
                else "ambiguous"
                if rows
                else "not_found"
            )
            result.append(
                {
                    "hint": hint,
                    "status": status,
                    "product_id": rows[0]["id"] if status == "resolved" else None,
                    "match_type": "exact" if exact_match else "partial" if rows else "none",
                    "candidates": [dict(row) for row in rows[:20]],
                    "total": len(rows) if len(rows) <= 20 else None,
                    "truncated": len(rows) > 20,
                    "requires_confirmation": status == "ambiguous",
                }
            )
    return result
