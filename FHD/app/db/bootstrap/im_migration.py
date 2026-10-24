"""Connection-scoped adapter for the existing IM provenance migration step."""

from __future__ import annotations

from logging import Logger

from sqlalchemy.engine import Engine

from app.db.bootstrap.contracts import InspectorFactory
from app.utils.operational_errors import RECOVERABLE_ERRORS


def ensure_message_provenance(engine: Engine, inspect: InspectorFactory, logger: Logger) -> None:
    try:
        if "im_messages" not in set(inspect(engine).get_table_names() or []):
            return
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        from app.db.schema_migrations.im_message_provenance import apply_message_provenance

        with engine.begin() as connection:
            operations = Operations(MigrationContext.configure(connection))
            apply_message_provenance(operations)
    except RECOVERABLE_ERRORS as exc:
        logger.warning("企业客服消息来源列兼容补齐失败（可执行对应 Alembic 迁移）：%s", exc)
