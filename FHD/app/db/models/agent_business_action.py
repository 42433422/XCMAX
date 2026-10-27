"""Real host ledger mapping; deliberately absent from shared Base and reexports.

Import registers mapping only, never connects or creates schema. Consumers must
validate the selected host session before use and supply their own scope filters;
this mapping grants no authorization or claim/replay semantics.
"""

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.orm import Session, registry

from app.db.schema_migrations.business_action_ledger import (
    TABLE_NAME,
    business_action_columns,
    validate_business_action_schema,
)

ledger_metadata = sa.MetaData()
_ledger_registry = registry(metadata=ledger_metadata)


@_ledger_registry.mapped
class AgentBusinessActionRecord:
    """The same durable host table, not a shadow database or replacement API."""

    __tablename__ = TABLE_NAME
    __table__ = sa.Table(TABLE_NAME, ledger_metadata, *business_action_columns())


def validate_ledger_storage(session: Session) -> None:
    """Fail closed on missing/incompatible SQLite schema; performs no DDL."""
    validate_business_action_schema(Operations(MigrationContext.configure(session.connection())))
