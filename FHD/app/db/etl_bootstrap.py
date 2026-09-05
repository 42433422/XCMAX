"""Idempotent ETL schema bootstrap for packaged SQLite desktops."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from sqlalchemy import Table, inspect, text

from app.db.base import Base
from app.db.models.etl import (
    EtlRun,
    EtlRunRow,
    EtlTargetConfig,
    EtlTemplate,
    EtlTemplateVersion,
    EtlUpload,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


def ensure_sqlite_etl_bootstrap(
    engine: Engine | None = None,
    *,
    database_url: str | None = None,
    swallow_errors: bool = True,
) -> None:
    """Create ETL tables when the packaged desktop starts without Alembic."""
    from app.db.init_db import _resolve_auth_bootstrap_engine

    real_engine = _resolve_auth_bootstrap_engine(engine, database_url=database_url)
    if real_engine is None or real_engine.dialect.name != "sqlite":
        return
    try:
        existing = set(inspect(real_engine).get_table_names() or [])
        model_tables: list[Table] = [
            cast("Table", EtlUpload.__table__),
            cast("Table", EtlTemplate.__table__),
            cast("Table", EtlTemplateVersion.__table__),
            cast("Table", EtlRun.__table__),
            cast("Table", EtlRunRow.__table__),
            cast("Table", EtlTargetConfig.__table__),
        ]
        missing = [table for table in model_tables if table.name not in existing]
        if missing:
            logger.info(
                "SQLite 缺少 ETL 表 %s，正在通过 ORM 创建 …",
                [table.name for table in missing],
            )
            Base.metadata.create_all(real_engine, tables=missing, checkfirst=True)
        # create_all does not add columns to an existing packaged desktop database.
        columns = {item["name"] for item in inspect(real_engine).get_columns("etl_runs")}
        with real_engine.begin() as connection:
            for name, ddl in (
                ("operation_kind", "ALTER TABLE etl_runs ADD COLUMN operation_kind VARCHAR(16)"),
                ("operation_token", "ALTER TABLE etl_runs ADD COLUMN operation_token VARCHAR(36)"),
                (
                    "operation_lease_until",
                    "ALTER TABLE etl_runs ADD COLUMN operation_lease_until DATETIME",
                ),
            ):
                if name not in columns:
                    connection.execute(text(ddl))
    except RECOVERABLE_ERRORS as exc:
        if swallow_errors:
            logger.warning("ensure_sqlite_etl_bootstrap 失败: %s", exc, exc_info=True)
            return
        raise
