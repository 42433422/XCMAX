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
        == "PARTIAL PASS"
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
    assert report["checks"]["B31-38"] == "fail"
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
