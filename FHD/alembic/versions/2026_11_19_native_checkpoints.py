"""Provision native SQLite checkpoints before guarded serving begins."""

from alembic.script import ScriptDirectory

from alembic import op

revision = "2026_11_19_native_checkpoints"
down_revision = "2026_11_19_chat_revision"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "sqlite":
        # PostgreSQL keeps its existing advisory-locked native migration owner.
        return
    from langgraph.checkpoint.sqlite import SqliteSaver

    from app.infrastructure.workflow.checkpoint_bridge import validate_sqlite_checkpoint_schema

    native = connection.connection.driver_connection
    validate_sqlite_checkpoint_schema(native, allow_missing=True)
    # Native setup uses executescript; commit at Alembic's explicit migration
    # boundary instead of allowing it to commit a surrounding transaction silently.
    with op.get_context().autocommit_block():
        SqliteSaver(native).setup()
    validate_sqlite_checkpoint_schema(native)


def downgrade() -> None:
    # Retain checkpoints and pending writes as recovery receipts. Run the parent
    # safety guard before Alembic can move this revision's version stamp.
    context = op.get_context()
    parent = ScriptDirectory.from_config(context.config).get_revision(down_revision)
    if parent is None:
        raise RuntimeError("Native checkpoints are missing their conversation-safety parent")
    parent.module.downgrade()
