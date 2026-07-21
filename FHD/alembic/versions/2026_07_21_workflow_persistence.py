"""workflow_definitions / workflow_runs / workflow_run_steps 三张表迁移。

新增持久化 PlanGraph 与运行实例所需的表结构。Revision 在 ``2026_07_05_employee_run_logs``
之上线性追加。

Revision ID: 2026_07_21_workflow_persistence
Revises: 2026_07_05_employee_run_logs
Create Date: 2026-07-21
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "2026_07_21_workflow_persistence"
down_revision: Union[str, Sequence[str], None] = "2026_07_05_employee_run_logs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE_DEFINITION = "workflow_definitions"
_TABLE_RUN = "workflow_runs"
_TABLE_STEP = "workflow_run_steps"


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # 1) workflow_definitions
    if not insp.has_table(_TABLE_DEFINITION):
        op.create_table(
            _TABLE_DEFINITION,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.Integer(), nullable=True),
            sa.Column("name", sa.String(length=128), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("trigger_type", sa.String(length=32), nullable=False, server_default="manual"),
            sa.Column("trigger_config", sa.Text(), nullable=True),
            sa.Column("nodes", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("edges", sa.Text(), nullable=True, server_default="[]"),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_workflow_definitions_tenant_id", _TABLE_DEFINITION, ["tenant_id"])
        op.create_index("ix_workflow_definitions_name", _TABLE_DEFINITION, ["name"])
        op.create_index("ix_workflow_definitions_is_active", _TABLE_DEFINITION, ["is_active"])
        op.create_index(
            "ix_workflow_definitions_tenant_active", _TABLE_DEFINITION, ["tenant_id", "is_active"]
        )

    # 2) workflow_runs
    if not insp.has_table(_TABLE_RUN):
        op.create_table(
            _TABLE_RUN,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("definition_id", sa.Integer(), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("triggered_by", sa.String(length=32), nullable=False, server_default="user"),
            sa.Column("trigger_payload", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("steps_snapshot", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(
                ["definition_id"], ["workflow_definitions.id"], ondelete="CASCADE"
            ),
        )
        op.create_index("ix_workflow_runs_definition_id", _TABLE_RUN, ["definition_id"])
        op.create_index("ix_workflow_runs_tenant_id", _TABLE_RUN, ["tenant_id"])
        op.create_index("ix_workflow_runs_status", _TABLE_RUN, ["status"])
        op.create_index(
            "ix_workflow_runs_def_status", _TABLE_RUN, ["definition_id", "status"]
        )
        op.create_index(
            "ix_workflow_runs_tenant_started", _TABLE_RUN, ["tenant_id", "started_at"]
        )

    # 3) workflow_run_steps
    if not insp.has_table(_TABLE_STEP):
        op.create_table(
            _TABLE_STEP,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("run_id", sa.Integer(), nullable=False),
            sa.Column("node_id", sa.String(length=128), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("result", sa.Text(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["run_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_workflow_run_steps_run_id", _TABLE_STEP, ["run_id"])
        op.create_index(
            "ix_workflow_run_steps_run_node", _TABLE_STEP, ["run_id", "node_id"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if insp.has_table(_TABLE_STEP):
        op.drop_index("ix_workflow_run_steps_run_node", table_name=_TABLE_STEP)
        op.drop_index("ix_workflow_run_steps_run_id", table_name=_TABLE_STEP)
        op.drop_table(_TABLE_STEP)

    if insp.has_table(_TABLE_RUN):
        op.drop_index("ix_workflow_runs_tenant_started", table_name=_TABLE_RUN)
        op.drop_index("ix_workflow_runs_def_status", table_name=_TABLE_RUN)
        op.drop_index("ix_workflow_runs_status", table_name=_TABLE_RUN)
        op.drop_index("ix_workflow_runs_tenant_id", table_name=_TABLE_RUN)
        op.drop_index("ix_workflow_runs_definition_id", table_name=_TABLE_RUN)
        op.drop_table(_TABLE_RUN)

    if insp.has_table(_TABLE_DEFINITION):
        op.drop_index("ix_workflow_definitions_tenant_active", table_name=_TABLE_DEFINITION)
        op.drop_index("ix_workflow_definitions_is_active", table_name=_TABLE_DEFINITION)
        op.drop_index("ix_workflow_definitions_name", table_name=_TABLE_DEFINITION)
        op.drop_index("ix_workflow_definitions_tenant_id", table_name=_TABLE_DEFINITION)
        op.drop_table(_TABLE_DEFINITION)
