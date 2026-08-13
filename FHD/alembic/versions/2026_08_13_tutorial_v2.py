"""Add tutorial V2 control plane and tenant-scope approval instances.

Revision ID: 2026_08_13_tutorial_v2
Revises: 2026_08_12_agent_task_execution
Create Date: 2026-08-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2026_08_13_tutorial_v2"
down_revision: str | Sequence[str] | None = "2026_08_12_agent_task_execution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_names(inspector: sa.Inspector, table: str) -> set[str]:
    return {str(row.get("name") or "") for row in inspector.get_columns(table)}


def _index_names(inspector: sa.Inspector, table: str) -> set[str]:
    return {str(row.get("name") or "") for row in inspector.get_indexes(table)}


def _add_approval_tenant_scope(bind) -> None:
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "approval_requests" in tables:
        if "tenant_id" not in _column_names(inspector, "approval_requests"):
            with op.batch_alter_table("approval_requests") as batch:
                batch.add_column(sa.Column("tenant_id", sa.Integer(), nullable=True))
        op.execute(
            sa.text(
                "UPDATE approval_requests SET tenant_id = "
                "(SELECT users.tenant_id FROM users WHERE users.id = approval_requests.applicant_id) "
                "WHERE tenant_id IS NULL"
            )
        )
        inspector = sa.inspect(bind)
        if "ix_approval_requests_tenant_id" not in _index_names(inspector, "approval_requests"):
            op.create_index("ix_approval_requests_tenant_id", "approval_requests", ["tenant_id"])
        if "ix_approval_requests_tenant_status" not in _index_names(
            sa.inspect(bind), "approval_requests"
        ):
            op.create_index(
                "ix_approval_requests_tenant_status",
                "approval_requests",
                ["tenant_id", "status"],
            )

    inspector = sa.inspect(bind)
    if "approval_records" in tables:
        if "tenant_id" not in _column_names(inspector, "approval_records"):
            with op.batch_alter_table("approval_records") as batch:
                batch.add_column(sa.Column("tenant_id", sa.Integer(), nullable=True))
        op.execute(
            sa.text(
                "UPDATE approval_records SET tenant_id = "
                "(SELECT approval_requests.tenant_id FROM approval_requests "
                "WHERE approval_requests.id = approval_records.request_id) "
                "WHERE tenant_id IS NULL"
            )
        )
        inspector = sa.inspect(bind)
        if "ix_approval_records_tenant_id" not in _index_names(inspector, "approval_records"):
            op.create_index("ix_approval_records_tenant_id", "approval_records", ["tenant_id"])
        if "ix_approval_records_tenant_request" not in _index_names(
            sa.inspect(bind), "approval_records"
        ):
            op.create_index(
                "ix_approval_records_tenant_request",
                "approval_records",
                ["tenant_id", "request_id"],
            )


def _create_tutorial_tables(bind) -> None:
    tables = set(sa.inspect(bind).get_table_names())
    if "tutorial_workspaces" not in tables:
        op.create_table(
            "tutorial_workspaces",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("source_tenant_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("tutorial_tenant_id", sa.Integer(), nullable=False),
            sa.Column("active_key", sa.String(length=96), nullable=True),
            sa.Column("generation", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="active"),
            sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("purge_after", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["source_tenant_id"], ["tenants.id"]),
            sa.ForeignKeyConstraint(["tutorial_tenant_id"], ["tenants.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.UniqueConstraint("tutorial_tenant_id", name="uq_tutorial_workspace_tenant"),
            sa.UniqueConstraint("active_key", name="uq_tutorial_workspace_active_key"),
            sa.UniqueConstraint(
                "source_tenant_id",
                "user_id",
                "generation",
                name="uq_tutorial_workspace_generation",
            ),
        )
        op.create_index(
            "ix_tutorial_workspace_owner_status",
            "tutorial_workspaces",
            ["source_tenant_id", "user_id", "status"],
        )
        op.create_index(
            "ix_tutorial_workspaces_source_tenant_id",
            "tutorial_workspaces",
            ["source_tenant_id"],
        )
        op.create_index("ix_tutorial_workspaces_user_id", "tutorial_workspaces", ["user_id"])
        op.create_index(
            "ix_tutorial_workspaces_tutorial_tenant_id",
            "tutorial_workspaces",
            ["tutorial_tenant_id"],
        )
        op.create_index("ix_tutorial_workspaces_status", "tutorial_workspaces", ["status"])
        op.create_index("ix_tutorial_workspaces_active_key", "tutorial_workspaces", ["active_key"])
        op.create_index(
            "ix_tutorial_workspaces_purge_after", "tutorial_workspaces", ["purge_after"]
        )

    tables = set(sa.inspect(bind).get_table_names())
    if "tutorial_runs" not in tables:
        op.create_table(
            "tutorial_runs",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("workspace_id", sa.String(length=36), nullable=False),
            sa.Column("source_tenant_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("course_id", sa.String(length=64), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False, server_default="2"),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="active"),
            sa.Column("active_key", sa.String(length=96), nullable=True),
            sa.Column("current_step_id", sa.String(length=96), nullable=False),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_entered_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_left_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(
                ["workspace_id"], ["tutorial_workspaces.id"], ondelete="CASCADE"
            ),
            sa.UniqueConstraint("active_key", name="uq_tutorial_run_active_key"),
        )
        op.create_index("ix_tutorial_runs_workspace_id", "tutorial_runs", ["workspace_id"])
        op.create_index("ix_tutorial_runs_source_tenant_id", "tutorial_runs", ["source_tenant_id"])
        op.create_index("ix_tutorial_runs_user_id", "tutorial_runs", ["user_id"])
        op.create_index("ix_tutorial_runs_course_id", "tutorial_runs", ["course_id"])
        op.create_index("ix_tutorial_runs_status", "tutorial_runs", ["status"])
        op.create_index("ix_tutorial_runs_active_key", "tutorial_runs", ["active_key"])
        op.create_index(
            "ix_tutorial_run_owner_status",
            "tutorial_runs",
            ["source_tenant_id", "user_id", "status"],
        )
        op.create_index(
            "ix_tutorial_run_workspace_course",
            "tutorial_runs",
            ["workspace_id", "course_id", "version"],
        )

    tables = set(sa.inspect(bind).get_table_names())
    if "tutorial_step_evidence" not in tables:
        op.create_table(
            "tutorial_step_evidence",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("run_id", sa.String(length=36), nullable=False),
            sa.Column("step_id", sa.String(length=96), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
            sa.Column(
                "result_code", sa.String(length=64), nullable=False, server_default="not_verified"
            ),
            sa.Column("entity_refs_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("counts_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["run_id"], ["tutorial_runs.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("run_id", "step_id", name="uq_tutorial_evidence_run_step"),
        )
        op.create_index("ix_tutorial_step_evidence_run_id", "tutorial_step_evidence", ["run_id"])
        op.create_index(
            "ix_tutorial_evidence_run_status",
            "tutorial_step_evidence",
            ["run_id", "status"],
        )


def upgrade() -> None:
    bind = op.get_bind()
    _add_approval_tenant_scope(bind)
    _create_tutorial_tables(bind)


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "tutorial_step_evidence" in tables:
        op.drop_table("tutorial_step_evidence")
    if "tutorial_runs" in tables:
        op.drop_table("tutorial_runs")
    if "tutorial_workspaces" in tables:
        op.drop_table("tutorial_workspaces")
    tables = set(sa.inspect(bind).get_table_names())
    if "approval_records" in tables and "tenant_id" in _column_names(
        sa.inspect(bind), "approval_records"
    ):
        with op.batch_alter_table("approval_records") as batch:
            batch.drop_column("tenant_id")
    if "approval_requests" in tables and "tenant_id" in _column_names(
        sa.inspect(bind), "approval_requests"
    ):
        with op.batch_alter_table("approval_requests") as batch:
            batch.drop_column("tenant_id")
