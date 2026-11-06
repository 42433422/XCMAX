"""Batch-1 execution reliability: queue, rejection, commit fault, idempotent body."""

from __future__ import annotations

import threading
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.db_base import Base
from app.infrastructure.tenant_scope import tenant_scope


@pytest.fixture(autouse=True)
def _reset_agent_repositories():
    from app.application.agent_orchestrator.run_repository import (
        set_agent_run_repository_for_tests,
    )
    from app.application.agent_orchestrator.task_dispatcher import (
        set_agent_task_dispatcher_for_tests,
    )
    from app.application.agent_orchestrator.task_execution_repository import (
        set_task_execution_repository_for_tests,
    )

    yield
    set_agent_run_repository_for_tests(None)
    set_task_execution_repository_for_tests(None)
    set_agent_task_dispatcher_for_tests(None)


def _models(prefix: str) -> list[list[str]]:
    return [
        ["可靠性", f"{prefix}-1", "合格一", "1件", "11.00"],
        ["可靠性", f"{prefix}-2", "合格二", "1件", "12.50"],
        ["可靠性", f"{prefix}-BAD", "", "1件", "9"],
    ]


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from app.application.agent_orchestrator.run_repository import (
        set_agent_run_repository_for_tests,
    )
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.application.agent_orchestrator.task_execution_repository import (
        set_task_execution_repository_for_tests,
    )
    from app.application.agent_orchestrator.task_execution_sql_repository import (
        SQLAlchemyTaskExecutionRepository,
    )
    from app.application.elt.service_uploads import UploadServiceMixin
    from app.db.models.approval import ApprovalRequest
    from app.db.models.product import Product
    from app.db.models.task_lifecycle import TaskLifecycleRecord
    from app.db.models.user import Session as UserSession
    from app.db.models.user import User
    from app.fastapi_routes.approval import router as approval_router
    from app.fastapi_routes.domains.agent.agent_routes import router as agent_router
    from app.middleware.industry_context import IndustryContextMiddleware
    from app.utils.time import utc_now_naive
    from tests.fixtures.cross_module_business import _build_source_workbook

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _fk_off(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.close()

    Base.metadata.create_all(engine)
    TaskLifecycleRecord.__table__.create(bind=engine, checkfirst=True)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    monkeypatch.setattr("app.db.session.SessionLocal", factory)
    monkeypatch.setattr("app.db.HostSessionLocal", factory)
    runs = SQLAlchemyAgentRunRepository(session_factory=factory)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=factory)
    set_agent_run_repository_for_tests(runs)
    set_task_execution_repository_for_tests(queue)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.delenv("XCAGI_TX_FAULT", raising=False)
    source = workspace / "source.xlsx"
    _build_source_workbook(source, rows=_models("REL"))
    db = factory()
    try:
        user = User(
            username="reliability-owner",
            password="not-a-secret",
            display_name="reliability-owner",
            role="admin",
            is_active=True,
            tenant_id=1,
            tier="enterprise",
        )
        db.add(user)
        db.flush()
        db.add(
            UserSession(
                session_id="sid-reliability",
                user_id=user.id,
                expires_at=utc_now_naive() + timedelta(days=1),
                tenant_id=1,
                account_kind="enterprise",
            )
        )
        db.commit()
        user_id = int(user.id)
    finally:
        db.close()
    app = FastAPI()
    app.add_middleware(IndustryContextMiddleware)
    app.include_router(agent_router)
    app.include_router(approval_router)
    client = TestClient(app)
    client.cookies.set("session_id", "sid-reliability")
    return {
        "client": client,
        "factory": factory,
        "queue": queue,
        "runs": runs,
        "engine": engine,
        "source": source,
        "user_id": user_id,
        "workspace": workspace,
        "upload": UploadServiceMixin,
        "approval_model": ApprovalRequest,
        "product_model": Product,
    }


def _post_task(env: dict, task_id: str, models: list[list[str]] | None = None) -> dict:
    source = env["source"]
    if models is not None:
        from tests.fixtures.cross_module_business import _build_source_workbook

        _build_source_workbook(source, rows=models)
    body = {
        "task_id": task_id,
        "title": "可靠性导入",
        "message": "处理上传的业务 Excel：识别有效表和区域，按规则切片清洗，导入产品库",
        "tool_id": "products",
        "action": "batch_create",
        "params": {
            "products": [{"name": "placeholder", "unit_price": 1}],
            "file_path": str(source),
        },
        "runtime_context": {"conversation_id": task_id, "session_id": task_id},
    }
    response = env["client"].post("/api/agent/tasks", json=body)
    assert response.status_code == 202, response.text
    return response.json()


def _product_models(env: dict) -> list[str]:
    session = env["factory"]()
    try:
        with tenant_scope(1):
            rows = (
                session.query(env["product_model"])
                .filter(env["product_model"].tenant_id == 1)
                .order_by(env["product_model"].model_number.asc())
                .all()
            )
            return [str(row.model_number) for row in rows]
    finally:
        session.close()


def _approval_id(created: dict) -> int:
    return int((created.get("data") or {}).get("metadata", {}).get("approval_request_db_id"))


def test_create_parks_a_real_queue_row_before_approval(tmp_path, monkeypatch):
    env = _client(tmp_path, monkeypatch)
    try:
        created = _post_task(env, "task-queue-before-approval")
        data = created["data"]
        assert data["status"] == "waiting_user"
        execution = created["execution"]
        assert execution["state"] == "waiting_approval"
        assert execution["execution_count"] == 0
        assert execution["requested_by"] == "agent-task-queue"
        assert execution["priority"] == 1
        history = env["queue"].lifecycle(data["run_id"])["history"]
        assert history[0]["from"] == "queued"
        assert history[0]["to"] == "waiting_approval"
        assert _product_models(env) == []
        duplicate = env["client"].post(
            "/api/agent/tasks",
            json={
                "task_id": "task-queue-before-approval",
                "title": "可靠性导入",
                "message": "处理上传的业务 Excel：识别有效表和区域，按规则切片清洗，导入产品库",
                "tool_id": "products",
                "action": "batch_create",
                "params": {
                    "products": [{"name": "placeholder", "unit_price": 1}],
                    "file_path": str(env["source"]),
                },
                "runtime_context": {
                    "conversation_id": "task-queue-before-approval",
                    "session_id": "task-queue-before-approval",
                },
            },
        )
        assert duplicate.status_code == 202
        assert duplicate.json()["deduplicated"] is True
        assert _product_models(env) == []
    finally:
        env["engine"].dispose()


def test_approval_runs_through_one_claim_and_replay_returns_the_body(tmp_path, monkeypatch):
    env = _client(tmp_path, monkeypatch)
    try:
        created = _post_task(env, "task-approve-once", _models("ONCE"))
        approved = env["client"].post(
            f"/api/approval/requests/{_approval_id(created)}/approve",
            json={"opinion": "同意导入"},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["success"] is True
        assert _product_models(env) == ["ONCE-1", "ONCE-2"]
        execution = env["queue"].get(created["data"]["run_id"])
        assert execution is not None
        assert execution.state == "succeeded"
        assert execution.execution_count == 1
        replay = env["client"].post(
            "/api/agent/tasks",
            json={
                "task_id": "task-approve-once",
                "title": "可靠性导入",
                "message": "处理上传的业务 Excel：识别有效表和区域，按规则切片清洗，导入产品库",
                "tool_id": "products",
                "action": "batch_create",
                "params": {
                    "products": [{"name": "placeholder", "unit_price": 1}],
                    "file_path": str(env["source"]),
                },
                "runtime_context": {
                    "conversation_id": "task-approve-once",
                    "session_id": "task-approve-once",
                },
            },
        )
        assert replay.status_code == 200, replay.text
        body = replay.json()
        assert body["deduplicated"] is True
        assert body["idempotent_replay"] is True
        assert body["idempotency_key"]
        assert body["request_digest"]
        assert body["execution_status"] in {"completed", "partial"}
        assert body["business_result_ref"]["run_id"] == created["data"]["run_id"]
        assert body["data"]["stored_count"] == 2
        assert env["queue"].get(created["data"]["run_id"]).execution_count == 1
        assert _product_models(env) == ["ONCE-1", "ONCE-2"]
        result = Path(body["data"]["final_output"]["business_result"]["sha256"])
        workbook = load_workbook(
            (created["data"]["metadata"]["runtime_context"]["cross_module_checkpoint"]["result_path"]),
            data_only=True,
        )
        sheet = workbook.worksheets[0]
        models = [str(row[1]) for row in sheet.iter_rows(min_row=2, values_only=True) if row[1]]
        workbook.close()
        assert models == ["ONCE-1", "ONCE-2"]
        assert result
    finally:
        env["engine"].dispose()


def test_rejection_survives_reload_and_blocks_another_write(tmp_path, monkeypatch):
    from app.application.agent_orchestrator.cross_module_chain import (
        project_rejected_approval,
        resume_cross_module_http,
    )
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.application.workflow.approval_persistence import load_workflow_snapshot_for_execution

    env = _client(tmp_path, monkeypatch)
    try:
        created = _post_task(env, "task-reject-restart", _models("REJ"))
        rejected = env["client"].post(
            f"/api/approval/requests/{_approval_id(created)}/reject",
            json={"reason": "不得写入"},
        )
        assert rejected.status_code == 200, rejected.text
        fresh = SQLAlchemyAgentRunRepository(session_factory=env["factory"], auto_create=False)
        from app.application.agent_orchestrator.run_repository import (
            set_agent_run_repository_for_tests,
        )

        set_agent_run_repository_for_tests(fresh)
        run_id = created["data"]["run_id"]
        stored = fresh.get(run_id)
        assert stored is not None and stored.status == "rejected"
        stored.status = "waiting_user"
        fresh.save(stored)
        assert fresh.get(run_id).status == "waiting_user"
        projected = project_rejected_approval(fresh.get(run_id))
        assert projected.status == "rejected"
        assert fresh.get(run_id).status == "rejected"
        task = env["client"].get("/api/agent/tasks/task-reject-restart")
        assert task.status_code == 200
        assert task.json()["data"]["status"] == "rejected"
        again = env["client"].post(
            f"/api/approval/requests/{_approval_id(created)}/approve",
            json={"opinion": "再次批准"},
        )
        assert again.status_code == 400
        session = env["factory"]()
        try:
            row = session.get(env["approval_model"], _approval_id(created))
            request_no = str(row.request_no)
        finally:
            session.close()
        with tenant_scope(1):
            snapshot = load_workflow_snapshot_for_execution(request_no)
        assert snapshot is None or resume_cross_module_http(
            snapshot, request_id=request_no, loaded_from_storage=True
        )["success"] is False
        assert _product_models(env) == []
        assert env["queue"].get(run_id).state == "rejected"
    finally:
        env["engine"].dispose()


def test_interrupted_commit_rolls_back_and_recovery_inserts_once(tmp_path, monkeypatch):
    from app.application.agent_orchestrator.cross_module_chain import (
        InjectedTransactionFault,
        execute_claimed_cross_module,
    )
    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator

    env = _client(tmp_path, monkeypatch)
    try:
        created = _post_task(env, "task-rollback", _models("ROLL"))
        run = env["runs"].get(created["data"]["run_id"])
        run.metadata["cross_module_dispatch"] = "approved"
        env["runs"].save(run)
        released = env["queue"].enqueue(run, requested_by="agent-task-queue", priority=1)
        assert released.state == "queued"
        claimed = env["queue"].claim("worker-a", lease_seconds=60, run_id=run.run_id)
        assert claimed is not None and claimed.execution_count == 1
        monkeypatch.setenv("XCAGI_TX_FAULT", "rollback_before_commit")
        with pytest.raises(InjectedTransactionFault):
            execute_claimed_cross_module(
                AgentOrchestrator(),
                run,
                owner="worker-a",
                queue=env["queue"],
                request_id=str(run.metadata["approval_request_id"]),
                finish=True,
            )
        assert _product_models(env) == []
        assert env["queue"].get(run.run_id).state == "running"
        monkeypatch.delenv("XCAGI_TX_FAULT")
        expired = env["queue"].claim(
            "worker-b",
            lease_seconds=60,
            run_id=run.run_id,
            now="2099-01-01T00:00:00+00:00",
        )
        assert expired is not None
        assert expired.lease_owner == "worker-b"
        assert expired.recovery_count == 1
        receipt = execute_claimed_cross_module(
            AgentOrchestrator(),
            env["runs"].get(run.run_id),
            owner="worker-b",
            queue=env["queue"],
            request_id=str(run.metadata["approval_request_id"]),
            finish=True,
        )
        assert receipt["success"] is True
        assert receipt["replayed"] is False
        assert _product_models(env) == ["ROLL-1", "ROLL-2"]
        finished = env["queue"].get(run.run_id)
        assert finished.state == "succeeded"
        reloaded = env["runs"].get(run.run_id)
        assert reloaded.status == "completed"
        checkpoint = reloaded.metadata["runtime_context"]["cross_module_checkpoint"]
        workbook = load_workbook(checkpoint["result_path"], data_only=True)
        models = [
            str(row[1])
            for row in workbook.worksheets[0].iter_rows(min_row=2, values_only=True)
            if row[1]
        ]
        workbook.close()
        assert models == _product_models(env)
    finally:
        monkeypatch.delenv("XCAGI_TX_FAULT", raising=False)
        env["engine"].dispose()


def test_crash_after_commit_replays_the_stored_body_without_a_second_insert(
    tmp_path, monkeypatch
):
    from app.application.agent_orchestrator.cross_module_chain import (
        InjectedTransactionFault,
        execute_claimed_cross_module,
        load_cross_module_http_result,
    )
    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator

    env = _client(tmp_path, monkeypatch)
    try:
        created = _post_task(env, "task-crash-after-commit", _models("CRASH"))
        run = env["runs"].get(created["data"]["run_id"])
        released = env["queue"].enqueue(run, requested_by="agent-task-queue", priority=1)
        assert released.state == "queued"
        claimed = env["queue"].claim("worker-a", lease_seconds=60, run_id=run.run_id)
        assert claimed is not None
        monkeypatch.setenv("XCAGI_TX_FAULT", "crash_after_commit")
        with pytest.raises(InjectedTransactionFault):
            execute_claimed_cross_module(
                AgentOrchestrator(),
                run,
                owner="worker-a",
                queue=env["queue"],
                request_id=str(run.metadata["approval_request_id"]),
                finish=True,
            )
        assert _product_models(env) == ["CRASH-1", "CRASH-2"]
        checkpoint = run.metadata["runtime_context"]["cross_module_checkpoint"]
        stored = load_cross_module_http_result(
            checkpoint["tenant_id"], checkpoint["idempotency_key"]
        )
        assert stored is not None
        assert stored["http_status"] == 200
        assert stored["execution_status"] == "committed"
        assert stored["request_digest"] == checkpoint["approval_fingerprint"]
        assert stored["business_result_ref"]["task_id"] == "task-crash-after-commit"
        monkeypatch.delenv("XCAGI_TX_FAULT")
        recovered = env["queue"].claim(
            "worker-b",
            lease_seconds=60,
            run_id=run.run_id,
            now="2099-01-01T00:00:00+00:00",
        )
        assert recovered is not None and recovered.recovery_count == 1
        receipt = execute_claimed_cross_module(
            AgentOrchestrator(),
            env["runs"].get(run.run_id),
            owner="worker-b",
            queue=env["queue"],
            request_id=str(run.metadata["approval_request_id"]),
            finish=True,
        )
        assert receipt["replayed"] is True
        assert receipt["stored_count"] == 2
        assert _product_models(env) == ["CRASH-1", "CRASH-2"]
        replay = env["client"].post(
            "/api/agent/tasks",
            json={
                "task_id": "task-crash-after-commit",
                "title": "可靠性导入",
                "message": "处理上传的业务 Excel：识别有效表和区域，按规则切片清洗，导入产品库",
                "tool_id": "products",
                "action": "batch_create",
                "params": {
                    "products": [{"name": "placeholder", "unit_price": 1}],
                    "file_path": str(env["source"]),
                },
                "runtime_context": {
                    "conversation_id": "task-crash-after-commit",
                    "session_id": "task-crash-after-commit",
                },
            },
        )
        assert replay.status_code == 200
        assert replay.json()["idempotent_replay"] is True
        assert replay.json()["data"]["stored_count"] == 2
        assert _product_models(env) == ["CRASH-1", "CRASH-2"]
    finally:
        monkeypatch.delenv("XCAGI_TX_FAULT", raising=False)
        env["engine"].dispose()


def test_two_workers_and_tenant_priority_claim_once(tmp_path, monkeypatch):
    from app.application.agent_orchestrator.cross_module_chain import (
        drive_cross_module_execution,
    )
    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_models import AgentRun

    env = _client(tmp_path, monkeypatch)
    try:
        high = AgentRun(user_id="7", message="high", status="queued")
        high.metadata["runtime_context"] = {"tenant_id": "1"}
        low = AgentRun(user_id="7", message="low", status="queued")
        low.metadata["runtime_context"] = {"tenant_id": "1"}
        other = AgentRun(user_id="8", message="other", status="queued")
        other.metadata["runtime_context"] = {"tenant_id": "2"}
        env["queue"].enqueue(low, priority=50)
        env["queue"].enqueue(high, priority=1)
        env["queue"].enqueue(other, priority=1)
        assert env["queue"].claim("tenant-2", lease_seconds=30, tenant_id="2").run_id == other.run_id
        claimed = env["queue"].claim("tenant-1", lease_seconds=30, tenant_id="1")
        assert claimed is not None and claimed.run_id == high.run_id
        assert env["queue"].claim("tenant-1-again", lease_seconds=30, tenant_id="1").run_id == low.run_id

        created = _post_task(env, "task-two-workers", _models("RACE"))
        run = env["runs"].get(created["data"]["run_id"])
        run.metadata["cross_module_dispatch"] = "approved"
        run.status = "queued"
        env["runs"].save(run)
        assert env["queue"].enqueue(run, requested_by="agent-task-queue", priority=1).state == "queued"
        errors: list[BaseException] = []
        receipts: list[dict] = []

        def worker() -> None:
            try:
                receipts.append(
                    drive_cross_module_execution(
                        AgentOrchestrator(),
                        run,
                        env["queue"],
                        str(run.metadata["approval_request_id"]),
                    )
                )
            except BaseException as exc:  # thread boundary
                errors.append(exc)

        threads = [threading.Thread(target=worker), threading.Thread(target=worker)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        assert errors == []
        assert all(not thread.is_alive() for thread in threads)
        assert _product_models(env) == ["RACE-1", "RACE-2"]
        assert env["queue"].get(run.run_id).execution_count == 1
        assert sum(bool(item.get("success")) for item in receipts) >= 1
        session = env["factory"]()
        try:
            count = session.execute(
                text("select count(*) from products where tenant_id = 1 and model_number like 'RACE-%'")
            ).scalar()
        finally:
            session.close()
        assert count == 2
    finally:
        env["engine"].dispose()


def test_cancel_releases_the_queued_task(tmp_path, monkeypatch):
    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator

    env = _client(tmp_path, monkeypatch)
    try:
        created = _post_task(env, "task-cancel-queue")
        cancelled = AgentOrchestrator().cancel_run(
            created["data"]["run_id"], requested_by="tester"
        )
        assert cancelled is not None and cancelled.status == "cancelled"
        execution = env["queue"].get(created["data"]["run_id"])
        assert execution is not None and execution.state == "cancelled"
        assert env["queue"].claim("late", lease_seconds=30, run_id=created["data"]["run_id"]) is None
        assert _product_models(env) == []
    finally:
        env["engine"].dispose()
