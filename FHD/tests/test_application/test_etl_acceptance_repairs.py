"""Proofs for the ETL acceptance failures B01–B31."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import date
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook, load_workbook

from app.application.elt.attendance_pipeline import _hours, parse_attendance_dataset
from app.application.elt.target_detection import detect_etl_target
from app.application.reviewed_excel_basic_classification import classify_review_workbook
from app.application.reviewed_excel_template import inspect_workbook

CUSTOMER = Path("/opt/cursor/artifacts/etl-b01-b31/customer-sources")
SYNTHETIC = Path("/opt/cursor/artifacts/etl-b01-b31/synthetic")


def test_real_customer_workbooks_classify_without_size_or_fidelity_rejection():
    dingtalk = (CUSTOMER / "dingtalk-export.xlsx").read_bytes()
    template = (CUSTOMER / "kaoqin-2026-03-template.xlsx").read_bytes()
    ding = inspect_workbook(dingtalk)
    sunbird = inspect_workbook(template)
    assert ding["sha256"] == hashlib.sha256(dingtalk).hexdigest()
    assert sunbird["sha256"] == hashlib.sha256(template).hexdigest()
    assert "每日统计" in ding["sheets"] and "原始记录" in ding["sheets"]
    assert sunbird["fidelity_skipped"]
    assert any(item["sheet"] == "明细" for item in sunbird["sheet_overview"])
    classified = classify_review_workbook(ding)
    assert {item["sheet"] for item in classified} == set(ding["sheets"])
    parsed = parse_attendance_dataset(CUSTOMER / "dingtalk-export.xlsx", max_rows=20000)
    daily = [row for row in parsed.rows if row.sheet == "每日统计"]
    invalid = [row for row in daily if row.provenance["clean"]["validation_result"]]
    assert len(daily) >= 4500
    assert len(daily) == len(invalid) + len(daily) - len(invalid)
    assert all("business_id" not in row.provenance["slice"] for row in daily)
    assert all(row.provenance["clean"]["business_id"] for row in daily if not row.provenance["clean"]["validation_result"])
    parsed.close()


def test_unknown_and_similar_templates_are_not_forced(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    unknown = tmp_path / "unknown-template.xlsx"
    similar = tmp_path / "similar-headers-multitable.xlsx"
    unknown.write_bytes((SYNTHETIC / "unknown-template.xlsx").read_bytes())
    similar.write_bytes((SYNTHETIC / "similar-headers-multitable.xlsx").read_bytes())
    assert detect_etl_target(unknown)["target_type"] == "abnormal"
    assert detect_etl_target(similar)["target_type"] == "abnormal"
    review = classify_review_workbook(inspect_workbook(similar.read_bytes()))[0]
    ranges = [region["range"] for region in review["regions"]]
    assert "A1:H10" not in ranges
    assert sum(region.get("data_region", True) for region in review["regions"]) >= 2
    title = classify_review_workbook(inspect_workbook((SYNTHETIC / "title-only.xlsx").read_bytes()))[0]
    assert title["processable"] is False and title["regions"][0]["data_region"] is False
    from app.application.reviewed_excel_auto_slice import derive_rule_slices

    slices = derive_rule_slices(
        similar.read_bytes(), {"sheets": classify_review_workbook(inspect_workbook(similar.read_bytes()))}
    )
    assert slices and all("business_id" not in item for item in slices)
    formula = next(cell for cell in inspect_workbook(similar.read_bytes())["cells"] if cell["cell"] == "F5")
    assert formula["kind"] == "formula" and formula["value"].startswith("=")
    assert all(item["basis"] == "rule_region" for item in slices)
    hidden = classify_review_workbook(inspect_workbook((SYNTHETIC / "hidden-blank.xlsx").read_bytes()))
    blank = next(item for item in hidden if item["sheet"] == "空白")
    concealed = next(item for item in hidden if item["sheet"] == "隐藏")
    assert blank["blank"] is True and blank["processable"] is False
    assert concealed["processable"] is False


def test_slice_has_no_business_id_and_clean_is_stable_and_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr("app.utils.path_io.path_utils.get_app_data_dir", lambda: str(tmp_path))
    book = Workbook()
    sheet = book.active
    sheet.title = "每日统计"
    sheet.append(["姓名", "工号", "部门", "日期", "上班1打卡时间", "下班1打卡时间"])
    sheet.append(["测试甲", "E001", "计划", "2026-03-02", "2026-03-02 08:00", "2026-03-02 17:30"])
    sheet.append(["测试甲", "E001", "计划", "2026-03-02", "2026-03-02 08:00", "2026-03-02 17:30"])
    sheet.append(["测试甲", "E009", "计划", "2026-03-04", "2026-03-04 08:00", "2026-03-04 12:00"])
    sheet.append(["", "E003", "计划", "2026-03-02", "not-a-time", ""])
    sheet.append(["测试甲", "E001", "计划", "2026-03-03", "2026-03-03 09:00", "2026-03-03 12:00"])
    path = tmp_path / "boundary.xlsx"
    book.save(path)
    book.close()
    original = hashlib.sha256(path.read_bytes()).hexdigest()
    dataset = parse_attendance_dataset(path, max_rows=100)
    dataset2 = parse_attendance_dataset(path, max_rows=100)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original
    assert all("business_id" not in row.provenance["slice"] for row in dataset.rows)
    ids = [row.provenance["clean"]["business_id"] for row in dataset.rows if row.values["employee_name"]]
    assert ids == [row.provenance["clean"]["business_id"] for row in dataset2.rows if row.values["employee_name"]]
    assert len(ids) == len(set(ids)) + 1
    errors = [row for row in dataset.rows if row.provenance["clean"]["validation_result"]]
    assert errors and errors[0].provenance["clean"]["validation_result"][0]["field"] == "employee_name"
    from app.application.elt.attendance_pipeline import persist_attendance_rows

    db = tmp_path / "attendance.sqlite"
    payload = []
    for row in dataset.rows:
        if row.provenance["clean"]["duplicate_status"] != "unique":
            continue
        if row.provenance["clean"]["validation_result"]:
            continue
        payload.append(
            {
                **row.provenance["clean"]["cleaning_result"],
                "business_id": row.provenance["clean"]["business_id"],
                "source_row": row.row_number,
                "source_sheet": row.sheet,
                "slice_id": row.provenance["slice"]["slice_id"],
            }
        )
    first = persist_attendance_rows(
        payload, db_path=db, source_file="same", upload_path=path, run_id="run-1"
    )
    second = persist_attendance_rows(
        payload, db_path=db, source_file="same", upload_path=path, run_id="run-2"
    )
    assert first["executed"] == 3 and second["executed"] == 0
    assert first["product_rows"] == 0 and first["customer_rows"] == 0
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM attendance_daily_records").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0
        people = conn.execute(
            "SELECT employee_no FROM attendance_employees ORDER BY employee_no"
        ).fetchall()
    assert people == [("E001",), ("E009",)]
    output = Path(first["output_path"])
    assert hashlib.sha256(output.read_bytes()).hexdigest() == first["sha256"]
    reopened = load_workbook(output, read_only=True)
    try:
        header = [cell.value for cell in next(reopened.active.iter_rows(max_row=1))]
    finally:
        reopened.close()
    assert header[:6] == ["员工姓名", "员工编号", "日期", "上班打卡", "下班打卡", "正班小时"]


def test_weekday_windows_match_the_documented_oracle():
    monday = _hours("2026-03-02", "08:00", "17:30")
    assert monday == {"regular_hours": 8.0, "sunday_overtime_hours": 0.0, "night_overtime_hours": 0.0}
    evening = _hours("2026-03-02", "08:00", "18:40")
    assert evening["regular_hours"] == 8.0
    assert evening["night_overtime_hours"] == 0.5
    sunday = _hours("2026-03-01", "09:00", "12:00")
    assert sunday["regular_hours"] == 0.0 and sunday["sunday_overtime_hours"] == 3.0
    assert date(2026, 3, 1).weekday() == 6


def test_enterprise_desktop_demo_can_convert(monkeypatch):
    from app.mod_sdk import customer_features

    monkeypatch.setattr(customer_features, "get_logged_in_user", lambda _: type("U", (), {"username": "xcagi-enterprise-demo"})())
    monkeypatch.setattr(customer_features, "load_session_private_delivery_binding", lambda _: {})
    monkeypatch.setattr(
        "app.mod_sdk.product_plane.is_enterprise_client_plane", lambda: True
    )
    from starlette.requests import Request

    features = customer_features.attendance_custom_features(Request({"type": "http", "headers": []}))
    assert "attendance-convert" in features["custom_features"]
    monkeypatch.setattr("app.mod_sdk.product_plane.is_enterprise_client_plane", lambda: False)
    denied = customer_features.attendance_custom_features(Request({"type": "http", "headers": []}))
    assert denied["custom_features"] == []


def test_fault_retry_does_not_duplicate_written_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("FHD_ETL_ATTENDANCE_FAULT", "after_first_commit")
    monkeypatch.setattr("app.utils.path_io.path_utils.get_app_data_dir", lambda: str(tmp_path))
    from app.application.elt.attendance_pipeline import persist_attendance_rows
    from app.application.elt.errors import EltError

    rows = [
        {"employee_name": "甲", "employee_no": "E1", "work_date": "2026-03-02", "business_id": "a" * 32, "source_row": 2},
        {"employee_name": "乙", "employee_no": "E2", "work_date": "2026-03-03", "business_id": "b" * 32, "source_row": 3},
    ]
    db = tmp_path / "fault.sqlite"
    path = tmp_path / "source.xlsx"
    path.write_bytes(b"source")
    try:
        persist_attendance_rows(rows, db_path=db, source_file="fault", upload_path=path, run_id="fault")
        raise AssertionError("fault must fail the ingest")
    except EltError as exc:
        assert exc.code == "ELT_ATTENDANCE_FAULT"
    monkeypatch.delenv("FHD_ETL_ATTENDANCE_FAULT")
    again = persist_attendance_rows(
        rows, db_path=db, source_file="fault", upload_path=path, run_id="retry"
    )
    assert again["executed"] == 1
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM attendance_daily_records").fetchone()[0] == 2


def test_corrupt_and_empty_workbooks_still_fail():
    try:
        inspect_workbook(b"")
        raise AssertionError("empty workbook must fail")
    except Exception as exc:
        assert "为空" in str(exc) or "无法读取" in str(exc)
    try:
        inspect_workbook(b"this is not a workbook")
        raise AssertionError("corrupt workbook must fail")
    except Exception as exc:
        assert "无法读取" in str(exc) or "为空" in str(exc)
    buffer = BytesIO()
    Workbook().save(buffer)
    assert inspect_workbook(buffer.getvalue())["sha256"]
