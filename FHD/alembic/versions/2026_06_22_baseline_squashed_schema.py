"""squashed baseline — full schema as single source of truth

Revision ID: 2026_06_22_baseline
Revises:
Create Date: 2026-06-22

WHY THIS EXISTS
---------------
The previous lineage could not build a database from empty: ``initial_schema``
was a no-op that assumed ``create_all`` had already run, and later migrations
``ALTER``ed tables (e.g. ``sessions``) that no migration ever ``CREATE``d. So
``alembic upgrade head`` on a fresh DB failed, and Alembic was not the schema
source of truth — ``create_all`` + runtime ``ensure_*`` was.

This baseline squashes that history into one root that reproduces the REAL
runtime schema, so ``alembic upgrade head`` on an empty database yields exactly
what the app expects:

  * every ORM table (``Base.metadata.create_all``) — dialect-agnostic, idempotent
  * the few raw-SQL tables that have no ORM model (templates, template_usage_log,
    distillation_log, training_stats, excel_vector_*), PostgreSQL-only, copied
    verbatim from the archived migrations. These are excluded from autogenerate
    in ``alembic/env.py`` (they are managed outside the ORM on purpose).

The pre-2026-06-22 migrations are archived under
``alembic/versions/_archive_pre_baseline_2026_06_22/`` (Alembic does not recurse
into that subdir; ``recursive_version_locations`` is false). Git history keeps
the full record.

MIGRATING AN EXISTING DATABASE
------------------------------
Existing DBs were stamped with old revision ids Alembic no longer knows.
Re-baseline them once (schema is unchanged — this only rewrites alembic_version):

    python -m alembic stamp 2026_06_22_baseline --purge

Production on a real database runs ``alembic upgrade head`` from this baseline
(``FHD_SKIP_ALEMBIC=0`` — see helm ``values-prod.yaml`` and
``docker-compose.fhd-prod.yml``; the entrypoint gates on a non-empty
``DATABASE_URL``). SQLite single-host deployments leave ``DATABASE_URL`` empty and
build via ``create_all`` + ensure, so the entrypoint skips Alembic for them. Real
DBs predating this squash need the one-time stamp above; dev/desktop SQLite DBs
build fresh.
"""

from __future__ import annotations

from typing import Sequence, Union

from sqlalchemy import text

from alembic import op

revision: str = "2026_06_22_baseline"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Raw-SQL tables that intentionally have no ORM model. Verbatim from the archived
# migrations (f0c2a8e1 templates, b1f4a6d2 distillation/training, f3b2c1d9 vector).
# PostgreSQL-only, matching the original migrations' dialect guards. Kept in sync
# with the autogenerate exclusion list in alembic/env.py (_NON_ORM_TABLES).
_NON_ORM_PG_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS templates (
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
    """,
    """
    CREATE TABLE IF NOT EXISTS template_usage_log (
        id BIGSERIAL PRIMARY KEY,
        template_id BIGINT NOT NULL REFERENCES templates(id) ON DELETE CASCADE,
        action TEXT NOT NULL,
        result TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_templates_type_active ON templates (template_type, is_active)",
    "CREATE INDEX IF NOT EXISTS idx_template_usage_log_template_id ON template_usage_log (template_id)",
    """
    CREATE TABLE IF NOT EXISTS distillation_log (
        id BIGSERIAL PRIMARY KEY,
        query TEXT NOT NULL,
        intent TEXT NOT NULL,
        slots TEXT,
        confidence DOUBLE PRECISION DEFAULT 1.0,
        source TEXT DEFAULT 'manual',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        used_for_training INTEGER DEFAULT 0
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_intent ON distillation_log(intent)",
    "CREATE INDEX IF NOT EXISTS idx_used ON distillation_log(used_for_training)",
    """
    CREATE TABLE IF NOT EXISTS training_stats (
        id BIGSERIAL PRIMARY KEY,
        intent TEXT NOT NULL,
        count INTEGER DEFAULT 0,
        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE EXTENSION IF NOT EXISTS vector",
    """
    CREATE TABLE IF NOT EXISTS excel_vector_indexes (
        index_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        source_file TEXT NOT NULL,
        created_at DOUBLE PRECISION NOT NULL,
        updated_at DOUBLE PRECISION NOT NULL,
        chunk_count INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS excel_vector_chunks (
        chunk_id TEXT PRIMARY KEY,
        index_id TEXT NOT NULL REFERENCES excel_vector_indexes(index_id) ON DELETE CASCADE,
        content TEXT NOT NULL,
        embedding vector(256) NOT NULL,
        metadata JSONB NOT NULL,
        created_at DOUBLE PRECISION NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_excel_vector_chunks_index_id ON excel_vector_chunks(index_id)",
    "CREATE INDEX IF NOT EXISTS idx_excel_vector_chunks_embedding "
    "ON excel_vector_chunks USING ivfflat (embedding vector_cosine_ops)",
)


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Every ORM table, in FK-correct order, idempotently (checkfirst=True).
    from app.db.base import Base
    import app.db.models  # noqa: F401  (populates Base.metadata)

    Base.metadata.create_all(bind=conn, checkfirst=True)

    # 2. Raw-SQL, non-ORM tables (PostgreSQL only — they never existed on sqlite).
    if conn.dialect.name == "postgresql":
        for stmt in _NON_ORM_PG_DDL:
            conn.execute(text(stmt))


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        for tbl in (
            "excel_vector_chunks",
            "excel_vector_indexes",
            "training_stats",
            "distillation_log",
            "template_usage_log",
            "templates",
        ):
            conn.execute(text(f"DROP TABLE IF EXISTS {tbl} CASCADE"))

    from app.db.base import Base
    import app.db.models  # noqa: F401

    Base.metadata.drop_all(bind=conn)
