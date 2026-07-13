from __future__ import annotations

import sqlite3
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.application import chat_business_safety_actions as actions
from app.application import chat_business_safety_read as reads
from app.application.chat_business_safety import BusinessActorIdentity, BusinessChatIntent
from app.fastapi_routes import mobile_api as _mobile_api  # noqa: F401
from app.fastapi_routes.mobile_extensions import routes_ai_groups as groups
from app.infrastructure.ocr import macos_vision as vision

_ACTOR = BusinessActorIdentity(authenticated=False)
_ATTENDANCE_INTENT = BusinessChatIntent("attendance_read", "attendance")
_PERSONNEL_INTENT = BusinessChatIntent("personnel_read", "personnel")


@pytest.mark.parametrize(
    ("message", "now", "expected"),
    [
        ("前天", date(2026, 7, 13), ("day", "2026-07-11", "2026-07-11")),
        ("昨日", date(2026, 7, 13), ("day", "2026-07-12", "2026-07-12")),
        ("明天", date(2026, 7, 13), ("day", "2026-07-14", "2026-07-14")),
        ("后天", date(2026, 7, 13), ("day", "2026-07-15", "2026-07-15")),
        ("今日", date(2026, 7, 13), ("day", "2026-07-13", "2026-07-13")),
        ("2026/12/31", date(2026, 7, 13), ("day", "2026-12-31", "2026-12-31")),
        ("7月14日", date(2026, 7, 13), ("day", "2026-07-14", "2026-07-14")),
        ("2026年12月", date(2026, 7, 13), ("month", "2026-12-01", "2026-12-31")),
        ("本月", date(2026, 12, 13), ("month", "2026-12-01", "2026-12-31")),
        ("2026年13月", date(2026, 7, 13), None),
        ("2026年2月30日", date(2026, 7, 13), None),
        ("2月30日", date(2026, 7, 13), None),
        ("未指定日期", date(2026, 7, 13), None),
    ],
)
def test_split_date_scope_contracts(
    message: str, now: date, expected: tuple[str, str, str] | None
) -> None:
    assert reads._parse_date_scope(message, now=now) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [('["08:00", 17]', ["08:00", "17"]), ('{"time": "08:00"}', []), ("not-json", [])],
)
def test_split_json_list_contracts(value: str, expected: list[str]) -> None:
    assert reads._json_list(value) == expected


@pytest.mark.parametrize(
    "error",
    [
        "missing_date_scope",
        "current_user_not_mapped",
        "attendance_database_missing",
        "attendance_records_missing",
        "attendance_query_failed:locked",
    ],
)
def test_split_attendance_error_receipts_cover_all_states(error: str) -> None:
    result = reads._attendance_error_payload(_ATTENDANCE_INTENT, error, {"scope": "day"})
    assert result["execution_receipt"]["executed"] is False
    assert result["execution_receipt"]["reason"] == error


def test_split_personnel_read_reports_missing_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reads, "_connect_existing", lambda: None)
    result = reads._handle_personnel_read("1001号员工", _PERSONNEL_INTENT, actor=_ACTOR)
    assert result["execution_receipt"]["reason"] == "personnel_database_missing"


def test_split_personnel_read_reports_missing_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "empty.db"
    sqlite3.connect(path).close()
    monkeypatch.setattr(reads, "_connect_existing", lambda: sqlite3.connect(path))
    result = reads._handle_personnel_read("查询人员", _PERSONNEL_INTENT, actor=_ACTOR)
    assert result["execution_receipt"]["reason"] == "personnel_table_missing"


def test_split_attendance_rows_cover_missing_store_and_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(reads, "_connect_existing", lambda: None)
    assert reads._attendance_rows("今天", actor=_ACTOR)[2] == "attendance_database_missing"

    path = tmp_path / "empty.db"
    sqlite3.connect(path).close()
    monkeypatch.setattr(reads, "_connect_existing", lambda: sqlite3.connect(path))
    assert reads._attendance_rows("今天", actor=_ACTOR)[2] == "attendance_records_missing"


@pytest.mark.parametrize(
    ("message", "rows", "expected"),
    [
        ("今天有没有迟到", [], "2026-07-01 至 2026-07-31"),
        (
            "今天有没有迟到",
            [{"work_date": "2026-07-13", "employee_name": "李四", "late_count_hint": 0}],
            "迟到标记为 0",
        ),
        (
            "今天有没有迟到",
            [
                {"work_date": "2026-07-13", "employee_name": "李四", "late_count_hint": 1},
                {"work_date": "2026-07-13", "employee_name": "王五", "late_count_hint": 0},
            ],
            "1 条带迟到标记",
        ),
        (
            "今天几点打卡",
            [{"work_date": "2026-07-13", "employee_name": "李四", "all_times_json": "[]"}],
            "无打卡时间",
        ),
        (
            "今天谁请假",
            [
                {"work_date": "2026-07-13", "employee_name": "李四", "leave_hours": 4},
                {"work_date": "2026-07-13", "employee_name": "王五", "leave_hours": 0},
            ],
            "1 条含请假时长",
        ),
    ],
)
def test_split_attendance_response_modes(
    message: str, rows: list[dict[str, Any]], expected: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        reads,
        "_attendance_rows",
        lambda *_args, **_kwargs: (
            rows,
            {"date_start": "2026-07-01", "date_end": "2026-07-31"},
            None,
        ),
    )
    result = reads._handle_attendance_read(message, _ATTENDANCE_INTENT, actor=_ACTOR)
    assert expected in result["response"]


@pytest.mark.parametrize(
    ("message", "period", "hours", "approved"),
    [
        ("李四明天事假上午", "morning", 4.0, False),
        ("李四明天事假下午", "afternoon", 4.0, False),
        ("李四明天事假半天", "half_day_unspecified", 4.0, False),
        ("李四明天事假全天", "full_day", 8.0, False),
        ("李四明天事假2.5小时", "hours", 2.5, False),
        ("李四明天事假，主管已同意", "", 0.0, True),
        ("李四明天事假，主管未同意", "", 0.0, False),
    ],
)
def test_split_leave_field_variants(
    message: str, period: str, hours: float, approved: bool
) -> None:
    fields = actions._leave_fields(message)
    assert fields["period"] == period
    assert fields["hours"] == hours
    assert (fields["approval_status"] == "reported_approved") is approved


class _IdentityConnection:
    closed = False

    def close(self) -> None:
        self.closed = True


def test_split_leave_identity_resolution_closes_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _IdentityConnection()
    monkeypatch.setattr(actions, "_connect_existing", lambda: conn)
    monkeypatch.setattr(
        actions,
        "_leave_fields",
        lambda _message: {
            "employee_name": "",
            "leave_type": "事假",
            "leave_date": "2026-07-14",
            "period": "",
            "hours": 0.0,
            "approval_status": "pending",
            "approval_evidence": "",
            "approval_verified": False,
        },
    )
    monkeypatch.setattr(
        actions,
        "_resolve_person_from_actor",
        lambda *_args: {"employee_name": "李四"},
    )
    result = actions._handle_leave_write(
        "我明天事假", BusinessChatIntent("leave_write", "attendance"), actor=_ACTOR
    )
    assert result["execution_receipt"]["reason"] == "missing_required_fields"
    assert conn.closed is True


def test_split_export_and_print_failure_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    intent_export = BusinessChatIntent("attendance_export", "attendance")
    intent_print = BusinessChatIntent("attendance_print", "attendance")
    meta = {"scope": "month", "date_start": "2026-07-01", "date_end": "2026-07-31"}

    monkeypatch.setattr(actions, "_attendance_rows", lambda *_args, **_kwargs: ([], meta, None))
    assert (
        actions._handle_attendance_export("本月", intent_export, actor=_ACTOR)["execution_receipt"][
            "reason"
        ]
        == "no_attendance_rows"
    )
    assert (
        actions._handle_attendance_print("本月", intent_print, actor=_ACTOR)["execution_receipt"][
            "reason"
        ]
        == "no_attendance_rows"
    )

    rows = [{"work_date": "2026-07-01", "employee_name": "李四"}]
    monkeypatch.setattr(actions, "_attendance_rows", lambda *_args, **_kwargs: (rows, meta, None))
    monkeypatch.setattr(
        actions,
        "_create_attendance_export",
        lambda *_args: (_ for _ in ()).throw(OSError("disk full")),
    )
    export_result = actions._handle_attendance_export("本月", intent_export, actor=_ACTOR)
    assert export_result["execution_receipt"]["reason"] == "attendance_export_failed"

    monkeypatch.setattr(
        actions,
        "_get_printer_service",
        lambda: (_ for _ in ()).throw(OSError("printer offline")),
    )
    print_result = actions._handle_attendance_print("本月", intent_print, actor=_ACTOR)
    assert print_result["execution_receipt"]["reason"] == "printer_status_failed"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("refs/heads/feature/demo", "feature/demo"),
        ("refs/remotes/origin/main", "main"),
        ("origin/release 1", "release-1"),
        ("HEAD", ""),
        ("feature//bad", ""),
        ("feature..bad", ""),
        ("release.lock", ""),
        (None, ""),
    ],
)
def test_split_mobile_branch_name_sanitizing(raw: Any, expected: str) -> None:
    assert groups._clean_mobile_git_branch(raw) == expected


def test_split_mobile_local_git_branch_discovery(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    results = iter(
        [
            SimpleNamespace(returncode=0, stdout="main\n"),
            SimpleNamespace(
                returncode=0,
                stdout="main\norigin/main\nfeature one\norigin/HEAD\nrefs/remotes/origin/dev\n",
            ),
        ]
    )
    parent = SimpleNamespace(
        subprocess=SimpleNamespace(run=lambda *_args, **_kwargs: next(results))
    )
    monkeypatch.setattr(groups, "_parent", lambda: parent)
    branches = groups._mobile_git_branches_from_repo(tmp_path)
    assert branches[0] == {"name": "main", "current": True, "remote": True}
    assert {row["name"] for row in branches} == {"main", "feature-one", "dev"}


def test_split_mobile_git_discovery_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    parent = SimpleNamespace(
        subprocess=SimpleNamespace(run=lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError()))
    )
    monkeypatch.setattr(groups, "_parent", lambda: parent)
    assert groups._mobile_git_branches_from_repo(tmp_path) == []
    assert groups._mobile_git_branches_from_remote() == []


def test_split_mobile_remote_git_branch_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    result = SimpleNamespace(
        returncode=0,
        stdout="abc refs/heads/main\ndef refs/heads/feature/mobile\ninvalid line\n",
    )
    parent = SimpleNamespace(subprocess=SimpleNamespace(run=lambda *_args, **_kwargs: result))
    monkeypatch.setattr(groups, "_parent", lambda: parent)
    assert groups._mobile_git_branches_from_remote() == [
        {"name": "main", "current": False, "remote": True},
        {"name": "feature/mobile", "current": False, "remote": True},
    ]


def test_split_macos_vision_availability(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vision.sys, "platform", "linux")
    assert vision.is_macos_vision_available() is False
    monkeypatch.setattr(vision.sys, "platform", "darwin")
    monkeypatch.setattr(vision.os.path, "isfile", lambda _path: True)
    assert vision.is_macos_vision_available() is True


class _FakeImage:
    def save(self, path: str, *, format: str) -> None:
        Path(path).write_bytes(format.encode())


def test_split_macos_vision_success_and_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_pil = SimpleNamespace(Image=SimpleNamespace(fromarray=lambda _array: _FakeImage()))
    monkeypatch.setitem(sys.modules, "PIL", fake_pil)
    monkeypatch.setattr(
        vision.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="  text  ", stderr=""),
    )
    assert vision.recognize_macos_vision(object(), cleaner=str.strip) == "text"

    monkeypatch.setattr(
        vision.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout="", stderr="failed"),
    )
    assert vision.recognize_macos_vision(object(), cleaner=str.strip) == ""
