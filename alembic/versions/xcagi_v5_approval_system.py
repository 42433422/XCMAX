# -*- coding: utf-8 -*-
"""
审批流数据库迁移脚本

创建审批流相关的数据库表
"""

from alembic import op
import sqlalchemy as sa


revision = "xcagi_v5_approval_system"
down_revision = "f0c2a8e1_templates"
branch_labels = None
depends_on = None


def upgrade():
    """创建审批流相关表"""

    op.create_table(
        "approval_flows",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("flow_key", sa.String(64), nullable=False),
        sa.Column("flow_name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("industry", sa.String(64), nullable=True, server_default="通用"),
        sa.Column("node_type", sa.String(32), nullable=True, server_default="serial"),
        sa.Column("allow_transfer", sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column("allow_delegate", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column("allow_withdraw", sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column("timeout_hours", sa.Integer(), nullable=True, server_default="48"),
        sa.Column("is_active", sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column("is_deleted", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_flow_key_active", "approval_flows", ["flow_key", "is_active"], unique=False)
    op.create_index(op.f("ix_approval_flows_is_active"), "approval_flows", ["is_active"], unique=False)
    op.create_index(op.f("ix_approval_flows_flow_key"), "approval_flows", ["flow_key"], unique=True)

    op.create_table(
        "approval_flow_nodes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("flow_id", sa.Integer(), sa.ForeignKey("approval_flows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_name", sa.String(128), nullable=False),
        sa.Column("node_order", sa.Integer(), nullable=False),
        sa.Column("node_type", sa.String(32), nullable=True, server_default="serial"),
        sa.Column("approver_type", sa.String(32), nullable=False),
        sa.Column("approver_ids", sa.Text(), nullable=True),
        sa.Column("min_approvals", sa.Integer(), nullable=True, server_default="1"),
        sa.Column("condition_expression", sa.Text(), nullable=True),
        sa.Column("condition_description", sa.String(256), nullable=True),
        sa.Column("timeout_hours", sa.Integer(), nullable=True),
        sa.Column("timeout_action", sa.String(32), nullable=True, server_default="notify"),
        sa.Column("is_active", sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_approval_flow_nodes_flow_id"), "approval_flow_nodes", ["flow_id"], unique=False)

    op.create_table(
        "approval_requests",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("request_no", sa.String(64), nullable=False),
        sa.Column("flow_id", sa.Integer(), sa.ForeignKey("approval_flows.id"), nullable=False),
        sa.Column("business_type", sa.String(64), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=True),
        sa.Column("business_data", sa.Text(), nullable=True),
        sa.Column("applicant_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("applicant_name", sa.String(64), nullable=True),
        sa.Column("applicant_department", sa.String(64), nullable=True),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("current_node_id", sa.Integer(), sa.ForeignKey("approval_flow_nodes.id"), nullable=True),
        sa.Column("current_node_order", sa.Integer(), nullable=True, server_default="1"),
        sa.Column("status", sa.String(32), nullable=True, server_default="pending"),
        sa.Column("priority", sa.String(16), nullable=True, server_default="normal"),
        sa.Column("submitted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_by_name", sa.String(64), nullable=True),
        sa.Column("rejection_reason", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_approval_requests_request_no"), "approval_requests", ["request_no"], unique=True)
    op.create_index(op.f("ix_approval_requests_flow_id"), "approval_requests", ["flow_id"], unique=False)
    op.create_index(op.f("ix_approval_requests_applicant_id"), "approval_requests", ["applicant_id"], unique=False)
    op.create_index(op.f("ix_approval_requests_status"), "approval_requests", ["status"], unique=False)

    op.create_table(
        "approval_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.Integer(), sa.ForeignKey("approval_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_id", sa.Integer(), sa.ForeignKey("approval_flow_nodes.id"), nullable=False),
        sa.Column("node_name", sa.String(128), nullable=True),
        sa.Column("node_order", sa.Integer(), nullable=True),
        sa.Column("approver_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("approver_name", sa.String(64), nullable=True),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("opinion", sa.Text(), nullable=True),
        sa.Column("reject_reason", sa.String(512), nullable=True),
        sa.Column("is_passed", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column("transferred_from", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("transferred_to", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("delegate_user", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("action_time", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_approval_records_request_id"), "approval_records", ["request_id"], unique=False)
    op.create_index(op.f("ix_approval_records_approver_id"), "approval_records", ["approver_id"], unique=False)
    op.create_index("idx_request_node", "approval_records", ["request_id", "node_order"], unique=False)

    op.create_table(
        "approval_delegations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("delegator_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("delegate_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("flow_ids", sa.Text(), nullable=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(512), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_approval_delegations_delegator_id"), "approval_delegations", ["delegator_id"], unique=False)
    op.create_index(op.f("ix_approval_delegations_delegate_id"), "approval_delegations", ["delegate_id"], unique=False)
    op.create_index(op.f("ix_approval_delegations_is_active"), "approval_delegations", ["is_active"], unique=False)


def downgrade():
    op.drop_table("approval_delegations")
    op.drop_table("approval_records")
    op.drop_table("approval_requests")
    op.drop_table("approval_flow_nodes")
    op.drop_table("approval_flows")
