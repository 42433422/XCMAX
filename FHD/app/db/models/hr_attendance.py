"""ERP-owned personnel and attendance models.

Attendance industry Mods may parse customer-specific source files, but the
resulting business data belongs to the tenant's ERP database.  These tables
are deliberately tenant scoped and do not depend on a Mod-private database.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import IntegerPrimaryKeyMixin, TenantScopedMixin, TimestampMixin


class ErpDepartment(IntegerPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    __tablename__ = "erp_departments"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "name", "parent_name", name="uq_erp_departments_tenant_identity"
        ),
        Index("ix_erp_departments_tenant_name", "tenant_id", "name"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    parent_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    attendance_group: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    source_system: Mapped[str] = mapped_column(String(64), nullable=False, default="erp")
    source_key: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ErpEmployee(IntegerPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    __tablename__ = "erp_employees"
    __table_args__ = (
        UniqueConstraint("tenant_id", "identity_key", name="uq_erp_employees_tenant_identity"),
        Index("ix_erp_employees_tenant_name", "tenant_id", "employee_name"),
        Index("ix_erp_employees_tenant_number", "tenant_id", "employee_no"),
    )

    identity_key: Mapped[str] = mapped_column(String(500), nullable=False)
    employee_name: Mapped[str] = mapped_column(String(200), nullable=False)
    department_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("erp_departments.id"), nullable=True, index=True
    )
    department: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    main_department: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    attendance_group: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    employee_no: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    position: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    external_user_id: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    account_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    source_system: Mapped[str] = mapped_column(String(64), nullable=False, default="erp")
    source_key: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AttendanceImportBatch(IntegerPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    __tablename__ = "erp_attendance_import_batches"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source_file", name="uq_erp_attendance_batch_tenant_source"),
        Index(
            "ix_erp_attendance_batch_owner",
            "tenant_id",
            "owner_user_id",
            "imported_at",
        ),
    )

    owner_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    source_file: Mapped[str] = mapped_column(String(600), nullable=False)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    month_label: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    workbook_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    rows_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    department_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    employee_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    receipt_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AttendanceDailyRecord(IntegerPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    __tablename__ = "erp_attendance_daily_records"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source_file",
            "source_row",
            name="uq_erp_attendance_daily_tenant_source_row",
        ),
        Index(
            "ix_erp_attendance_daily_employee_date",
            "tenant_id",
            "employee_name",
            "work_date",
        ),
        Index("ix_erp_attendance_daily_batch", "tenant_id", "batch_id"),
    )

    batch_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("erp_attendance_import_batches.id"), nullable=False
    )
    employee_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("erp_employees.id"), nullable=True, index=True
    )
    department_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("erp_departments.id"), nullable=True, index=True
    )
    source_file: Mapped[str] = mapped_column(String(600), nullable=False)
    month_label: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    source_row: Mapped[int] = mapped_column(Integer, nullable=False)
    employee_name: Mapped[str] = mapped_column(String(200), nullable=False)
    attendance_group: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    department: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    employee_no: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    position: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    external_user_id: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    work_date: Mapped[date] = mapped_column(Date, nullable=False)
    shift_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    daily_times_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    raw_times_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    all_times_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    leave_hours: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    absent_days: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    late_count_hint: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    early_count_hint: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    missing_card_count: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    notes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AttendanceLeaveRecord(IntegerPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    __tablename__ = "erp_attendance_leave_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "receipt_id", name="uq_erp_attendance_leave_tenant_receipt"),
        UniqueConstraint(
            "tenant_id",
            "employee_id",
            "leave_date",
            "period",
            "leave_type",
            name="uq_erp_attendance_leave_business_key",
        ),
        Index(
            "ix_erp_attendance_leave_employee_date",
            "tenant_id",
            "employee_id",
            "leave_date",
        ),
    )

    receipt_id: Mapped[str] = mapped_column(String(96), nullable=False)
    employee_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("erp_employees.id"), nullable=False
    )
    employee_name: Mapped[str] = mapped_column(String(200), nullable=False)
    employee_no: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    external_user_id: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    leave_type: Mapped[str] = mapped_column(String(64), nullable=False)
    leave_date: Mapped[date] = mapped_column(Date, nullable=False)
    period: Mapped[str] = mapped_column(String(64), nullable=False)
    hours: Mapped[float] = mapped_column(Float, nullable=False)
    approval_status: Mapped[str] = mapped_column(String(64), nullable=False, default="pending")
    approval_evidence: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_message: Mapped[str] = mapped_column(Text, nullable=False, default="")


__all__ = [
    "AttendanceDailyRecord",
    "AttendanceImportBatch",
    "AttendanceLeaveRecord",
    "ErpDepartment",
    "ErpEmployee",
]
