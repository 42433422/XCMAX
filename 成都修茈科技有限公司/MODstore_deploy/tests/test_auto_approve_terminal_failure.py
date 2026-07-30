from __future__ import annotations

import pytest

import modstore_server.db.base as db_base
import modstore_server.models as models
from modstore_server.auto_approve_policy import _mark_change_request_validation_failed
from modstore_server.db.employee_ops import EmployeeChangeRequest


@pytest.fixture
def session_factory(tmp_path, monkeypatch):
    for engine in {models._engine, db_base._engine}:
        if engine is not None:
            engine.dispose()
    models._engine = None
    models._SessionFactory = None
    db_base._engine = None
    db_base._SessionFactory = None
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "auto-approve.sqlite"))
    models.init_db()
    yield models.get_session_factory()
    for engine in {models._engine, db_base._engine}:
        if engine is not None:
            engine.dispose()
    models._engine = None
    models._SessionFactory = None
    db_base._engine = None
    db_base._SessionFactory = None


def test_narrow_ci_failure_is_terminal(session_factory, tmp_path):
    with session_factory() as session:
        session.add(
            EmployeeChangeRequest(
                id=901,
                source_employee_id="code-employee",
                change_kind="file_edit",
                workspace_root_hint=str(tmp_path),
                target_paths_json="[]",
                diff_summary="",
                diff_blob="{}",
                status="pending",
                risk_level="medium",
            )
        )
        session.commit()

    changed = _mark_change_request_validation_failed(
        901,
        "py_compile",
        session_factory=session_factory,
    )

    with session_factory() as session:
        row = session.get(EmployeeChangeRequest, 901)
        assert changed is True
        assert row is not None
        assert row.status == "failed"
        assert row.error == "narrow_ci_failed:py_compile"


def test_terminal_change_request_is_not_rewritten(session_factory, tmp_path):
    with session_factory() as session:
        session.add(
            EmployeeChangeRequest(
                id=902,
                source_employee_id="code-employee",
                change_kind="file_edit",
                workspace_root_hint=str(tmp_path),
                target_paths_json="[]",
                diff_summary="",
                diff_blob="{}",
                status="applied",
                risk_level="medium",
            )
        )
        session.commit()

    changed = _mark_change_request_validation_failed(
        902,
        "pytest",
        session_factory=session_factory,
    )

    with session_factory() as session:
        row = session.get(EmployeeChangeRequest, 902)
        assert changed is False
        assert row is not None
        assert row.status == "applied"
