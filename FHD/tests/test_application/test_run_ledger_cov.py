"""Branch coverage for app/application/employee_runtime/run_ledger.py."""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import MagicMock, patch


class _FakeDB:
    """Context-manager DB mock supporting add/flush/commit/get/query chain."""

    def __init__(self, *, get_return=None, all_rows=None, next_id=1):
        self._get_return = get_return
        self._all_rows = all_rows if all_rows is not None else []
        self._next_id = next_id
        self.added: list = []
        self.committed = False
        self.flushed = False
        self.last_limit: int | None = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        self.flushed = True
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = self._next_id
                self._next_id += 1

    def commit(self):
        self.committed = True

    def get(self, model, pk):
        return self._get_return

    def query(self, model):
        return self

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args):
        return self

    def limit(self, n):
        self.last_limit = n
        return self

    def all(self):
        return list(self._all_rows)


def _make_row(
    *,
    row_id=1,
    employee_id="emp1",
    status="running",
    attempts=1,
    verified=0,
    error_text="",
    created_at=None,
    finished_at=None,
):
    row = MagicMock()
    row.id = row_id
    row.employee_id = employee_id
    row.status = status
    row.attempts = attempts
    row.verified = verified
    row.error_text = error_text
    row.created_at = created_at
    row.finished_at = finished_at
    return row


def _patch_db(db):
    return patch(
        "app.application.employee_runtime.run_ledger.get_db",
        return_value=db,
    )


class TestCreateEmployeeRunLog:
    def test_create_normal(self):
        from app.application.employee_runtime.run_ledger import create_employee_run_log

        db = _FakeDB()
        with _patch_db(db):
            run_id = create_employee_run_log(
                employee_id="emp1",
                input_payload={"k": "v"},
                tenant_id=1,
                session_id="sess1",
                user_id=1,
            )
        assert run_id == 1
        assert db.committed is True
        assert db.flushed is True
        assert len(db.added) == 1
        row = db.added[0]
        assert row.employee_id == "emp1"
        assert row.tenant_id == 1
        assert row.session_id == "sess1"
        assert row.user_id == 1
        assert row.status == "running"
        assert json.loads(row.input_json) == {"k": "v"}

    def test_create_strips_employee_id(self):
        from app.application.employee_runtime.run_ledger import create_employee_run_log

        db = _FakeDB()
        with _patch_db(db):
            create_employee_run_log(employee_id="  emp2  ")
        assert db.added[0].employee_id == "emp2"

    def test_create_empty_employee_id(self):
        from app.application.employee_runtime.run_ledger import create_employee_run_log

        db = _FakeDB()
        with _patch_db(db):
            create_employee_run_log(employee_id="")
        assert db.added[0].employee_id == ""

    def test_create_none_employee_id(self):
        from app.application.employee_runtime.run_ledger import create_employee_run_log

        db = _FakeDB()
        with _patch_db(db):
            create_employee_run_log(employee_id=None)
        assert db.added[0].employee_id == ""

    def test_create_none_payload(self):
        from app.application.employee_runtime.run_ledger import create_employee_run_log

        db = _FakeDB()
        with _patch_db(db):
            create_employee_run_log(employee_id="emp3", input_payload=None)
        assert json.loads(db.added[0].input_json) == {}

    def test_create_empty_payload(self):
        from app.application.employee_runtime.run_ledger import create_employee_run_log

        db = _FakeDB()
        with _patch_db(db):
            create_employee_run_log(employee_id="emp3b", input_payload={})
        assert json.loads(db.added[0].input_json) == {}

    def test_create_none_session_id(self):
        from app.application.employee_runtime.run_ledger import create_employee_run_log

        db = _FakeDB()
        with _patch_db(db):
            create_employee_run_log(employee_id="emp4", session_id=None)
        assert db.added[0].session_id is None

    def test_create_strips_session_id(self):
        from app.application.employee_runtime.run_ledger import create_employee_run_log

        db = _FakeDB()
        with _patch_db(db):
            create_employee_run_log(employee_id="emp5", session_id="  s1  ")
        assert db.added[0].session_id == "s1"

    def test_create_returns_int_id(self):
        from app.application.employee_runtime.run_ledger import create_employee_run_log

        db = _FakeDB(next_id=42)
        with _patch_db(db):
            run_id = create_employee_run_log(employee_id="emp6")
        assert run_id == 42
        assert isinstance(run_id, int)

    def test_create_default_optional_args(self):
        from app.application.employee_runtime.run_ledger import create_employee_run_log

        db = _FakeDB()
        with _patch_db(db):
            create_employee_run_log(employee_id="emp7")
        row = db.added[0]
        assert row.tenant_id is None
        assert row.session_id is None
        assert row.user_id is None
        assert json.loads(row.input_json) == {}


class TestFinishEmployeeRunLog:
    def test_finish_normal_success(self):
        from app.application.employee_runtime.run_ledger import finish_employee_run_log

        row = _make_row(row_id=10, status="running")
        db = _FakeDB(get_return=row)
        with _patch_db(db):
            finish_employee_run_log(
                10,
                status="success",
                output={"result": "ok"},
                error="",
                attempts=3,
                verified=True,
            )
        assert row.status == "success"
        assert json.loads(row.output_json) == {"result": "ok"}
        assert row.error_text == ""
        assert row.attempts == 3
        assert row.verified == 1
        assert row.finished_at is not None
        assert db.committed is True

    def test_finish_run_not_found(self):
        from app.application.employee_runtime.run_ledger import finish_employee_run_log

        db = _FakeDB(get_return=None)
        with _patch_db(db):
            finish_employee_run_log(999, status="success")
        assert db.committed is False

    def test_finish_none_status_defaults_to_failed(self):
        from app.application.employee_runtime.run_ledger import finish_employee_run_log

        row = _make_row()
        db = _FakeDB(get_return=row)
        with _patch_db(db):
            finish_employee_run_log(1, status=None)
        assert row.status == "failed"

    def test_finish_empty_status_defaults_to_failed(self):
        from app.application.employee_runtime.run_ledger import finish_employee_run_log

        row = _make_row()
        db = _FakeDB(get_return=row)
        with _patch_db(db):
            finish_employee_run_log(1, status="")
        assert row.status == "failed"

    def test_finish_status_truncated_to_32(self):
        from app.application.employee_runtime.run_ledger import finish_employee_run_log

        row = _make_row()
        db = _FakeDB(get_return=row)
        long_status = "x" * 40
        with _patch_db(db):
            finish_employee_run_log(1, status=long_status)
        assert row.status == "x" * 32

    def test_finish_none_output_defaults_to_empty(self):
        from app.application.employee_runtime.run_ledger import finish_employee_run_log

        row = _make_row()
        db = _FakeDB(get_return=row)
        with _patch_db(db):
            finish_employee_run_log(1, status="success", output=None)
        assert json.loads(row.output_json) == {}

    def test_finish_error_truncated_to_4000(self):
        from app.application.employee_runtime.run_ledger import finish_employee_run_log

        row = _make_row()
        db = _FakeDB(get_return=row)
        long_err = "e" * 5000
        with _patch_db(db):
            finish_employee_run_log(1, status="failed", error=long_err)
        assert row.error_text == "e" * 4000

    def test_finish_none_error_defaults_to_empty(self):
        from app.application.employee_runtime.run_ledger import finish_employee_run_log

        row = _make_row()
        db = _FakeDB(get_return=row)
        with _patch_db(db):
            finish_employee_run_log(1, status="failed", error=None)
        assert row.error_text == ""

    def test_finish_attempts_zero_becomes_one(self):
        from app.application.employee_runtime.run_ledger import finish_employee_run_log

        row = _make_row()
        db = _FakeDB(get_return=row)
        with _patch_db(db):
            finish_employee_run_log(1, status="success", attempts=0)
        assert row.attempts == 1

    def test_finish_attempts_negative_becomes_one(self):
        from app.application.employee_runtime.run_ledger import finish_employee_run_log

        row = _make_row()
        db = _FakeDB(get_return=row)
        with _patch_db(db):
            finish_employee_run_log(1, status="success", attempts=-5)
        assert row.attempts == 1

    def test_finish_verified_false_sets_zero(self):
        from app.application.employee_runtime.run_ledger import finish_employee_run_log

        row = _make_row()
        db = _FakeDB(get_return=row)
        with _patch_db(db):
            finish_employee_run_log(1, status="success", verified=False)
        assert row.verified == 0

    def test_finish_default_attempts_is_one(self):
        from app.application.employee_runtime.run_ledger import finish_employee_run_log

        row = _make_row()
        db = _FakeDB(get_return=row)
        with _patch_db(db):
            finish_employee_run_log(1, status="success")
        assert row.attempts == 1

    def test_finish_default_verified_is_zero(self):
        from app.application.employee_runtime.run_ledger import finish_employee_run_log

        row = _make_row()
        db = _FakeDB(get_return=row)
        with _patch_db(db):
            finish_employee_run_log(1, status="success")
        assert row.verified == 0


class TestListEmployeeRunLogs:
    def test_list_normal(self):
        from app.application.employee_runtime.run_ledger import list_employee_run_logs

        row = _make_row(
            row_id=5,
            employee_id="emp1",
            status="success",
            attempts=2,
            verified=1,
            error_text="",
            created_at=datetime(2026, 1, 1, 10, 0, 0),
            finished_at=datetime(2026, 1, 1, 10, 5, 0),
        )
        db = _FakeDB(all_rows=[row])
        with _patch_db(db):
            result = list_employee_run_logs("emp1")
        assert len(result) == 1
        item = result[0]
        assert item["id"] == 5
        assert item["employee_id"] == "emp1"
        assert item["status"] == "success"
        assert item["attempts"] == 2
        assert item["verified"] is True
        assert item["error"] == ""
        assert "2026" in item["created_at"]
        assert "2026" in item["finished_at"]

    def test_list_empty_employee_id_returns_empty(self):
        from app.application.employee_runtime.run_ledger import list_employee_run_logs

        db = _FakeDB(all_rows=[_make_row()])
        with _patch_db(db):
            result = list_employee_run_logs("")
        assert result == []

    def test_list_none_employee_id_returns_empty(self):
        from app.application.employee_runtime.run_ledger import list_employee_run_logs

        db = _FakeDB(all_rows=[_make_row()])
        with _patch_db(db):
            result = list_employee_run_logs(None)
        assert result == []

    def test_list_whitespace_employee_id_returns_empty(self):
        from app.application.employee_runtime.run_ledger import list_employee_run_logs

        db = _FakeDB(all_rows=[_make_row()])
        with _patch_db(db):
            result = list_employee_run_logs("   ")
        assert result == []

    def test_list_strips_employee_id(self):
        from app.application.employee_runtime.run_ledger import list_employee_run_logs

        row = _make_row(employee_id="emp1")
        db = _FakeDB(all_rows=[row])
        with _patch_db(db):
            result = list_employee_run_logs("  emp1  ")
        assert len(result) == 1
        assert result[0]["employee_id"] == "emp1"

    def test_list_default_limit_is_50(self):
        from app.application.employee_runtime.run_ledger import list_employee_run_logs

        db = _FakeDB(all_rows=[])
        with _patch_db(db):
            list_employee_run_logs("emp1")
        assert db.last_limit == 50

    def test_list_limit_capped_to_200(self):
        from app.application.employee_runtime.run_ledger import list_employee_run_logs

        db = _FakeDB(all_rows=[])
        with _patch_db(db):
            list_employee_run_logs("emp1", limit=500)
        assert db.last_limit == 200

    def test_list_limit_at_200_boundary(self):
        from app.application.employee_runtime.run_ledger import list_employee_run_logs

        db = _FakeDB(all_rows=[])
        with _patch_db(db):
            list_employee_run_logs("emp1", limit=200)
        assert db.last_limit == 200

    def test_list_limit_zero_becomes_one(self):
        from app.application.employee_runtime.run_ledger import list_employee_run_logs

        db = _FakeDB(all_rows=[])
        with _patch_db(db):
            list_employee_run_logs("emp1", limit=0)
        assert db.last_limit == 1

    def test_list_limit_negative_becomes_one(self):
        from app.application.employee_runtime.run_ledger import list_employee_run_logs

        db = _FakeDB(all_rows=[])
        with _patch_db(db):
            list_employee_run_logs("emp1", limit=-10)
        assert db.last_limit == 1

    def test_list_limit_one(self):
        from app.application.employee_runtime.run_ledger import list_employee_run_logs

        db = _FakeDB(all_rows=[])
        with _patch_db(db):
            list_employee_run_logs("emp1", limit=1)
        assert db.last_limit == 1

    def test_list_empty_rows(self):
        from app.application.employee_runtime.run_ledger import list_employee_run_logs

        db = _FakeDB(all_rows=[])
        with _patch_db(db):
            result = list_employee_run_logs("emp1")
        assert result == []

    def test_list_none_dates_return_empty_strings(self):
        from app.application.employee_runtime.run_ledger import list_employee_run_logs

        row = _make_row(created_at=None, finished_at=None)
        db = _FakeDB(all_rows=[row])
        with _patch_db(db):
            result = list_employee_run_logs("emp1")
        assert result[0]["created_at"] == ""
        assert result[0]["finished_at"] == ""

    def test_list_verified_false(self):
        from app.application.employee_runtime.run_ledger import list_employee_run_logs

        row = _make_row(verified=0)
        db = _FakeDB(all_rows=[row])
        with _patch_db(db):
            result = list_employee_run_logs("emp1")
        assert result[0]["verified"] is False

    def test_list_multiple_rows(self):
        from app.application.employee_runtime.run_ledger import list_employee_run_logs

        rows = [
            _make_row(row_id=1, employee_id="emp1"),
            _make_row(row_id=2, employee_id="emp1"),
        ]
        db = _FakeDB(all_rows=rows)
        with _patch_db(db):
            result = list_employee_run_logs("emp1")
        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[1]["id"] == 2

    def test_list_with_error_text(self):
        from app.application.employee_runtime.run_ledger import list_employee_run_logs

        row = _make_row(error_text="something went wrong")
        db = _FakeDB(all_rows=[row])
        with _patch_db(db):
            result = list_employee_run_logs("emp1")
        assert result[0]["error"] == "something went wrong"
