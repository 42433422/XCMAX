"""B31 发布门槛：客户原件闭环，不把单项或合成 Excel 当成通过。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from openpyxl import Workbook

from app.application.elt.customer_excel_gate import (
    CHECK_IDS,
    decide_status,
    evaluate_workbook,
    release_status,
)


def test_release_status_without_customer_original_is_blocked(monkeypatch):
    monkeypatch.delenv("XCAGI_ETL_CUSTOMER_EXCEL", raising=False)
    monkeypatch.delenv("XCAGI_ETL_MANUAL_BASELINE", raising=False)
    report = release_status()
    assert report["status"] == "BLOCKED"
    assert report["release_pass"] is False
    assert report["checks"].keys() == set(CHECK_IDS)
    assert "合成" in report["reason"]


def test_substitute_evidence_cannot_pass_even_when_every_check_passes():
    checks = dict.fromkeys(CHECK_IDS, "pass")
    for evidence in ("synthetic", "unit_test", "ci", "historical_attendance", "fixture"):
        assert (
            decide_status(
                evidence_class=evidence,
                customer_original=False,
                checks=checks,
                hard_fail=False,
            )
            == "BLOCKED"
        )


def test_customer_chain_fails_closed_on_data_loss_and_passes_only_when_complete():
    checks = dict.fromkeys(CHECK_IDS, "pass")
    assert (
        decide_status(
            evidence_class="customer_original",
            customer_original=True,
            checks=checks,
            hard_fail=True,
        )
        == "FAIL"
    )
    assert (
        decide_status(
            evidence_class="customer_original",
            customer_original=True,
            checks=checks,
            hard_fail=False,
        )
        == "PASS"
    )
    checks["B31-38"] = "fail"
    assert (
        decide_status(
            evidence_class="customer_original",
            customer_original=True,
            checks=checks,
            hard_fail=False,
        )
        == "FAIL"
    )


def test_missing_checks_cannot_be_reported_as_a_complete_release():
    assert (
        decide_status(
            evidence_class="customer_original",
            customer_original=True,
            checks={CHECK_IDS[0]: "pass"},
            hard_fail=False,
        )
        == "PARTIAL PASS"
    )


def test_corrupt_customer_workbook_returns_failure_without_writes(tmp_path):
    path = tmp_path / "客户原件.xlsx"
    path.write_bytes(b"not a workbook")
    report = evaluate_workbook(
        path,
        {"version": "test-version", "task_id": "corrupt", "confirmed": True},
        data_dir=tmp_path / "gate",
    )
    assert report["status"] == "FAIL"
    assert report["checks"]["B31-04"] == "fail"
    assert report["checks"]["B31-35"] == "not_tested"
    assert not list(tmp_path.glob("**/*.sqlite"))


def test_synthetic_workbook_is_not_a_release_pass(tmp_path, monkeypatch):
    monkeypatch.setattr("app.utils.path_io.path_utils.get_app_data_dir", lambda: str(tmp_path))
    monkeypatch.setenv("FHD_ETL_ATTENDANCE_FAULT", "after_first_commit")
    path = tmp_path / "synthetic-attendance.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.title = "每日统计"
    sheet.append(["姓名", "工号", "部门", "日期", "上班1打卡时间", "下班1打卡时间"])
    sheet.append(["测试甲", "E001", "计划", "2026-03-02", "2026-03-02 08:00", "2026-03-02 17:30"])
    sheet.append(["", "E003", "计划", "2026-03-02", "not-a-time", ""])
    hidden = book.create_sheet("隐藏")
    hidden.append(["姓名", "上班时间", "下班时间"])
    hidden.sheet_state = "hidden"
    book.save(path)
    book.close()
    baseline = {
        "evidence_class": "synthetic",
        "version": "1.0.0.7",
        "task_id": "synthetic-task",
        "confirmed": True,
        "daily_rows": 1,
        "regular_hours": 8.0,
        "manual_reconciled": True,
        "opened_with": ["Excel", "WPS"],
    }
    report = evaluate_workbook(
        path, baseline, data_dir=tmp_path / "gate", evidence_class="synthetic"
    )
    assert report["status"] == "BLOCKED"
    assert report["release_pass"] is False
    assert report["checks"]["B31-03"] == "pass"
    assert report["checks"]["B31-05"] == "pass"
    assert report["checks"]["B31-30"] == "pass"
    assert report["checks"]["B31-34"] == "pass"
    assert report["checks"]["B31-50"] == "pass"
    assert report["checks"]["B31-38"] == "not_tested"
    assert report["checks"]["B31-52"] == "not_tested"
    assert report["checks"]["B31-45"] == "not_tested"
    assert report["checks"]["B31-54"] == "pass"
    import os

    assert os.environ["FHD_ETL_ATTENDANCE_FAULT"] == "after_first_commit"


def test_missing_manual_oracle_does_not_verify_totals_and_db_fields_are_compared(
    tmp_path, monkeypatch
):
    from app.application.elt import customer_excel_gate as gate

    monkeypatch.setattr("app.utils.path_io.path_utils.get_app_data_dir", lambda: str(tmp_path))
    persist = gate.persist_attendance_rows

    def corrupt_written_field(rows, **kwargs):
        result = persist(rows, **kwargs)
        if kwargs["db_path"].name == "b31.sqlite" and result["executed"]:
            with sqlite3.connect(kwargs["db_path"]) as conn:
                conn.execute("UPDATE attendance_daily_records SET employee_name = '错配'")
        return result

    monkeypatch.setattr(gate, "persist_attendance_rows", corrupt_written_field)
    path = tmp_path / "客户原件.xlsx"
    book = Workbook()
    book.active.append(["姓名", "工号", "日期", "上班1打卡时间", "下班1打卡时间"])
    book.active.append(["甲", "E1", "2026-03-02", "2026-03-02 08:00", "2026-03-02 17:30"])
    book.save(path)
    book.close()
    report = evaluate_workbook(
        path,
        {"version": "test-version", "task_id": "missing-oracle", "confirmed": True},
        data_dir=tmp_path / "gate",
    )
    assert report["status"] == "FAIL"
    assert report["checks"]["B31-36"] == "fail"
    assert report["checks"]["B31-54"] == "fail"
    assert report["checks"]["B31-42"] == "not_tested"
    assert report["checks"]["B31-47"] == "not_tested"
    assert report["checks"]["B31-48"] == "fail"


def test_fixture_path_cannot_release_even_with_customer_label(tmp_path, monkeypatch):
    monkeypatch.delenv("XCAGI_ETL_CUSTOMER_EXCEL", raising=False)
    monkeypatch.delenv("XCAGI_ETL_MANUAL_BASELINE", raising=False)
    sample = tmp_path / "tests" / "sample-customer.xlsx"
    sample.parent.mkdir()
    sample.write_bytes(b"not-a-workbook")
    oracle = tmp_path / "baseline.json"
    oracle.write_text(json.dumps({"evidence_class": "customer_original"}), encoding="utf-8")
    env = {
        "XCAGI_ETL_CUSTOMER_EXCEL": str(sample),
        "XCAGI_ETL_MANUAL_BASELINE": str(oracle),
    }
    report = release_status(env)
    assert report["status"] == "BLOCKED"
    assert report["release_pass"] is False
    assert "样例" in report["reason"]


def test_unconfirmed_customer_file_does_not_count_as_pass(tmp_path):
    path = tmp_path / "客户考勤原件.xlsx"
    book = Workbook()
    book.active.append(["姓名", "工号", "日期", "上班1打卡时间", "下班1打卡时间"])
    book.active.append(["甲", "E1", "2026-03-02", "2026-03-02 08:00", "2026-03-02 17:30"])
    book.save(path)
    book.close()
    report = evaluate_workbook(
        path,
        {
            "version": "1.0.0.7",
            "task_id": "task-1",
            "confirmed": False,
            "evidence_class": "customer_original",
        },
        data_dir=tmp_path / "gate",
        evidence_class="customer_original",
    )
    assert report["release_pass"] is False
    assert report["status"] == "PARTIAL PASS"
    assert report["checks"]["B31-34"] == "pass"
    assert report["checks"]["B31-35"] == "not_tested"
    assert any("未经确认" in note for note in report["notes"])
    assert not list(tmp_path.glob("**/*.sqlite"))


def _matrix_book(path, *, marks=("√", "✘"), extra_rows=()):
    import calendar

    book = Workbook()
    sheet = book.active
    sheet.title = "考勤"
    for year, month in ((2026, 2), (2026, 3)):
        days = calendar.monthrange(year, month)[1]
        sheet.append([f"{year}年{month}月考勤表"])
        sheet.append(
            [
                "",
                *(
                    "一二三四五六日"[calendar.weekday(year, month, day)]
                    for day in range(1, days + 1)
                ),
            ]
        )
        sheet.append(["姓名", *range(1, days + 1)])
        sheet.append(["张三", marks[0], marks[1]])
        sheet.append(["李四"])
        sheet.append(["备注：月底结算"])
    for row in extra_rows:
        sheet.append(row)
    book.save(path)
    book.close()


def test_monthly_matrix_reaches_every_row_and_reconciles_monthly_records(tmp_path, monkeypatch):
    monkeypatch.setattr("app.utils.path_io.path_utils.get_app_data_dir", lambda: str(tmp_path))
    path = tmp_path / "客户考勤原件.xlsx"
    _matrix_book(path)
    report = evaluate_workbook(
        path,
        {
            "version": "v",
            "task_id": "matrix",
            "confirmed": True,
            "business_records": 4,
            "absent_days": 2,
            "present_marked_days": 2,
            "exception_rows": 0,
        },
        data_dir=tmp_path / "gate",
    )
    assert report["checks"]["B31-16"] == "pass"
    assert report["checks"]["B31-35"] == "pass"
    assert report["checks"]["B31-36"] == "pass"
    assert report["checks"]["B31-42"] == "pass"
    assert not any("没有去向" in note for note in report["notes"])
    with sqlite3.connect(tmp_path / "gate" / "b31.sqlite") as conn:
        stored = conn.execute(
            "SELECT employee_name, work_month, absent_dates FROM attendance_monthly_marks "
            "ORDER BY work_month, employee_name"
        ).fetchall()
    assert stored == [
        ("张三", "2026-02", "2026-02-02"),
        ("李四", "2026-02", ""),
        ("张三", "2026-03", "2026-03-02"),
        ("李四", "2026-03", ""),
    ]


def test_monthly_matrix_wrong_manual_total_fails(tmp_path, monkeypatch):
    monkeypatch.setattr("app.utils.path_io.path_utils.get_app_data_dir", lambda: str(tmp_path))
    path = tmp_path / "客户考勤原件.xlsx"
    _matrix_book(path)
    report = evaluate_workbook(
        path,
        {
            "version": "v",
            "task_id": "m",
            "confirmed": True,
            "business_records": 4,
            "absent_days": 3,
        },
        data_dir=tmp_path / "gate",
    )
    assert report["status"] == "FAIL"
    assert report["checks"]["B31-42"] == "fail"


def test_unknown_mark_is_an_exception_not_a_silent_value(tmp_path):
    from app.application.elt.attendance_pipeline import parse_attendance_dataset

    path = tmp_path / "考勤.xlsx"
    _matrix_book(path, marks=("√", "Ⅹ"))
    dataset = parse_attendance_dataset(path, max_rows=100)
    issues = [row.provenance["clean"]["validation_result"] for row in dataset.rows]
    assert len(dataset.rows) == 4
    assert sum(1 for item in issues if item) == 2
    assert all(issue["code"] == "ELT_ATTENDANCE_MARK_UNKNOWN" for item in issues for issue in item)
    assert all(not row.values["business_id"] for row, item in zip(dataset.rows, issues) if item)


def test_content_without_recognised_region_blocks_confirmation(tmp_path):
    from app.application.elt.attendance_pipeline import parse_attendance_dataset
    from app.application.elt.errors import EltError

    path = tmp_path / "考勤.xlsx"
    book = Workbook()
    book.active.append(["随便写的", "不是考勤"])
    book.save(path)
    book.close()
    try:
        parse_attendance_dataset(path, max_rows=100)
    except EltError as exc:
        assert exc.code == "ELT_ATTENDANCE_REGION_UNPARSED"
    else:
        raise AssertionError("unparsed content must not produce an empty confirmable preview")
    report = evaluate_workbook(
        path, {"version": "v", "task_id": "z", "confirmed": True}, data_dir=tmp_path / "gate"
    )
    assert report["status"] == "FAIL"
    assert report["checks"]["B31-04"] == "fail"


def test_rows_without_destination_fail_the_gate(tmp_path, monkeypatch):
    from app.application.elt import customer_excel_gate as gate

    monkeypatch.setattr("app.utils.path_io.path_utils.get_app_data_dir", lambda: str(tmp_path))
    path = tmp_path / "客户考勤原件.xlsx"
    _matrix_book(path)
    real = gate._row_destinations

    def drop_notes(sheets, rows):
        roles = real(sheets, rows)
        for target in roles.values():
            for line in [key for key, role in target.items() if role == "note"]:
                del target[line]
        return roles

    monkeypatch.setattr(gate, "_row_destinations", drop_notes)
    report = evaluate_workbook(
        path, {"version": "v", "task_id": "o", "confirmed": True}, data_dir=tmp_path / "gate"
    )
    assert report["status"] == "FAIL"
    assert report["checks"]["B31-16"] == "fail"
    assert any("没有去向" in note for note in report["notes"])
