from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.application import erp_attendance_app_service as service
from app.db.base import Base
from app.db.models.hr_attendance import (
    AttendanceDailyRecord,
    AttendanceImportBatch,
    ErpDepartment,
    ErpEmployee,
)
from app.db.models.product import Product
from app.infrastructure.tenant_scope import tenant_scope


@pytest.fixture()
def db_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _workbook(path: Path) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "每日统计"
    ws.append(["标题"] * 7)
    ws.append(["标题"] * 7)
    ws.append(["标题"] * 7)
    ws.append(["张三", "公司正班", "生产部", "总部", "001", "操作员", "u001"])
    wb.save(path)
    wb.close()
    return path


def _daily_record():
    return SimpleNamespace(
        source_row=4,
        employee_name="张三",
        attendance_group="公司正班",
        department="生产部",
        employee_no="001",
        position="操作员",
        user_id="u001",
        work_date=date(2026, 8, 24),
        shift_name="白班",
        daily_times=[datetime(2026, 8, 24, 8, 0)],
        raw_times=[datetime(2026, 8, 24, 8, 0)],
        all_punch_times=lambda: [
            datetime(2026, 8, 24, 8, 0),
            datetime(2026, 8, 24, 17, 30),
        ],
        leave_hours=0,
        absent_days=0,
        late_count_hint=0,
        early_count_hint=0,
        missing_card_count=0,
        notes=[],
    )


def test_import_writes_canonical_erp_tables_and_rollback(db_factory, tmp_path, monkeypatch):
    source = _workbook(tmp_path / "attendance-2026-08.xlsx")
    monkeypatch.setattr(
        service, "_daily_records", lambda *_args, **_kwargs: (1, [_daily_record()], "2026-08")
    )

    with tenant_scope(1):
        db = db_factory()
        receipt = service.import_attendance_workbook_to_erp(
            source,
            db,
            owner_user_id=7,
            source_file_key="hash:attendance-2026-08.xlsx",
            source_hash="hash",
        )
        db.commit()

        assert receipt["storage"] == "erp"
        assert receipt["sync_ui_tables"] is False
        assert db.query(ErpDepartment).count() == 1
        assert db.query(ErpEmployee).count() == 1
        assert db.query(AttendanceImportBatch).count() == 1
        assert db.query(AttendanceDailyRecord).count() == 1
        assert db.query(Product).count() == 0
        row = db.query(AttendanceDailyRecord).one()
        assert row.employee_name == "张三"
        assert row.work_date == date(2026, 8, 24)

        from app.fastapi_routes.erp_hr_attendance import (
            list_attendance_imports,
            list_attendance_records,
            list_departments,
            list_employees,
        )

        employee_page = list_employees(page=1, page_size=50, search="张三", db=db)
        department_page = list_departments(page=1, page_size=50, search="生产", db=db)
        attendance_page = list_attendance_records(
            page=1,
            page_size=50,
            date_start="2026-08-24",
            date_end="2026-08-24",
            employee_name="张三",
            employee_no="",
            department="",
            db=db,
        )
        import_page = list_attendance_imports(page=1, page_size=50, db=db)
        assert employee_page["data"]["items"][0]["employee_name"] == "张三"
        assert department_page["data"]["items"][0]["department"] == "生产部"
        assert attendance_page["data"]["items"][0]["work_date"] == "2026-08-24"
        assert isinstance(import_page["data"]["items"][0]["imported_at"], str)

        with pytest.raises(ValueError, match="attendance_source_already_imported"):
            service.import_attendance_workbook_to_erp(
                source,
                db,
                owner_user_id=7,
                source_file_key="hash:attendance-2026-08.xlsx",
            )

        deleted = service.rollback_attendance_import(
            db,
            source_file="hash:attendance-2026-08.xlsx",
            batch_id=receipt["batch_id"],
        )
        db.commit()
        assert deleted == 3
        assert db.query(AttendanceDailyRecord).count() == 0
        assert db.query(AttendanceImportBatch).count() == 0
        assert db.query(ErpEmployee).count() == 0
        assert db.query(ErpDepartment).count() == 0


def test_second_source_reuses_master_data_and_rollback_keeps_it(db_factory, tmp_path, monkeypatch):
    first = _workbook(tmp_path / "first.xlsx")
    second = _workbook(tmp_path / "second.xlsx")
    monkeypatch.setattr(
        service, "_daily_records", lambda *_args, **_kwargs: (1, [_daily_record()], "2026-08")
    )

    with tenant_scope(2):
        db = db_factory()
        service.import_attendance_workbook_to_erp(
            first, db, owner_user_id=9, source_file_key="h1:first.xlsx"
        )
        db.commit()
        second_receipt = service.import_attendance_workbook_to_erp(
            second, db, owner_user_id=9, source_file_key="h2:second.xlsx"
        )
        db.commit()
        assert db.query(ErpEmployee).count() == 1
        assert db.query(ErpDepartment).count() == 1
        assert db.query(AttendanceDailyRecord).count() == 2

        service.rollback_attendance_import(
            db, source_file="h2:second.xlsx", batch_id=second_receipt["batch_id"]
        )
        db.commit()
        assert db.query(ErpEmployee).count() == 1
        assert db.query(ErpDepartment).count() == 1
        assert db.query(AttendanceDailyRecord).count() == 1


def test_employee_identity_is_stable_and_tenant_scoped(db_factory):
    assert (
        service.employee_identity_key(
            employee_name="张三", department="生产部", employee_no="001", external_user_id="u001"
        )
        == "user:u001"
    )
    with tenant_scope(3):
        db = db_factory()
        db.add(
            ErpEmployee(
                tenant_id=3,
                identity_key="user:u001",
                employee_name="张三",
                department="生产部",
                main_department="总部",
                attendance_group="公司正班",
                employee_no="001",
                position="操作员",
                external_user_id="u001",
                source_system="test",
                source_key="test",
            )
        )
        db.commit()
        assert service.find_employee(db, employee_no="001").employee_name == "张三"
        assert service.find_employee(db, identifiers=["u001"]).employee_no == "001"


def test_legacy_side_database_migrates_once_into_current_tenant(db_factory, tmp_path):
    from app.application.attendance_import_app_service import _ensure_schema

    legacy = tmp_path / "taiyangniao_pro.db"
    conn = sqlite3.connect(legacy)
    _ensure_schema(conn)
    conn.execute(
        """
        INSERT INTO attendance_departments
            (source_file, department, main_department, attendance_group)
        VALUES ('old.xlsx', '生产部', '总部', '公司正班')
        """
    )
    conn.execute(
        """
        INSERT INTO attendance_employees
            (source_file, employee_name, department, main_department,
             attendance_group, employee_no, position, user_id)
        VALUES ('old.xlsx', '张三', '生产部', '总部', '公司正班', '001', '操作员', 'u001')
        """
    )
    conn.commit()
    conn.close()

    preview = service.legacy_attendance_preview(legacy)
    assert preview["counts"]["employees"] == 1
    with tenant_scope(8):
        db = db_factory()
        migrated = service.migrate_legacy_attendance_to_erp(
            db, legacy_db_path=legacy, owner_user_id=3
        )
        db.commit()
        assert migrated["status"] == "migrated"
        assert db.query(ErpEmployee).one().tenant_id == 8
        assert db.query(ErpDepartment).one().tenant_id == 8
        again = service.migrate_legacy_attendance_to_erp(db, legacy_db_path=legacy, owner_user_id=3)
        assert again["status"] == "already_migrated"
