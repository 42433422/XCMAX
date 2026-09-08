# mypy: disable-error-code="index, union-attr"
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
from app.application import chat_business_safety_attendance as attendance_safety
from app.application import chat_business_safety_leave as leave_safety
from app.application import chat_business_safety_output as output_safety
from app.application import chat_business_safety_personnel as personnel_safety
from app.application import planner_compat_service as planner_compat
from app.application.chat_business_safety_core import BusinessActorIdentity, BusinessChatIntent
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
    monkeypatch.setenv("WORKSPACE_ROOT", str(workspace))
    monkeypatch.setattr(safety, "resolve_safe_workspace_relpath", lambda rel: workspace / rel)
    return db_path, workspace


@pytest.mark.parametrize(
    ("message", "operation"),
    [
        ("我今天有没有迟到？", "attendance_read"),
        ("先介绍考勤制度，再查询1001号员工的姓名", "personnel_read"),
        ("请你先解释请假规则，然后帮李四登记明天事假半天", "leave_write"),
        ("先解释员工制度；查询李四是哪个部门", "personnel_read"),
        ("先介绍考勤规则，查询李四2026年7月13日打卡记录", "attendance_read"),
        ("ＡＩ业务员工，查询１００１号员工的姓名", "personnel_read"),
        ("AI-员工，查询1001号员工的姓名", "personnel_read"),
        ("研发部今天谁出勤", "attendance_read"),
        ("1001号员工叫什么名字？", "personnel_read"),
        ("请你作为AI业务员工，查询1001号员工的姓名", "personnel_read"),
        ("AI员工先查客户，再告诉我李四是哪个部门", "personnel_read"),
        ("数字员工，先查商品库存，然后查我今天有没有迟到", "attendance_read"),
        ("AI员工，帮李四登记明天事假半天，然后查询商品", "leave_write"),
        ("AI业务员工先查客户，再取消李四明天的请假", "leave_write"),
        ("智能员工，直接把今天考勤表打印出来，再查客户", "attendance_print"),
        ("AI员工，导出本月考勤表，再查客户", "attendance_export"),
        ("李四是哪个部门？", "personnel_read"),
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
        "ＡＩ业务员工，查询客户和商品",
        "AI-员工，查询客户和商品",
        "AI－业务－员工，查询客户和商品",
        "数字·员工，查询客户和商品",
        "先解释考勤制度，然后介绍请假规则",
        "AI员工，先解释考勤制度，再查询商品库存",
        "病假和事假有什么区别",
        "如何办理请假审批流程",
        "给我讲讲迟到规则怎么计算",
        "你好，今天心情不错",
        "这是我的新手第一单，请你作为 AI 业务员工查询客户和商品，再创建演示出货单",
        "请你作为 AI 员工，查一下演示客户，再查商品的可用数量",
        "ai业务员工，帮我查客户、商品和库存，然后准备出货单供我确认",
        "帮我让AI销售员工查一下客户和商品，并准备订单",
        "请人工智能业务员工查询客户，列出待我确认的开单计划",
        "请数字员工帮我查一下库存，再生成报价单",
        "智能员工，查询演示商品并告诉我可用数量",
        "请虚拟员工帮我查询客户并生成订单",
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


@pytest.mark.parametrize("prefix", ["", "AI业务员工，先查商品，再告诉我："])
def test_unmapped_current_user_never_gets_invented_attendance(
    business_db: tuple[Path, Path],
    prefix: str,
) -> None:
    result = safety.try_handle_business_chat_action(
        f"{prefix}我2026年7月13日有没有迟到？", user_id="not-mapped"
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


@pytest.mark.parametrize("prefix", ["", "AI业务员工，先查客户，再"])
def test_unknown_employee_leave_is_not_written(
    business_db: tuple[Path, Path],
    prefix: str,
) -> None:
    result = safety.try_handle_business_chat_action(
        f"{prefix}帮赵六登记2026年7月14日上午事假半天，主管已审批通过"
    )
    assert result is not None
    assert "没有找到“赵六”" in result["response"]
    assert result["execution_receipt"]["executed"] is False


@pytest.mark.parametrize("prefix", ["", "AI业务员工，先查商品；"])
def test_leave_cancel_is_blocked_instead_of_creating_or_claiming_cancelled(
    business_db: tuple[Path, Path],
    prefix: str,
) -> None:
    result = safety.try_handle_business_chat_action(f"{prefix}李四明天不休假了")
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


@pytest.mark.parametrize("prefix", ["", "请你作为 AI 业务员工，"])
def test_stream_path_preempts_legacy_planner_and_returns_same_receipt(
    business_db: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, prefix: str
) -> None:
    def fail_if_called(*_args: Any, **_kwargs: Any):
        raise AssertionError("legacy planner must not run for protected business actions")

    monkeypatch.setattr(chat_helpers, "_xcagi_guarded_planner_stream_events", fail_if_called)
    monkeypatch.setattr(
        "app.application.get_ai_chat_app_service",
        lambda: SimpleNamespace(_pending_workflows={}),
    )
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/ai/chat/stream",
            "headers": [],
            "client": ("127.0.0.1", 12345),
        }
    )
    body = chat_helpers.XcagiCompatChatBody(
        message=f"{prefix}我2026年7月13日有没有迟到？", user_id="u-1001"
    )
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
@pytest.mark.parametrize("prefix", ["", "请你作为 AI 业务员工，"])
async def test_json_path_preempts_both_mainline_and_legacy_chat(
    business_db: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, prefix: str
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
    body = chat_helpers.XcagiCompatChatBody(
        message=f"{prefix}1001号员工叫什么名字？", user_id="u-1001"
    )
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


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("前天", ("day", "2026-07-12", "2026-07-12")),
        ("昨日", ("day", "2026-07-13", "2026-07-13")),
        ("明天", ("day", "2026-07-15", "2026-07-15")),
        ("后天", ("day", "2026-07-16", "2026-07-16")),
        ("今日", ("day", "2026-07-14", "2026-07-14")),
        ("2026年8月2日", ("day", "2026-08-02", "2026-08-02")),
        ("8月3日", ("day", "2026-08-03", "2026-08-03")),
        ("2026年12月", ("month", "2026-12-01", "2026-12-31")),
        ("本月", ("month", "2026-07-01", "2026-07-31")),
        ("2026年13月1日", None),
        ("2月30日", None),
        ("2026年13月", None),
        ("没有日期", None),
    ],
)
def test_date_scope_parser_covers_supported_and_invalid_shapes(
    message: str, expected: tuple[str, str, str] | None
) -> None:
    from datetime import date

    assert attendance_safety._parse_date_scope(message, now=date(2026, 7, 14)) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('["08:00", 17]', ["08:00", "17"]),
        ('{"time":"08:00"}', []),
        ("not-json", []),
        (None, []),
    ],
)
def test_attendance_json_list_is_fail_closed(raw: Any, expected: list[str]) -> None:
    assert attendance_safety._json_list(raw) == expected


def test_attendance_read_failures_are_truthful(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    intent = BusinessChatIntent("attendance_read", "attendance")
    actor = BusinessActorIdentity(authenticated=False)

    missing = tmp_path / "missing.db"
    monkeypatch.setattr(safety, "_db_path", lambda: missing)
    result = attendance_safety._handle_attendance_read("今天考勤", intent, actor=actor)
    assert result["execution_receipt"]["reason"] == "attendance_database_missing"

    empty = tmp_path / "empty.db"
    sqlite3.connect(empty).close()
    monkeypatch.setattr(safety, "_db_path", lambda: empty)
    result = attendance_safety._handle_attendance_read("今天考勤", intent, actor=actor)
    assert result["execution_receipt"]["reason"] == "attendance_records_missing"

    broken = tmp_path / "broken.db"
    conn = sqlite3.connect(broken)
    conn.execute("CREATE TABLE attendance_daily_records (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(safety, "_db_path", lambda: broken)
    result = attendance_safety._handle_attendance_read("今天考勤", intent, actor=actor)
    assert result["execution_receipt"]["status"] == "failed"
    assert result["execution_receipt"]["reason"].startswith("attendance_query_failed:")

    result = attendance_safety._handle_attendance_read("考勤情况", intent, actor=actor)
    assert result["execution_receipt"]["reason"] == "missing_date_scope"


def test_attendance_read_covers_empty_punch_leave_and_multi_late_summaries(
    business_db: tuple[Path, Path],
) -> None:
    intent = BusinessChatIntent("attendance_read", "attendance")
    actor = BusinessActorIdentity(authenticated=False)

    empty = attendance_safety._handle_attendance_read(
        "李四2026年7月20日有没有迟到", intent, actor=actor
    )
    assert empty["execution_receipt"]["status"] == "verified_empty"

    punch = attendance_safety._handle_attendance_read(
        "李四2026年7月13日几点打卡", intent, actor=actor
    )
    assert "08:03:00" in punch["response"]

    conn = sqlite3.connect(str(business_db[0]))
    conn.execute("UPDATE attendance_daily_records SET leave_hours=4 WHERE employee_name='李四'")
    conn.commit()
    conn.close()
    leave = attendance_safety._handle_attendance_read(
        "李四2026年7月13日请假情况", intent, actor=actor
    )
    assert "1 条含请假时长" in leave["response"]

    late = attendance_safety._handle_attendance_read(
        "研发部2026年7月13日谁迟到", intent, actor=actor
    )
    assert "2 条真实考勤记录" in late["response"]
    assert "李四" in late["response"]


def test_attendance_read_covers_unscoped_employee_month_and_zero_summaries(
    business_db: tuple[Path, Path],
) -> None:
    intent = BusinessChatIntent("attendance_read", "attendance")
    actor = BusinessActorIdentity(authenticated=False)

    rows, meta, error = attendance_safety._attendance_rows(
        "考勤情况", actor=actor, require_scope=False
    )
    assert error is None
    assert meta == {}
    assert len(rows) == 2

    employee = attendance_safety._handle_attendance_read(
        "工号1001在2026年7月13日的考勤", intent, actor=actor
    )
    assert employee["execution_receipt"]["affected_rows"] == 1
    assert employee["execution_receipt"]["details"]["employee_no"] == "1001"

    month = attendance_safety._handle_attendance_read("2026年7月谁出勤", intent, actor=actor)
    month_details = month["execution_receipt"]["details"]
    assert month_details["scope"] == "month"
    assert (month_details["date_start"], month_details["date_end"]) == (
        "2026-07-01",
        "2026-07-31",
    )

    conn = sqlite3.connect(str(business_db[0]))
    conn.execute("UPDATE attendance_daily_records SET late_count_hint=0, leave_hours=0")
    conn.commit()
    conn.close()

    no_late = attendance_safety._handle_attendance_read(
        "研发部2026年7月13日谁迟到", intent, actor=actor
    )
    assert "其中 0 条带迟到标记" in no_late["response"]

    no_leave = attendance_safety._handle_attendance_read(
        "研发部2026年7月13日请假情况", intent, actor=actor
    )
    assert "其中 0 条含请假时长" in no_leave["response"]


def test_personnel_read_covers_missing_table_actor_empty_and_truncation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    business_db: tuple[Path, Path],
) -> None:
    intent = BusinessChatIntent("personnel_read", "personnel")
    anonymous = BusinessActorIdentity(authenticated=False)

    monkeypatch.setattr(safety, "_db_path", lambda: tmp_path / "missing.db")
    missing = personnel_safety._handle_personnel_read("查人员", intent, actor=anonymous)
    assert missing["execution_receipt"]["reason"] == "personnel_database_missing"

    empty_db = tmp_path / "empty.db"
    sqlite3.connect(empty_db).close()
    monkeypatch.setattr(safety, "_db_path", lambda: empty_db)
    no_table = personnel_safety._handle_personnel_read("查人员", intent, actor=anonymous)
    assert no_table["execution_receipt"]["reason"] == "personnel_table_missing"

    monkeypatch.setattr(safety, "_db_path", lambda: business_db[0])
    unmapped = personnel_safety._handle_personnel_read("我是谁", intent, actor=anonymous)
    assert unmapped["execution_receipt"]["reason"] == "current_user_not_mapped"

    actor = BusinessActorIdentity(authenticated=True, local_user_id="u-1001")
    current = personnel_safety._handle_personnel_read("我是谁", intent, actor=actor)
    assert "李四" in current["response"]

    not_found = personnel_safety._handle_personnel_read("查赵六的部门", intent, actor=anonymous)
    assert not_found["execution_receipt"]["status"] == "verified_empty"

    conn = sqlite3.connect(str(business_db[0]))
    for index in range(55):
        conn.execute(
            "INSERT INTO attendance_employees "
            "(employee_name, department, employee_no, position, user_id) VALUES (?, '研发部', ?, '工程师', ?)",
            (f"测试员工{index:02d}", f"T{index:02d}", f"test-{index:02d}"),
        )
    conn.commit()
    conn.close()
    all_rows = personnel_safety._handle_personnel_read("查人员", intent, actor=anonymous)
    assert "另有" in all_rows["response"]


def test_personnel_query_error_is_not_reported_as_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "broken-personnel.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE attendance_employees (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(safety, "_db_path", lambda: db_path)
    result = personnel_safety._handle_personnel_read(
        "查人员",
        BusinessChatIntent("personnel_read", "personnel"),
        actor=BusinessActorIdentity(authenticated=False),
    )
    assert result["execution_receipt"]["status"] == "failed"
    assert result["execution_receipt"]["reason"].startswith("personnel_query_failed:")


@pytest.mark.parametrize(
    ("message", "period", "hours", "approval"),
    [
        ("李四2026年7月14日上午事假", "morning", 4.0, "pending"),
        ("李四2026年7月14日下午病假", "afternoon", 4.0, "pending"),
        ("李四2026年7月14日年假半天", "half_day_unspecified", 4.0, "pending"),
        ("李四2026年7月14日调休全天", "full_day", 8.0, "pending"),
        ("李四2026年7月14日婚假2.5小时，经理同意", "hours", 2.5, "reported_approved"),
        ("李四2026年7月14日丧假，经理拒绝", "", 0.0, "pending"),
    ],
)
def test_leave_field_parser_covers_period_and_approval_shapes(
    message: str, period: str, hours: float, approval: str
) -> None:
    fields = leave_safety._leave_fields(message)
    assert fields["period"] == period
    assert fields["hours"] == hours
    assert fields["approval_status"] == approval


def test_leave_modify_current_actor_and_pending_upgrade(
    business_db: tuple[Path, Path],
) -> None:
    intent = BusinessChatIntent("leave_write", "attendance")
    actor = BusinessActorIdentity(authenticated=True, local_user_id="u-1001")

    blocked = leave_safety._handle_leave_write("把李四明天事假改成病假", intent, actor=actor)
    assert blocked["execution_receipt"]["reason"] == "leave_modify_tool_unavailable"

    message = "我2026年7月16日下午病假半天"
    created = leave_safety._handle_leave_write(message, intent, actor=actor)
    assert created["execution_receipt"]["status"] == "created"
    assert created["execution_receipt"]["details"]["employee_name"] == "李四"

    approved = leave_safety._handle_leave_write(message + "，主管已经审批通过", intent, actor=actor)
    assert approved["execution_receipt"]["status"] == "updated"
    assert approved["execution_receipt"]["details"]["approval_status"] == "reported_approved"


def test_leave_write_rejects_missing_database_and_personnel_table(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    business_db: tuple[Path, Path],
) -> None:
    intent = BusinessChatIntent("leave_write", "attendance")
    actor = BusinessActorIdentity(authenticated=False)
    message = "李四2026年7月18日上午事假半天"

    unmapped = leave_safety._handle_leave_write("我2026年7月18日上午事假半天", intent, actor=actor)
    assert unmapped["execution_receipt"]["reason"] == "missing_required_fields"

    monkeypatch.setattr(safety, "_db_path", lambda: tmp_path / "missing.db")
    missing_identity = leave_safety._handle_leave_write(
        "我2026年7月18日上午事假半天", intent, actor=actor
    )
    assert missing_identity["execution_receipt"]["reason"] == "missing_required_fields"

    missing = leave_safety._handle_leave_write(message, intent, actor=actor)
    assert missing["execution_receipt"]["reason"] == "personnel_database_missing"

    empty_db = tmp_path / "empty.db"
    sqlite3.connect(empty_db).close()
    monkeypatch.setattr(safety, "_db_path", lambda: empty_db)
    no_table = leave_safety._handle_leave_write(message, intent, actor=actor)
    assert no_table["execution_receipt"]["reason"] == "personnel_table_missing"


class _PrinterServiceResult:
    def __init__(self, printers: Any, result: Any = None) -> None:
        self.printers = printers
        self.result = result

    def get_printers(self) -> Any:
        if isinstance(self.printers, Exception):
            raise self.printers
        return self.printers

    def print_document(self, _path: str) -> Any:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_attendance_export_covers_query_empty_and_write_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intent = BusinessChatIntent("attendance_export", "attendance")
    actor = BusinessActorIdentity(authenticated=False)

    monkeypatch.setattr(
        output_safety,
        "_attendance_rows",
        lambda *_args, **_kwargs: ([], {}, "attendance_database_missing"),
    )
    query_error = output_safety._handle_attendance_export("今天考勤", intent, actor=actor)
    assert query_error["execution_receipt"]["reason"] == "attendance_database_missing"

    monkeypatch.setattr(
        output_safety, "_attendance_rows", lambda *_args, **_kwargs: ([], {"scope": "day"}, None)
    )
    empty = output_safety._handle_attendance_export("今天考勤", intent, actor=actor)
    assert empty["execution_receipt"]["reason"] == "no_attendance_rows"

    monkeypatch.setattr(
        output_safety,
        "_attendance_rows",
        lambda *_args, **_kwargs: ([{"work_date": "2026-07-14"}], {}, None),
    )
    monkeypatch.setattr(
        output_safety,
        "_create_attendance_export",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )
    failed = output_safety._handle_attendance_export("今天考勤", intent, actor=actor)
    assert failed["execution_receipt"]["status"] == "failed"
    assert failed["execution_receipt"]["reason"].startswith("attendance_export_failed:")


@pytest.mark.parametrize(
    ("printers", "print_result", "reason"),
    [
        (RuntimeError("offline"), None, "printer_status_failed:"),
        ([], None, "no_available_printer"),
        ({"success": False, "printers": []}, None, "no_available_printer"),
        ({"success": True, "printers": [{"name": "QA"}]}, None, "printer_rejected"),
        (
            {"success": True, "count": 1, "printers": [{"name": "QA"}]},
            {"success": False, "message": "queue full"},
            "queue full",
        ),
    ],
)
def test_attendance_print_covers_printer_failure_contracts(
    monkeypatch: pytest.MonkeyPatch, printers: Any, print_result: Any, reason: str
) -> None:
    intent = BusinessChatIntent("attendance_print", "attendance")
    actor = BusinessActorIdentity(authenticated=False)
    monkeypatch.setattr(
        output_safety,
        "_attendance_rows",
        lambda *_args, **_kwargs: ([{"work_date": "2026-07-14"}], {}, None),
    )
    monkeypatch.setattr(
        safety, "_get_printer_service", lambda: _PrinterServiceResult(printers, print_result)
    )
    monkeypatch.setattr(
        output_safety,
        "_create_attendance_export",
        lambda *_args, **_kwargs: (Path(__file__), "test.xlsx"),
    )
    result = output_safety._handle_attendance_print("打印今天考勤", intent, actor=actor)
    assert result["execution_receipt"]["executed"] is False
    assert result["execution_receipt"]["reason"].startswith(reason)


def test_attendance_print_covers_query_empty_and_submit_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intent = BusinessChatIntent("attendance_print", "attendance")
    actor = BusinessActorIdentity(authenticated=False)

    monkeypatch.setattr(
        output_safety,
        "_attendance_rows",
        lambda *_args, **_kwargs: ([], {}, "attendance_records_missing"),
    )
    query_error = output_safety._handle_attendance_print("打印今天考勤", intent, actor=actor)
    assert query_error["execution_receipt"]["reason"] == "attendance_records_missing"

    monkeypatch.setattr(output_safety, "_attendance_rows", lambda *_args, **_kwargs: ([], {}, None))
    empty = output_safety._handle_attendance_print("打印今天考勤", intent, actor=actor)
    assert empty["execution_receipt"]["reason"] == "no_attendance_rows"

    monkeypatch.setattr(
        output_safety,
        "_attendance_rows",
        lambda *_args, **_kwargs: ([{"work_date": "2026-07-14"}], {}, None),
    )
    monkeypatch.setattr(
        safety,
        "_get_printer_service",
        lambda: _PrinterServiceResult(
            {"success": True, "count": 1, "printers": [{"name": "QA"}]},
            RuntimeError("submit failed"),
        ),
    )
    monkeypatch.setattr(
        output_safety,
        "_create_attendance_export",
        lambda *_args, **_kwargs: (Path(__file__), "test.xlsx"),
    )
    failed = output_safety._handle_attendance_print("打印今天考勤", intent, actor=actor)
    assert failed["execution_receipt"]["status"] == "failed"
    assert failed["execution_receipt"]["reason"].startswith("print_submit_failed:")


@pytest.mark.parametrize("prefix", ["ＡＩ业务员工", "AI-员工", "数字·员工"])
def test_assistant_alias_does_not_open_personnel_store(prefix, monkeypatch):
    def unexpected_database_lookup():
        pytest.fail("A customer/product request must not open the personnel database")

    monkeypatch.setattr(safety, "_db_path", unexpected_database_lookup)
    assert safety.try_handle_business_chat_action(f"{prefix}，查询客户和商品") is None


def test_explanation_prefix_does_not_bypass_personnel_receipt(business_db):
    result = safety.try_handle_business_chat_action("先介绍考勤制度，再查询1001号员工的姓名")
    assert result is not None
    assert "李四" in result["response"]
    assert result["execution_receipt"]["verified"] is True
