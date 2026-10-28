"""Read-only guarded-host readiness checks; no migration or authorization grant.

Accept the exact canonical SQLite run/worker/approval schema, not merely names or
revision stamps. Equivalent but differently declared legacy schemas require review;
this API never creates a reference database, alters storage, or adopts old data.
"""

import re

from sqlalchemy import inspect
from sqlalchemy.schema import CreateIndex, CreateTable

from app.db.models.agent import AgentRunRecord, AgentTaskExecutionRecord
from app.db.models.agent_approval import AgentApprovalConsumption
from app.db.models.workflow import WorkflowPlan


def validate_owned_host_runtime_schema(connection):
    """Validate actual main tables and reject connection-local shadow authority."""
    if connection.dialect.name != "sqlite":
        raise RuntimeError("owned host runtime requires canonical SQLite schema")
    inspector = inspect(connection)
    compact = lambda sql: re.sub(r"\s+", "", str(sql or "")).lower()
    for model in (AgentRunRecord, AgentTaskExecutionRecord, AgentApprovalConsumption, WorkflowPlan):
        table = model.__table__
        expected = {
            ("table", table.name): compact(CreateTable(table).compile(dialect=connection.dialect))
        }
        expected.update(
            {
                ("index", index.name): compact(
                    CreateIndex(index).compile(dialect=connection.dialect)
                )
                for index in table.indexes
            }
        )
        actual = {
            (kind, name): compact(sql)
            for kind, name, sql in connection.exec_driver_sql(
                "SELECT type,name,sql FROM main.sqlite_master WHERE tbl_name=? AND sql IS NOT NULL",
                (table.name,),
            )
        }
        if (
            actual != expected
            or connection.exec_driver_sql(
                "SELECT 1 FROM temp.sqlite_master WHERE name=? OR tbl_name=? LIMIT 1",
                (table.name, table.name),
            ).first()
        ):
            raise RuntimeError(f"owned host runtime schema differs: {table.name}")
        columns = inspector.get_columns(table.name, schema="main")
        if len(columns) != len(table.columns) or any(
            got["name"] != wanted.name
            or str(got["type"]).upper() != wanted.type.compile(dialect=connection.dialect).upper()
            or got["nullable"] != wanted.nullable
            or compact(got.get("default"))
            != compact(
                wanted.server_default.arg.compile(dialect=connection.dialect)
                if wanted.server_default is not None
                else None
            )
            or got.get("computed") is not None
            for got, wanted in zip(columns, table.columns, strict=True)
        ):
            raise RuntimeError(f"owned host runtime columns differ: {table.name}")
        if inspector.get_pk_constraint(table.name, schema="main").get("constrained_columns") != [
            column.name for column in table.primary_key.columns
        ]:
            raise RuntimeError(f"owned host runtime primary key differs: {table.name}")
        # Exact canonical DDL above includes all unique/check/FK declarations and
        # indexes (including sort order/expressions). Refuse hidden columns too.
        if any(
            row[6] != 0
            for row in connection.exec_driver_sql(f'PRAGMA main.table_xinfo("{table.name}")')
        ):
            raise RuntimeError(f"owned host runtime hidden column: {table.name}")
