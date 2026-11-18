"""Dashboard SQL is independent of employee count; its rolling window stays compatible."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from modstore_server import auth_service
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

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    for model in (User, CatalogItem, EmployeeExecutionMetric, EmployeeChangeRequest):
        model.__table__.create(engine)
    now = datetime.now(UTC)
    with Session(engine) as db:
        db.add(User(id=1, username="metric-user", password_hash="test-only"))
        db.flush()
        for number in range(employee_count):
            eid = f"employee-{number:03}"
            db.add(CatalogItem(pkg_id=eid, version="1", name=eid, artifact="employee_pack"))
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
                    EmployeeChangeRequest(source_employee_id=eid, change_kind="test", status=status)
                )
        db.add(CatalogItem(pkg_id="not-an-employee", version="1", name="mod", artifact="mod"))
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
            assert employee["pending_change_requests"] == 2 and employee["health"] == "degraded"
            assert employee["last_execution"]["duration_ms"] == 11
            assert len(employee["last_execution"]["task"]) == 200
    finally:
        event.remove(engine, "before_cursor_execute", count_sql)
        engine.dispose()


@pytest.fixture
def status_client(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'status-auth.sqlite'}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    for model in (User, CatalogItem, EmployeeExecutionMetric, EmployeeChangeRequest):
        model.__table__.create(engine)
    sessions = sessionmaker(bind=engine)
    now = datetime.now(UTC)
    with sessions.begin() as db:
        db.add_all(
            [
                User(id=1, username="member", password_hash="unused", is_admin=False),
                User(id=2, username="victim", password_hash="unused", is_admin=False),
                User(id=3, username="admin", password_hash="unused", is_admin=True),
            ]
        )
        db.flush()
        db.add(
            CatalogItem(pkg_id="employee", version="1", name="employee", artifact="employee_pack")
        )
        db.add_all(
            [
                EmployeeExecutionMetric(
                    user_id=1,
                    employee_id="employee",
                    task="member-task",
                    created_at=now - timedelta(minutes=1),
                ),
                EmployeeExecutionMetric(
                    user_id=2,
                    employee_id="employee",
                    task="private-other-account-task",
                    created_at=now,
                ),
                EmployeeChangeRequest(
                    source_employee_id="employee", change_kind="test", status="pending"
                ),
            ]
        )
    monkeypatch.setattr(auth_service, "get_session_factory", lambda: sessions)
    monkeypatch.setattr(api, "get_session_factory", lambda: sessions)
    metric_reads = []

    @event.listens_for(engine, "before_cursor_execute")
    def record_reads(_conn, _cursor, statement, _params, _context, _many):
        if "employee_execution_metrics" in statement.lower():
            metric_reads.append(statement)

    app = FastAPI()
    app.include_router(api.router)
    with TestClient(app) as client:
        yield client, metric_reads
    engine.dispose()


@pytest.mark.parametrize(
    "actor,admin_claim,expected",
    [(None, False, 401), (99, False, 401), (1, False, 403), (1, True, 403)],
)
def test_global_status_rejects_nonadmins_before_reading_other_accounts(
    status_client, actor, admin_claim, expected
):
    client, metric_reads = status_client
    headers = (
        {}
        if actor is None
        else {
            "Authorization": "Bearer "
            + auth_service.create_access_token(actor, "synthetic", is_admin=admin_claim)
        }
    )
    response = client.get("/api/ops/employee-status", headers=headers)
    assert response.status_code == expected, response.text
    assert "private-other-account-task" not in response.text
    assert metric_reads == []


def test_current_admin_keeps_global_status_and_task_details(status_client):
    client, metric_reads = status_client
    response = client.get(
        "/api/ops/employee-status",
        headers={"Authorization": "Bearer " + auth_service.create_access_token(3, "admin")},
    )
    assert response.status_code == 200, response.text
    employee = response.json()["employees"][0]
    assert employee["last_execution"]["task"] == "private-other-account-task"
    assert employee["runs_7d"] == 2
    assert employee["pending_change_requests"] == 1
    assert len(metric_reads) == 1
