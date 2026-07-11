"""Static SQLite upgrade statements for retained mobile notification tables."""

from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy import text
from sqlalchemy.sql.elements import TextClause

_SCHEMA_SQL: dict[str, dict[str, TextClause]] = {
    "mobile_device_tokens": {
        "add_notification_audience": text(
            "ALTER TABLE mobile_device_tokens ADD COLUMN "
            "notification_audience VARCHAR(32) NOT NULL DEFAULT 'enterprise'"
        ),
        "add_tenant_id": text(
            "ALTER TABLE mobile_device_tokens ADD COLUMN tenant_id INTEGER NOT NULL DEFAULT 0"
        ),
        "backfill_tenant_all": text(
            "UPDATE mobile_device_tokens SET tenant_id = COALESCE("
            "(SELECT users.tenant_id FROM users "
            "WHERE users.id = mobile_device_tokens.user_id), 0) "
            "WHERE 1 = 1"
        ),
        "backfill_tenant_null": text(
            "UPDATE mobile_device_tokens SET tenant_id = COALESCE("
            "(SELECT users.tenant_id FROM users "
            "WHERE users.id = mobile_device_tokens.user_id), 0) "
            "WHERE tenant_id IS NULL"
        ),
        "default_tenant_null": text(
            "UPDATE mobile_device_tokens SET tenant_id = 0 WHERE tenant_id IS NULL"
        ),
        "create_audience_index": text(
            "CREATE INDEX IF NOT EXISTS "
            "ix_mobile_device_tokens_notification_audience "
            "ON mobile_device_tokens (notification_audience)"
        ),
        "create_tenant_index": text(
            "CREATE INDEX IF NOT EXISTS ix_mobile_device_tokens_tenant_id "
            "ON mobile_device_tokens (tenant_id)"
        ),
    },
    "mobile_notification_outbox": {
        "add_notification_audience": text(
            "ALTER TABLE mobile_notification_outbox ADD COLUMN "
            "notification_audience VARCHAR(32) NOT NULL DEFAULT 'enterprise'"
        ),
        "add_tenant_id": text(
            "ALTER TABLE mobile_notification_outbox ADD COLUMN tenant_id INTEGER NOT NULL DEFAULT 0"
        ),
        "add_event_id": text(
            "ALTER TABLE mobile_notification_outbox ADD COLUMN event_id VARCHAR(256)"
        ),
        "backfill_tenant_all": text(
            "UPDATE mobile_notification_outbox SET tenant_id = COALESCE("
            "(SELECT users.tenant_id FROM users "
            "WHERE users.id = mobile_notification_outbox.user_id), 0) "
            "WHERE 1 = 1"
        ),
        "backfill_tenant_null": text(
            "UPDATE mobile_notification_outbox SET tenant_id = COALESCE("
            "(SELECT users.tenant_id FROM users "
            "WHERE users.id = mobile_notification_outbox.user_id), 0) "
            "WHERE tenant_id IS NULL"
        ),
        "default_tenant_null": text(
            "UPDATE mobile_notification_outbox SET tenant_id = 0 WHERE tenant_id IS NULL"
        ),
        "create_audience_index": text(
            "CREATE INDEX IF NOT EXISTS "
            "ix_mobile_notification_outbox_notification_audience "
            "ON mobile_notification_outbox (notification_audience)"
        ),
        "create_tenant_index": text(
            "CREATE INDEX IF NOT EXISTS ix_mobile_notification_outbox_tenant_id "
            "ON mobile_notification_outbox (tenant_id)"
        ),
    },
}


def notification_schema_statements(table: str) -> Mapping[str, TextClause]:
    """Return predeclared SQL for one of the two fixed model-owned tables."""

    return _SCHEMA_SQL[table]
