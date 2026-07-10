"""Allow AI workflow approvals without a configured traditional flow.

Revision ID: 2026_07_09_ai_approval
Revises: 2026_07_05_employee_run_logs
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2026_07_09_ai_approval"
down_revision: str | Sequence[str] | None = "2026_07_05_employee_run_logs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Traditional approval requests still provide both values. The nullable shape is
    # reserved for business_type=workflow_tool, whose pending plan lives in the
    # ApprovalService runtime and has no ApprovalFlowNode.
    with op.batch_alter_table("approval_requests") as batch_op:
        batch_op.alter_column("flow_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    # Rows that cannot satisfy the legacy schema are runtime-backed and cannot be
    # resumed after a downgrade, so remove only those special workflow rows.
    op.execute(
        "DELETE FROM approval_requests "
        "WHERE business_type = 'workflow_tool' AND flow_id IS NULL"
    )
    with op.batch_alter_table("approval_requests") as batch_op:
        batch_op.alter_column("flow_id", existing_type=sa.Integer(), nullable=False)
