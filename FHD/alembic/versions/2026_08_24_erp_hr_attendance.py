"""Move personnel and attendance ownership into the ERP database.

Revision ID: 2026_08_24_erp_hr_attendance
Revises: 2026_08_20_repair_products_uom
Create Date: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2026_08_24_erp_hr_attendance"
down_revision: str | Sequence[str] | None = "2026_08_20_repair_products_uom"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    required = {
        "erp_departments",
        "erp_employees",
        "erp_attendance_import_batches",
        "erp_attendance_daily_records",
        "erp_attendance_leave_records",
    }
    if required.issubset(existing):
        return
    partial = required & existing
    if partial:
        raise RuntimeError(f"ERP 人事考勤表处于不完整状态，拒绝继续迁移: {sorted(partial)}")

    op.create_table(
        "erp_departments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("parent_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("attendance_group", sa.String(200), nullable=False, server_default=""),
        sa.Column("source_system", sa.String(64), nullable=False, server_default="erp"),
        sa.Column("source_key", sa.String(500), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "tenant_id", "name", "parent_name", name="uq_erp_departments_tenant_identity"
        ),
    )
    op.create_index("ix_erp_departments_tenant_id", "erp_departments", ["tenant_id"])
    op.create_index("ix_erp_departments_tenant_name", "erp_departments", ["tenant_id", "name"])

    op.create_table(
        "erp_employees",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer(), nullable=True),
        sa.Column("identity_key", sa.String(500), nullable=False),
        sa.Column("employee_name", sa.String(200), nullable=False),
        sa.Column("department_id", sa.Integer(), nullable=True),
        sa.Column("department", sa.String(200), nullable=False, server_default=""),
        sa.Column("main_department", sa.String(200), nullable=False, server_default=""),
        sa.Column("attendance_group", sa.String(200), nullable=False, server_default=""),
        sa.Column("employee_no", sa.String(100), nullable=False, server_default=""),
        sa.Column("position", sa.String(200), nullable=False, server_default=""),
        sa.Column("external_user_id", sa.String(200), nullable=False, server_default=""),
        sa.Column("account_user_id", sa.Integer(), nullable=True),
        sa.Column("source_system", sa.String(64), nullable=False, server_default="erp"),
        sa.Column("source_key", sa.String(500), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["department_id"], ["erp_departments.id"], name="fk_erp_employee_department"
        ),
        sa.UniqueConstraint("tenant_id", "identity_key", name="uq_erp_employees_tenant_identity"),
    )
    op.create_index("ix_erp_employees_tenant_id", "erp_employees", ["tenant_id"])
    op.create_index("ix_erp_employees_department_id", "erp_employees", ["department_id"])
    op.create_index("ix_erp_employees_account_user_id", "erp_employees", ["account_user_id"])
    op.create_index("ix_erp_employees_tenant_name", "erp_employees", ["tenant_id", "employee_name"])
    op.create_index("ix_erp_employees_tenant_number", "erp_employees", ["tenant_id", "employee_no"])

    op.create_table(
        "erp_attendance_import_batches",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer(), nullable=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        sa.Column("source_file", sa.String(600), nullable=False),
        sa.Column("source_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("source_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("month_label", sa.String(20), nullable=False, server_default=""),
        sa.Column("workbook_kind", sa.String(32), nullable=False, server_default=""),
        sa.Column("rows_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_written", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("department_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("employee_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("receipt_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "tenant_id", "source_file", name="uq_erp_attendance_batch_tenant_source"
        ),
    )
    op.create_index(
        "ix_erp_attendance_import_batches_tenant_id",
        "erp_attendance_import_batches",
        ["tenant_id"],
    )
    op.create_index(
        "ix_erp_attendance_import_batches_owner_user_id",
        "erp_attendance_import_batches",
        ["owner_user_id"],
    )
    op.create_index(
        "ix_erp_attendance_batch_owner",
        "erp_attendance_import_batches",
        ["tenant_id", "owner_user_id", "imported_at"],
    )

    op.create_table(
        "erp_attendance_daily_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer(), nullable=True),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=True),
        sa.Column("department_id", sa.Integer(), nullable=True),
        sa.Column("source_file", sa.String(600), nullable=False),
        sa.Column("month_label", sa.String(20), nullable=False, server_default=""),
        sa.Column("source_row", sa.Integer(), nullable=False),
        sa.Column("employee_name", sa.String(200), nullable=False),
        sa.Column("attendance_group", sa.String(200), nullable=False, server_default=""),
        sa.Column("department", sa.String(200), nullable=False, server_default=""),
        sa.Column("employee_no", sa.String(100), nullable=False, server_default=""),
        sa.Column("position", sa.String(200), nullable=False, server_default=""),
        sa.Column("external_user_id", sa.String(200), nullable=False, server_default=""),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("shift_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("daily_times_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("raw_times_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("all_times_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("leave_hours", sa.Float(), nullable=False, server_default="0"),
        sa.Column("absent_days", sa.Float(), nullable=False, server_default="0"),
        sa.Column("late_count_hint", sa.Float(), nullable=False, server_default="0"),
        sa.Column("early_count_hint", sa.Float(), nullable=False, server_default="0"),
        sa.Column("missing_card_count", sa.Float(), nullable=False, server_default="0"),
        sa.Column("notes_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["erp_attendance_import_batches.id"],
            name="fk_erp_attendance_daily_batch",
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"], ["erp_employees.id"], name="fk_erp_attendance_daily_employee"
        ),
        sa.ForeignKeyConstraint(
            ["department_id"],
            ["erp_departments.id"],
            name="fk_erp_attendance_daily_department",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "source_file",
            "source_row",
            name="uq_erp_attendance_daily_tenant_source_row",
        ),
    )
    op.create_index(
        "ix_erp_attendance_daily_records_tenant_id",
        "erp_attendance_daily_records",
        ["tenant_id"],
    )
    op.create_index(
        "ix_erp_attendance_daily_records_employee_id",
        "erp_attendance_daily_records",
        ["employee_id"],
    )
    op.create_index(
        "ix_erp_attendance_daily_records_department_id",
        "erp_attendance_daily_records",
        ["department_id"],
    )
    op.create_index(
        "ix_erp_attendance_daily_employee_date",
        "erp_attendance_daily_records",
        ["tenant_id", "employee_name", "work_date"],
    )
    op.create_index(
        "ix_erp_attendance_daily_batch",
        "erp_attendance_daily_records",
        ["tenant_id", "batch_id"],
    )

    op.create_table(
        "erp_attendance_leave_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer(), nullable=True),
        sa.Column("receipt_id", sa.String(96), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("employee_name", sa.String(200), nullable=False),
        sa.Column("employee_no", sa.String(100), nullable=False, server_default=""),
        sa.Column("external_user_id", sa.String(200), nullable=False, server_default=""),
        sa.Column("leave_type", sa.String(64), nullable=False),
        sa.Column("leave_date", sa.Date(), nullable=False),
        sa.Column("period", sa.String(64), nullable=False),
        sa.Column("hours", sa.Float(), nullable=False),
        sa.Column("approval_status", sa.String(64), nullable=False, server_default="pending"),
        sa.Column("approval_evidence", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["employee_id"], ["erp_employees.id"], name="fk_erp_attendance_leave_employee"
        ),
        sa.UniqueConstraint(
            "tenant_id", "receipt_id", name="uq_erp_attendance_leave_tenant_receipt"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "employee_id",
            "leave_date",
            "period",
            "leave_type",
            name="uq_erp_attendance_leave_business_key",
        ),
    )
    op.create_index(
        "ix_erp_attendance_leave_records_tenant_id",
        "erp_attendance_leave_records",
        ["tenant_id"],
    )
    op.create_index(
        "ix_erp_attendance_leave_employee_date",
        "erp_attendance_leave_records",
        ["tenant_id", "employee_id", "leave_date"],
    )


def downgrade() -> None:
    op.drop_table("erp_attendance_leave_records")
    op.drop_table("erp_attendance_daily_records")
    op.drop_table("erp_attendance_import_batches")
    op.drop_table("erp_employees")
    op.drop_table("erp_departments")
