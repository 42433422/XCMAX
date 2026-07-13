from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import openpyxl
import pytest
from fastapi import Request

from app.application import chat_business_safety as safety
from app.application import planner_compat_service as planner_compat
from app.fastapi_routes import xcagi_compat_chat_helpers as chat_helpers


def _create_business_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE attendance_employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_file TEXT NOT NULL DEFAULT '',
            employee_name TEXT NOT NULL,
            department TEXT NOT NULL DEFAULT '',
            main_department TEXT NOT NULL DEFAULT '',
            attendance_group TEXT NOT NULL DEFAULT '',
            employee_no TEXT NOT NULL DEFAULT '',
            position TEXT NOT NULL DEFAULT '',
            user_id TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE attendance_daily_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_file TEXT NOT NULL,
            month_label TEXT NOT NULL,
            source_row INTEGER NOT NULL,
            employee_name TEXT NOT NULL,
            attendance_group TEXT NOT NULL,
            department TEXT NOT NULL,
            employee_no TEXT NOT NULL,
            position TEXT NOT NULL,
            user_id TEXT NOT NULL,
            work_date TEXT NOT NULL,
            shift_name TEXT NOT NULL,
            daily_times_json TEXT NOT NULL,
            raw_times_json TEXT NOT NULL,
            all_times_json TEXT NOT NULL,
            leave_hours REAL NOT NULL,
            absent_days REAL NOT NULL,
            late_count_hint REAL NOT NULL,
            early_count_hint REAL NOT NULL,
            missing_card_count REAL NOT NULL,
            notes_json TEXT NOT NULL,
            imported_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        """
        INSERT INTO attendance_employees (
            employee_name, department, employee_no, position, user_id
        ) VALUES ('李四', '研发部', '1001', '工程师', 'u-1001')
        """
    )
    rows = [
        (
            "李四",
            "1001",
            "研发部",
            "工程师",
            "u-1001",
            "2026-07-13",
            '["2026-07-13 08:03:00", "2026-07-13 17:35:00"]',
            0.0,
            0.0,
            1.0,
        ),
        (
            "王五",
            "1002",
            "研发部",
            "测试工程师",
            "u-1002",
            "2026-07-13",
            '["2026-07-13 07:58:00", "2026-07-13 17:31:00"]',
            0.0,
            0.0,
            0.0,
        ),
    ]
    for index, row in enumerate(rows, 1):
        conn.execute(
            """
            INSERT INTO attendance_daily_records (
                source_file, month_label, source_row, employee_name,
                attendance_group, department, employee_no, position, user_id,
                work_date, shift_name, daily_times_json, raw_times_json,
                all_times_json, leave_hours, absent_days, late_count_hint,
                early_count_hint, missing_card_count, notes_json, imported_at
            ) VALUES (?, '2026-07', ?, ?, '', ?, ?, ?, ?, ?, '正班', '[]', '[]', ?, ?, ?, ?, 0, 0, '[]', '2026-07-13T18:00:00')
            """,
            (
                "smoke.xlsx",
                index,
                row[0],
                row[2],
                row[1],
                row[3],
                row[4],
                row[5],
                row[6],
                row[7],
                row[8],
                row[9],
            ),
        )
    conn.commit()
    conn.close()


@pytest.fixture()
def business_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    db_path = tmp_path / "taiyangniao_pro.db"
    workspace = tmp_path / "workspace"
    _create_business_db(db_path)
    monkeypatch.setattr(safety, "_db_path", lambda: db_path)
    monkeypatch.setattr(safety, "resolve_safe_workspace_relpath", lambda rel: workspace / rel)
    return db_path, workspace


@pytest.mark.parametrize(
    ("message", "operation"),
    [
        ("我今天有没有迟到？", "attendance_read"),
        ("研发部今天谁出勤", "attendance_read"),
        ("1001号员工叫什么名字？", "personnel_read"),
        ("李四是哪个部门？", "personnel_read"),
        ("导出全部员工名单", "personnel_export"),
        ("下载人员列表", "personnel_export"),
        ("帮李四登记2026年7月14日上午事假半天，主管已经审批通过。", "leave_write"),
        ("李四明天休假半天", "leave_write"),
        ("李四明天不休假了", "leave_write"),
        ("直接把今天的考勤表打出来。", "attendance_print"),
        ("给我制作一份本月考勤数据", "attendance_export"),
        ("下载2026年7月的考勤明细", "attendance_export"),
    ],
)
def test_business_intent_covers_natural_wording(message: str, operation: str) -> None:
    intent = safety.classify_business_chat_intent(message)
    assert intent is not None
    assert intent.operation == operation


@pytest.mark.parametrize(
    "message",
    [
        "请解释一下考勤制度",
        "病假和事假有什么区别",
        "如何办理请假审批流程",
        "给我讲讲迟到规则怎么计算",
        "你好，今天心情不错",
    ],
)
def test_explanatory_or_general_chat_is_not_intercepted(message: str) -> None:
    assert safety.classify_business_chat_intent(message) is None


def test_natural_employee_lookup_uses_real_personnel_store(business_db: tuple[Path, Path]) -> None:
    result = safety.try_handle_business_chat_action("1001号员工叫什么名字？")
    assert result is not None
    assert "李四" in result["response"]
    assert result["execution_receipt"]["executed"] is True
    assert result["execution_receipt"]["verified"] is True
    assert result["execution_receipt"]["source"].endswith(":attendance_employees")


def test_personal_late_query_is_grounded_in_imported_record(
    business_db: tuple[Path, Path],
) -> None:
    result = safety.try_handle_business_chat_action("我2026年7月13日有没有迟到？", user_id="u-1001")
    assert result is not None
    assert "有迟到标记" in result["response"]
    assert "08:03:00" in result["response"]
    assert "只代表当前已导入的数据" in result["response"]
    assert result["execution_receipt"]["affected_rows"] == 1


def test_department_attendance_query_does_not_treat_department_as_person_name(
    business_db: tuple[Path, Path],
) -> None:
    result = safety.try_handle_business_chat_action("研发部2026年7月13日谁出勤")
    assert result is not None
    assert result["execution_receipt"]["affected_rows"] == 2
    assert result["execution_receipt"]["details"]["department"] == "研发部"
    assert "有打卡时间 2 条" in result["response"]


def test_unmapped_current_user_never_gets_invented_attendance(
    business_db: tuple[Path, Path],
) -> None:
    result = safety.try_handle_business_chat_action(
        "我2026年7月13日有没有迟到？", user_id="not-mapped"
    )
    assert result is not None
    assert "没有绑定人员档案" in result["response"]
    assert result["execution_receipt"]["executed"] is False
    assert result["execution_receipt"]["reason"] == "current_user_not_mapped"


def test_authenticated_server_identity_beats_web_conversation_user_id(
    business_db: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        safety,
        "_authenticated_user_from_request",
        lambda _request: SimpleNamespace(id=77, username="1001", display_name="李四"),
    )
    result = safety.try_handle_business_chat_action(
        "我2026年7月13日有没有迟到？",
        user_id="web_normal_fake-session-id",
        request=object(),
    )
    assert result is not None
    assert "李四有迟到标记" in result["response"]
    actor = result["execution_receipt"]["details"]["actor"]
    assert actor["authenticated"] is True
    assert actor["username"] == "1001"
    assert actor["trusted_client_user_id"] == ""


def test_leave_write_requires_complete_fields_and_never_calls_llm(
    business_db: tuple[Path, Path],
) -> None:
    result = safety.try_handle_business_chat_action("帮李四登记明天请假")
    assert result is not None
    assert "请假未登记" in result["response"]
    assert result["execution_receipt"]["executed"] is False
    assert set(result["execution_receipt"]["details"]["missing_fields"]) >= {
        "请假类型",
        "时段或时长",
    }


def test_approved_leave_is_written_with_idempotent_receipt(
    business_db: tuple[Path, Path],
) -> None:
    message = "帮李四登记2026年7月14日上午事假半天，主管已经审批通过。"
    first = safety.try_handle_business_chat_action(message, user_id="operator")
    second = safety.try_handle_business_chat_action(message, user_id="operator")
    assert first is not None and second is not None
    assert "登记成功" in first["response"]
    assert first["execution_receipt"]["status"] == "created"
    assert second["execution_receipt"]["status"] == "already_exists"
    first_business_receipt = first["execution_receipt"]["details"]["write_receipt_id"]
    second_business_receipt = second["execution_receipt"]["details"]["write_receipt_id"]
    assert first_business_receipt == second_business_receipt

    conn = sqlite3.connect(str(business_db[0]))
    row = conn.execute(
        "SELECT employee_name, leave_type, leave_date, period, approval_status "
        "FROM attendance_leave_records"
    ).fetchone()
    count = conn.execute("SELECT COUNT(*) FROM attendance_leave_records").fetchone()[0]
    conn.close()
    assert row == ("李四", "事假", "2026-07-14", "morning", "reported_approved")
    assert count == 1

    assert first["execution_receipt"]["details"]["approval_verified"] is False
    assert "未核验审批单/审批 ID" in first["response"]


def test_negative_approval_wording_stays_pending(business_db: tuple[Path, Path]) -> None:
    result = safety.try_handle_business_chat_action(
        "帮李四登记2026年7月15日下午事假半天，主管还没有审批通过。"
    )
    assert result is not None
    assert result["execution_receipt"]["details"]["approval_status"] == "pending"
    assert "状态为待审批" in result["response"]


def test_unknown_employee_leave_is_not_written(business_db: tuple[Path, Path]) -> None:
    result = safety.try_handle_business_chat_action(
        "帮赵六登记2026年7月14日上午事假半天，主管已审批通过"
    )
    assert result is not None
    assert "没有找到“赵六”" in result["response"]
    assert result["execution_receipt"]["executed"] is False


def test_leave_cancel_is_blocked_instead_of_creating_or_claiming_cancelled(
    business_db: tuple[Path, Path],
) -> None:
    result = safety.try_handle_business_chat_action("李四明天不休假了")
    assert result is not None
    assert "取消未执行" in result["response"]
    assert result["execution_receipt"]["executed"] is False
    assert result["execution_receipt"]["reason"] == "leave_cancel_tool_unavailable"

    conn = sqlite3.connect(str(business_db[0]))
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='attendance_leave_records'"
    ).fetchone()
    conn.close()
    assert exists is None


def test_export_creates_verified_downloadable_xlsx(business_db: tuple[Path, Path]) -> None:
    result = safety.try_handle_business_chat_action("导出2026年7月13日考勤表")
    assert result is not None
    receipt = result["execution_receipt"]
    assert receipt["status"] == "completed"
    assert receipt["verified"] is True
    assert receipt["affected_rows"] == 2
    artifact = receipt["artifacts"][0]
    exported = Path(artifact["path"])
    assert exported.is_file()
    assert artifact["download_url"].startswith(
        "/api/mod/taiyangniao-pro/attendance/download?relpath="
    )
    wb = openpyxl.load_workbook(exported, read_only=True, data_only=True)
    try:
        assert wb.active.max_row == 3
        assert wb.active["A1"].value == "日期"
        assert wb.active["B2"].value == "李四"
    finally:
        wb.close()


def test_personnel_export_creates_verified_downloadable_xlsx(
    business_db: tuple[Path, Path],
) -> None:
    result = safety.try_handle_business_chat_action("导出全部员工名单")
    assert result is not None
    receipt = result["execution_receipt"]
    assert receipt["operation"] == "personnel_export"
    assert receipt["status"] == "completed"
    assert receipt["verified"] is True
    assert receipt["affected_rows"] == 1
    artifact = receipt["artifacts"][0]
    exported = Path(artifact["path"])
    assert exported.is_file()
    assert artifact["download_url"].startswith(
        "/api/mod/taiyangniao-pro/attendance/download?relpath="
    )
    wb = openpyxl.load_workbook(exported, read_only=True, data_only=True)
    try:
        assert wb.active.title == "人员名单"
        assert wb.active.max_row == 2
        assert wb.active["A1"].value == "姓名"
        assert wb.active["A2"].value == "李四"
        assert wb.active["B2"].value == "1001"
    finally:
        wb.close()


class _NoPrinterService:
    def get_printers(self) -> dict[str, Any]:
        return {"success": True, "count": 0, "printers": []}


class _AcceptedPrinterService:
    printed: list[str]

    def __init__(self) -> None:
        self.printed = []

    def get_printers(self) -> dict[str, Any]:
        return {"success": True, "count": 1, "printers": [{"name": "QA Printer"}]}

    def print_document(self, path: str) -> dict[str, Any]:
        self.printed.append(path)
        return {"success": True, "printer": "QA Printer", "message": "accepted"}


def test_print_without_printer_is_not_reported_as_success(
    business_db: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(safety, "_get_printer_service", lambda: _NoPrinterService())
    result = safety.try_handle_business_chat_action("直接把2026年7月13日考勤表打出来")
    assert result is not None
    assert "打印未执行" in result["response"]
    assert result["execution_receipt"]["executed"] is False
    assert result["execution_receipt"]["reason"] == "no_available_printer"


def test_print_reports_submitted_only_after_backend_accepts_job(
    business_db: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    printer = _AcceptedPrinterService()
    monkeypatch.setattr(safety, "_get_printer_service", lambda: printer)
    result = safety.try_handle_business_chat_action("打印2026年7月13日的考勤表")
    assert result is not None
    assert result["execution_receipt"]["status"] == "submitted"
    assert result["execution_receipt"]["executed"] is True
    assert "已提交到 QA Printer" in result["response"]
    assert "实际出纸仍以设备状态为准" in result["response"]
    assert len(printer.printed) == 1
    assert Path(printer.printed[0]).is_file()


def test_stream_path_preempts_legacy_planner_and_returns_same_receipt(
    business_db: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_if_called(*_args: Any, **_kwargs: Any):
        raise AssertionError("legacy planner must not run for protected business actions")

    monkeypatch.setattr(chat_helpers, "_xcagi_guarded_planner_stream_events", fail_if_called)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/ai/chat/stream",
            "headers": [],
            "client": ("127.0.0.1", 12345),
        }
    )
    body = chat_helpers.XcagiCompatChatBody(message="我2026年7月13日有没有迟到？", user_id="u-1001")
    raw = b"".join(chat_helpers._xcagi_planner_stream_bytes(request, body, ai_tier="P0"))
    events = [
        json.loads(line.removeprefix("data: "))
        for line in raw.decode("utf-8").splitlines()
        if line.startswith("data: ")
    ]
    assert [event["type"] for event in events] == ["token", "done"]
    result = events[-1]["result"]
    assert result["business_receipt"]["verified"] is True
    assert "run_id" not in result


@pytest.mark.asyncio
async def test_json_path_preempts_both_mainline_and_legacy_chat(
    business_db: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(planner_compat, "assert_p2_elevated_claim_or_raise", lambda _request: None)
    monkeypatch.setattr(planner_compat, "resolve_ai_tier", lambda _request: "P0")
    monkeypatch.setattr(
        planner_compat,
        "run_agent_chat",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("legacy chat must not run")),
    )
    monkeypatch.setattr(
        planner_compat,
        "_execute_ai_chat_mainline",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("AI mainline must not run")),
    )
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/ai/chat",
            "headers": [],
            "client": ("127.0.0.1", 12345),
        }
    )
    body = chat_helpers.XcagiCompatChatBody(message="1001号员工叫什么名字？", user_id="u-1001")
    result = await planner_compat.execute_compat_chat(request, body)
    assert result["business_receipt"]["operation"] == "personnel_read"
    assert result["business_receipt"]["verified"] is True
    assert "李四" in result["response"]


@pytest.mark.asyncio
async def test_batch_path_applies_receipt_policy_to_every_protected_message(
    business_db: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(planner_compat, "assert_p2_elevated_claim_or_raise", lambda _request: None)
    monkeypatch.setattr(planner_compat, "resolve_ai_tier", lambda _request: "P0")
    monkeypatch.setattr(
        planner_compat,
        "run_agent_chat",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("legacy chat must not run")),
    )
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/ai/chat/batch",
            "headers": [],
            "client": ("127.0.0.1", 12345),
        }
    )
    body = chat_helpers.XcagiCompatChatBatchBody(
        messages=[
            "1001号员工叫什么名字？",
            "我2026年7月13日有没有迟到？",
        ],
        user_id="u-1001",
    )
    result = await planner_compat.execute_compat_chat_batch(request, body)
    assert result["success"] is True
    assert result["count"] == 2
    assert [row["business_receipt"]["operation"] for row in result["results"]] == [
        "personnel_read",
        "attendance_read",
    ]
    assert all(row["business_receipt"]["verified"] for row in result["results"])
