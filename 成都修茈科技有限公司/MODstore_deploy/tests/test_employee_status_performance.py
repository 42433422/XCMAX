"""Dashboard SQL is independent of employee count; its rolling window stays compatible."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from modstore_server import employee_status_api as api
from modstore_server.models import (
    CatalogItem,
    EmployeeChangeRequest,
    EmployeeExecutionMetric,
    User,
)


@pytest.mark.parametrize("employee_count", [0, 1, 50])
def test_employee_summary_uses_three_queries_and_latest_ten_window(
    tmp_path, monkeypatch, employee_count
):
    engine = create_engine(f"sqlite:///{tmp_path / 'status.sqlite'}")
    for model in (User, CatalogItem, EmployeeExecutionMetric, EmployeeChangeRequest):
        model.__table__.create(engine)
    now = datetime.now(UTC)
    with Session(engine) as db:
        for number in range(employee_count):
            eid = f"employee-{number:03}"
            db.add(
                CatalogItem(pkg_id=eid, version="1", name=eid, artifact="employee_pack")
            )
            for position in range(12):
                db.add(
                    EmployeeExecutionMetric(
                        employee_id=eid,
                        user_id=1,
                        task="任务" * 150,
                        duration_ms=position,
                        status="success" if position < 9 else "failed",
                        created_at=now - timedelta(minutes=12 - position),
                    )
                )
            db.add(
                EmployeeExecutionMetric(
                    employee_id=eid,
                    user_id=1,
                    status="success",
                    created_at=now - timedelta(days=8),
                )
            )
            for status in ("pending", "pending", "applied"):
                db.add(
                    EmployeeChangeRequest(
                        source_employee_id=eid, change_kind="test", status=status
                    )
                )
        db.add(
            CatalogItem(
                pkg_id="not-an-employee", version="1", name="mod", artifact="mod"
            )
        )
        db.commit()
    statements = []

    def count_sql(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", count_sql)
    monkeypatch.setattr(api, "get_session_factory", lambda: sessionmaker(bind=engine))
    try:
        result = api._employee_status_summary()
        assert len(statements) == (3 if employee_count else 1)
        assert len(result) == employee_count
        for number, employee in enumerate(result):
            assert employee["employee_id"] == f"employee-{number:03}"
            assert employee["runs_7d"] == 10 and employee["success_7d"] == 7
            assert (
                employee["pending_change_requests"] == 2
                and employee["health"] == "degraded"
            )
            assert employee["last_execution"]["duration_ms"] == 11
            assert len(employee["last_execution"]["task"]) == 200
    finally:
        event.remove(engine, "before_cursor_execute", count_sql)
        engine.dispose()
