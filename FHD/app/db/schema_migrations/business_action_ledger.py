"""Dormant SQLite ledger schema management; no ORM registration or startup hook.

Call only with an explicitly selected migration connection. This does not enable
execution, prove reconciliation readiness, or read/write Alembic revision stamps.
PostgreSQL and offline migration contexts are intentionally unsupported.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic.operations import Operations

TABLE_NAME = "agent_business_actions"
# Exact committed AgentBusinessActionRecord contract; no invented constraints.
_COLUMNS = (
    ("action_key", 64),
    ("tenant_id", 128),
    ("mod_id", 128),
    ("business_action_id", 256),
    ("tool_id", 128),
    ("action", 64),
    ("user_id", 128),
    ("fingerprint", 64),
    ("owner", 64),
    ("run_id", 96),
    ("state", 32),
    ("receipt_json", None),
    ("created_at", 48),
    ("updated_at", 48),
)


def business_action_columns() -> tuple[sa.Column, ...]:
    """Fresh canonical columns for explicit DDL and the private-registry mapper."""
    return tuple(
        sa.Column(
            name,
            sa.String(length) if length else sa.Text(),
            primary_key=name == "action_key",
            nullable=False,
            default="{}" if name == "receipt_json" else None,
        )
        for name, length in _COLUMNS
    )


class LedgerSchemaError(ValueError):
    """Missing, unsupported or incompatible schema; never repair implicitly."""


def _connection(operations: Operations):
    bind = operations.get_bind()
    if not isinstance(bind, sa.engine.Connection) or bind.dialect.name != "sqlite":
        raise LedgerSchemaError("ledger schema preparation requires a live SQLite connection")
    return bind


def validate_business_action_schema(operations: Operations) -> None:
    """Inspect physical schema, never trust a version stamp or table name alone."""
    bind = _connection(operations)
    if bind.execute(
        sa.text("SELECT 1 FROM sqlite_temp_master WHERE name=:name"), {"name": TABLE_NAME}
    ).first():
        raise LedgerSchemaError("temporary ledger shadow is unsupported")
    inspector = sa.inspect(bind)
    if not inspector.has_table(TABLE_NAME):
        raise LedgerSchemaError("business-action ledger table is missing")
    row = bind.execute(
        sa.text("SELECT type, sql FROM sqlite_master WHERE name=:name"), {"name": TABLE_NAME}
    ).one_or_none()
    if row is None or row.type != "table" or not row.sql:
        raise LedgerSchemaError("business-action ledger is not an ordinary table")
    if any(word in row.sql.upper() for word in ("VIRTUAL", "WITHOUT ROWID", "COLLATE")):
        raise LedgerSchemaError("unsupported ledger table semantics")
    columns = inspector.get_columns(TABLE_NAME)
    if [column["name"] for column in columns] != [name for name, _ in _COLUMNS]:
        raise LedgerSchemaError("ledger columns differ from the exact contract")
    for column, (name, length) in zip(columns, _COLUMNS, strict=True):
        expected = f"VARCHAR({length})" if length else "TEXT"
        if (
            str(column["type"]).upper() != expected
            or column["nullable"] is not False
            or column.get("default") is not None
            or column.get("computed") is not None
        ):
            raise LedgerSchemaError(f"incompatible ledger column: {name}")
    if inspector.get_pk_constraint(TABLE_NAME).get("constrained_columns") != ["action_key"]:
        raise LedgerSchemaError("ledger primary key differs")
    # Raw SQLite metadata also catches hidden columns and indexes SQLAlchemy may
    # omit (e.g. unsupported expression indexes). Fixed identifier, no input SQL.
    if any(
        row[6] != 0 for row in bind.exec_driver_sql('PRAGMA table_xinfo("agent_business_actions")')
    ):
        raise LedgerSchemaError("hidden ledger columns are unsupported")
    if any(
        row[3] != "pk"
        for row in bind.exec_driver_sql('PRAGMA index_list("agent_business_actions")')
    ):
        raise LedgerSchemaError("unexpected physical ledger index")
    if any(
        (
            inspector.get_foreign_keys(TABLE_NAME),
            inspector.get_unique_constraints(TABLE_NAME),
            inspector.get_check_constraints(TABLE_NAME),
            inspector.get_indexes(TABLE_NAME),
        )
    ):
        raise LedgerSchemaError("unexpected ledger constraints or indexes")
    if bind.execute(
        sa.text(
            "SELECT 1 FROM sqlite_master WHERE type='trigger' AND tbl_name=:name "
            "UNION ALL SELECT 1 FROM sqlite_temp_master WHERE type='trigger' AND tbl_name=:name"
        ),
        {"name": TABLE_NAME},
    ).first():
        raise LedgerSchemaError("unexpected ledger trigger")


def prepare_business_action_schema(operations: Operations, *, opt_in: bool = False) -> bool:
    """Explicit migration API; False does nothing, True creates/validates only.

    The caller owns connection/transaction/backup selection. Existing incompatible
    data is never altered. No runtime or default migration path calls this API.
    """
    if type(opt_in) is not bool:
        raise LedgerSchemaError("ledger schema opt-in must be an explicit boolean")
    if not opt_in:
        return False
    bind = _connection(operations)
    if not sa.inspect(bind).has_table(TABLE_NAME):
        operations.create_table(TABLE_NAME, *business_action_columns())
    validate_business_action_schema(operations)
    return True


def retain_business_action_schema(operations: Operations) -> None:
    """Rollback policy: retain all claims/receipts; no DROP, DML or restamping.

    Missing/incompatible schema is reported, not repaired or removed. Disabling
    future use is a separate execution policy; this API never enables hooks.
    """
    validate_business_action_schema(operations)
