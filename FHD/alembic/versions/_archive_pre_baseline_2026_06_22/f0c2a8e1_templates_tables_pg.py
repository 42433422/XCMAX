"""templates_tables_pg

Revision ID: f0c2a8e1_templates
Revises: f8c2e1d0abb7
Create Date: 2026-04-11

PostgreSQL: templates / template_usage_log（与 app/db/init_db.init_template_tables SQLite DDL 对齐）。
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect, text

revision: str = "f0c2a8e1_templates"
down_revision: Union[str, Sequence[str], None] = "f8c2e1d0abb7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, table_name: str) -> bool:
    return table_name in inspect(conn).get_table_names()


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return

    if not _table_exists(conn, "templates"):
        conn.execute(
            text(
                """
                CREATE TABLE templates (
                    id BIGSERIAL PRIMARY KEY,
                    template_key TEXT,
                    template_name TEXT NOT NULL,
                    template_type TEXT,
                    original_file_path TEXT,
                    analyzed_data TEXT,
                    editable_config TEXT,
                    zone_config TEXT,
                    merged_cells_config TEXT,
                    style_config TEXT,
                    business_rules TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

    if not _table_exists(conn, "template_usage_log"):
        conn.execute(
            text(
                """
                CREATE TABLE template_usage_log (
                    id BIGSERIAL PRIMARY KEY,
                    template_id BIGINT NOT NULL REFERENCES templates(id) ON DELETE CASCADE,
                    action TEXT NOT NULL,
                    result TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_templates_type_active ON templates (template_type, is_active)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_template_usage_log_template_id ON template_usage_log (template_id)"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return
    conn.execute(text("DROP TABLE IF EXISTS template_usage_log"))
    conn.execute(text("DROP TABLE IF EXISTS templates"))
