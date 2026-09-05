"""Atomic rollback DML; ORM image checks alone cannot protect a later flush."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import String, cast, delete, exists, inspect, or_, select, update
from sqlalchemy.exc import IntegrityError, OperationalError

from app.application.etl.errors import EtlError
from app.infrastructure.tenant_scope import tenant_id_for_write


def _conflict(label: str) -> EtlError:
    return EtlError(
        "ETL_ROLLBACK_CONCURRENT_CHANGE",
        f"{label}或关联数据在撤销期间发生变化，已停止撤销以避免覆盖或删除新数据",
        status_code=409,
    )


def _conditions(db: Any, obj: Any, keys: set[str], label: str) -> list[Any]:
    mapper = inspect(obj).mapper
    table = mapper.local_table
    tenant_id = tenant_id_for_write()
    if obj.tenant_id != tenant_id:
        raise _conflict(label)
    conditions = [table.c.tenant_id == tenant_id]
    keys |= {column.key for column in mapper.primary_key}
    for key in sorted(keys):
        value = getattr(obj, key)
        column = table.c[key]
        equality = column.is_(None) if value is None else column == value
        if (
            db.get_bind().dialect.name == "sqlite"
            and isinstance(value, datetime)
            and not value.microsecond
        ):
            # SQLite CURRENT_TIMESTAMP omits .000000; DateTime bind values include
            # it. Accept those two exact spellings without rounding subsecond edits.
            equality = or_(equality, cast(column, String) == value.strftime("%Y-%m-%d %H:%M:%S"))
        conditions.append(equality)
    return conditions


def _execute(db: Any, statement: Any, label: str) -> None:
    try:
        result = db.execute(statement)
    except IntegrityError as exc:
        # A concurrently created FK reference must never be deleted or cascaded away.
        raise _conflict(label) from exc
    except OperationalError as exc:
        code = getattr(exc.orig, "sqlite_errorcode", 0) or 0
        sqlstate = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
        if code & 0xFF in {5, 6} or sqlstate in {"40001", "40P01"}:
            raise _conflict(label) from exc
        raise
    if result.rowcount != 1:
        raise _conflict(label)


def restore_fields(db: Any, obj: Any, values: dict[str, Any], label: str) -> None:
    """Restore changed fields iff their observed values and tenant still match."""
    if not values:
        return
    with db.no_autoflush:
        table = inspect(obj).mapper.local_table
        statement = update(table).where(*_conditions(db, obj, set(values), label)).values(**values)
        _execute(db, statement, label)
        db.expire(obj)


def _logical_reference_guards(obj: Any) -> list[Any]:
    """Known legacy ERP name references, which have no database FK protection."""
    from app.db.models import Product, SalesOrder, SalesOrderItem, ShipmentRecord

    def absent(model, *conditions):
        return ~exists(select(1).where(model.__table__.c.tenant_id == obj.tenant_id, *conditions))

    shipment = ShipmentRecord.__table__.c
    if inspect(obj).mapper.local_table.name == "purchase_units":
        return [
            absent(Product, Product.__table__.c.unit == obj.unit_name),
            absent(
                ShipmentRecord,
                or_(shipment.purchase_unit == obj.unit_name, shipment.unit_id == obj.id),
            ),
            absent(SalesOrder, SalesOrder.__table__.c.customer_name == obj.unit_name),
        ]
    shipment_identity = (
        or_(shipment.model_number == obj.model_number, shipment.product_name == obj.name)
        if obj.model_number
        else shipment.product_name == obj.name
    )
    sales_item = SalesOrderItem.__table__.c
    return [
        absent(ShipmentRecord, shipment.purchase_unit == obj.unit, shipment_identity),
        absent(
            SalesOrderItem, sales_item.product_id.is_(None), sales_item.product_name == obj.name
        ),
    ]


def delete_created_row(db: Any, obj: Any, label: str) -> None:
    """Protect every observed column; retain rows when relationship safety is unknown."""
    with db.no_autoflush:
        mapper = inspect(obj).mapper
        table = mapper.local_table
        conditions = _conditions(db, obj, {column.key for column in mapper.columns}, label)
        dialect = db.get_bind().dialect.name
        if dialect != "sqlite":
            # String references can be inserted in PostgreSQL after DELETE's snapshot.
            # Until every reference writer has a shared locking/FK contract, retain rows.
            raise EtlError(
                "ETL_ROLLBACK_RELATION_GUARD_REQUIRED",
                f"当前数据库无法保证{label}关联数据的并发删除安全，已保留记录，请核对关联数据",
                status_code=409,
            )
        if db.connection().exec_driver_sql("PRAGMA foreign_keys").scalar() != 1:
            raise EtlError(
                "ETL_ROLLBACK_RELATION_GUARD_REQUIRED",
                "数据库未启用外键保护，已停止自动删除以保留关联数据",
                status_code=409,
            )
        # SQLite serializes writers: evaluate references within the DELETE, not in
        # an earlier read. This guards the known ERP references at deletion time.
        conditions.extend(_logical_reference_guards(obj))
        _execute(db, delete(table).where(*conditions), label)
        # Core DML deliberately bypasses ORM flush; do not leave a live deleted identity.
        db.expunge(obj)
