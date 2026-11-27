"""Real SQLite and PostgreSQL transactions for claimed cross-module execution.

PostgreSQL runs only when XCAGI_TEST_AGENT_POSTGRES_URL is set. CI's Agent
PostgreSQL transactions job sets that URL. A missing URL skips the PostgreSQL
parameter; it does not replace these cases with an in-memory database.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine

from app.db.models.task_lifecycle import TaskLifecycleIdempotency, TaskLifecycleRecord
from tests.test_application.test_core_execution_reliability import (
    _client,
    _models,
    _post_task,
    _product_models,
    _task_body,
)


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


def _dialects():
    cases = [pytest.param("sqlite", id="sqlite")]
    if os.environ.get("XCAGI_TEST_AGENT_POSTGRES_URL", "").strip():
        cases.append(pytest.param("postgresql", id="postgresql"))
    else:
        cases.append(
            pytest.param(
                "postgresql",
                marks=pytest.mark.skip(reason="XCAGI_TEST_AGENT_POSTGRES_URL is absent"),
                id="postgresql",
            )
        )
    return cases


@contextmanager
def _execution_database(tmp_path, monkeypatch, dialect: str):
    admin = None
    schema = ""
    engine = None
    env = None
    if dialect == "postgresql":
        url = os.environ["XCAGI_TEST_AGENT_POSTGRES_URL"]
        schema = "agent_xmod_" + uuid.uuid4().hex
        admin = create_engine(url)
        with admin.begin() as db:
            db.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        engine = create_engine(
            url,
            connect_args={
                "options": (
                    f"-csearch_path={schema} -clock_timeout=3000 -cstatement_timeout=60000"
                ),
            },
        )
    try:
        env = _client(tmp_path, monkeypatch, engine=engine)
        yield env
    finally:
        if env is not None:
            env["engine"].dispose()
        elif engine is not None:
            engine.dispose()
        if admin is not None:
            with admin.begin() as db:
                db.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
            admin.dispose()


def _queue_for_execution(env, created: dict):
    run = env["runs"].get(created["data"]["run_id"])
    assert run is not None
    run.metadata["cross_module_dispatch"] = "approved"
    run.status = "queued"
    env["runs"].save(run)
    released = env["queue"].enqueue(run, requested_by="agent-task-queue", priority=1)
    assert released is not None and released.state == "queued"
    stored = env["runs"].get(run.run_id)
    assert stored is not None
    return stored


def _lifecycle_counts(env) -> tuple[int, int]:
    session = env["factory"]()
    try:
        return (
            session.query(TaskLifecycleRecord).count(),
            session.query(TaskLifecycleIdempotency).count(),
        )
    finally:
        session.close()


def _business_lifecycle(env) -> tuple[list[str], int]:
    """Import and HTTP-response rows only. The queue log is a separate module."""
    session = env["factory"]()
    try:
        modules = sorted(
            row.module
            for row in session.query(TaskLifecycleRecord).all()
            if str(row.module).startswith("cross_module_")
        )
        return modules, session.query(TaskLifecycleIdempotency).count()
    finally:
        session.close()


@pytest.mark.parametrize("takeover", [False, True])
def test_stale_cross_module_claim_cannot_reach_business_writes(tmp_path, monkeypatch, takeover):
    from app.application.agent_orchestrator.cross_module_execution import (
        execute_claimed_cross_module,
    )
    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.worker_repository import WorkerLeaseLost
    from app.db.models.agent import AgentTaskExecutionRecord

    with _execution_database(tmp_path, monkeypatch, "sqlite") as env:
        run = _queue_for_execution(env, _post_task(env, "expired-cross-module"))
        claim = env["queue"].claim("same-worker", lease_seconds=60, run_id=run.run_id)
        assert claim is not None
        with env["factory"].begin() as db:
            db.query(AgentTaskExecutionRecord).filter_by(run_id=run.run_id).update(
                {"lease_expires_at": "2000-01-01T00:00:00+00:00"}
            )
        if takeover:
            replacement = env["queue"].claim("same-worker", lease_seconds=60, run_id=run.run_id)
            assert (
                replacement is not None and replacement.execution_count == claim.execution_count + 1
            )
        before = env["queue"].get(run.run_id).to_dict()
        history = env["queue"].lifecycle(run.run_id)
        with pytest.raises(WorkerLeaseLost):
            execute_claimed_cross_module(
                AgentOrchestrator(),
                run,
                owner=claim.lease_owner,
                execution=claim,
                queue=env["queue"],
                request_id=str(run.metadata["approval_request_id"]),
                finish=True,
            )
        assert _product_models(env) == []
        assert _business_lifecycle(env) == ([], 0)
        assert env["queue"].get(run.run_id).to_dict() == before
        assert env["queue"].lifecycle(run.run_id) == history


@pytest.mark.parametrize(
    "damage",
    [
        "elt_permission",
        "product_permission",
        "owner",
        "tenant",
        "revision",
        "rows",
        "file_only",
        "errors",
    ],
)
def test_owned_import_requires_live_grants_and_exact_elt_preview(tmp_path, monkeypatch, damage):
    from copy import deepcopy

    from app.db.models.agent import AgentRunRecord
    from app.db.models.elt import EltRun, EltRunRow
    from app.db.models.permission import Role

    with _execution_database(tmp_path, monkeypatch, "sqlite") as env:
        body = deepcopy(_task_body(env, "guarded-import"))
        with env["factory"]() as db:
            preview = db.get(EltRun, body["params"]["run_id"])
            if damage in {"elt_permission", "product_permission"}:
                code = "elt.execute" if damage == "elt_permission" else "product.edit"
                role = db.query(Role).filter_by(name="admin").one()
                role.permissions = [p for p in role.permissions if p.code != code]
            elif damage == "owner":
                preview.owner_user_id += 1
            elif damage == "tenant":
                preview.tenant_id = 2
            elif damage == "revision":
                body["params"]["preview_revision"] = "0" * 64
            elif damage == "rows":
                row = db.query(EltRunRow).filter_by(run_id=preview.id, final_action="new").first()
                row.normalized_json = '{"name":"changed without approval"}'
            elif damage == "file_only":
                body["params"] = {"file_paths": [str(env["source"])]}
            else:
                body["params"]["valid_rows_only"] = False
            db.commit()
        response = env["client"].post("/api/agent/tasks", json=body)
        assert response.status_code == 400, response.text
        assert _product_models(env) == []
        assert _business_lifecycle(env) == ([], 0)
        with env["factory"]() as db:
            assert db.query(AgentRunRecord).count() == 0
            assert db.query(env["approval_model"]).count() == 0


def test_product_import_message_cannot_replace_another_admitted_tool(tmp_path, monkeypatch):
    from copy import deepcopy

    with _execution_database(tmp_path, monkeypatch, "sqlite") as env:
        body = deepcopy(_task_body(env, "unrelated-tool"))
        body.update(tool_id="business_db", action="read")
        body["params"] = {"entity": "customers", "file_path": str(env["source"])}
        response = env["client"].post("/api/agent/tasks", json=body)
        assert response.status_code == 202, response.text
        run = env["runs"].get(response.json()["data"]["run_id"])
        assert "cross_module_checkpoint" not in run.metadata["runtime_context"]
        assert "approval_request_id" not in run.metadata
        assert [(s.tool_id, s.action) for s in run.steps] == [("business_db", "read")]
        assert _product_models(env) == []
        with env["factory"]() as db:
            assert db.query(env["approval_model"]).count() == 0


@pytest.mark.parametrize("damage", ["revoked", "changed_preview"])
def test_owned_import_rechecks_authority_before_first_write(tmp_path, monkeypatch, damage):
    from app.application.agent_orchestrator.cross_module_execution import (
        execute_claimed_cross_module,
    )
    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
    from app.application.elt.errors import EltError
    from app.db.models.elt import EltRunRow
    from app.db.models.permission import Role

    with _execution_database(tmp_path, monkeypatch, "sqlite") as env:
        created = _post_task(env, "revoked-before-write")
        run = _queue_for_execution(env, created)
        assert (claim := env["queue"].claim("worker", lease_seconds=60, run_id=run.run_id))
        with env["factory"]() as db:
            if damage == "revoked":
                role = db.query(Role).filter_by(name="admin").one()
                role.permissions = [p for p in role.permissions if p.code != "product.edit"]
            else:
                preview_id = run.metadata["runtime_context"]["cross_module_checkpoint"][
                    "elt_params"
                ]["run_id"]
                row = db.query(EltRunRow).filter_by(run_id=preview_id, final_action="new").first()
                row.normalized_json = '{"name":"changed after approval"}'
            db.commit()
        with pytest.raises((ValueError, EltError)):
            execute_claimed_cross_module(
                AgentOrchestrator(),
                run,
                owner="worker",
                queue=env["queue"],
                request_id=str(run.metadata["approval_request_id"]),
                finish=True,
                execution=claim,
            )
        assert _product_models(env) == []
        assert _business_lifecycle(env) == ([], 0)
        finished = env["queue"].get(run.run_id)
        assert finished.state == "failed"
        assert finished.last_error_code == "invalid_approved_input"
        assert finished.execution_count == 1
        assert env["queue"].claim("another-worker", lease_seconds=60, run_id=run.run_id) is None


@pytest.mark.parametrize("after_commit", [False, True])
def test_unclassified_import_error_preserves_the_claim(tmp_path, monkeypatch, after_commit):
    from app.application.agent_orchestrator import cross_module_chain as chain
    from app.application.agent_orchestrator import cross_module_execution as execution
    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator

    with _execution_database(tmp_path, monkeypatch, "sqlite") as env:
        created = _post_task(env, "unclassified-import", _models("UNKNOWN"))
        run = _queue_for_execution(env, created)
        assert (claim := env["queue"].claim("worker", lease_seconds=60, run_id=run.run_id))
        error = RuntimeError("unclassified execution failure")

        def fail(*_args, **_kwargs):
            raise error

        if after_commit:
            monkeypatch.setattr(chain, "_run_employee", fail)
        else:
            monkeypatch.setattr(execution, "_execute_elt_import", fail)
        with pytest.raises(RuntimeError) as raised:
            execution.execute_claimed_cross_module(
                AgentOrchestrator(),
                run,
                owner="worker",
                queue=env["queue"],
                request_id=str(run.metadata["approval_request_id"]),
                finish=True,
                execution=claim,
            )
        assert raised.value is error
        pending = env["queue"].get(run.run_id)
        assert pending.state == "running"
        assert pending.lease_owner == "worker"
        assert pending.execution_count == 1
        assert env["queue"].claim("another-worker", lease_seconds=60, run_id=run.run_id) is None
        assert _product_models(env) == (["UNKNOWN-1", "UNKNOWN-2"] if after_commit else [])
        assert _business_lifecycle(env) == (
            (["cross_module_http_response", "cross_module_import"], 1) if after_commit else ([], 0)
        )


def test_known_import_error_keeps_open_effect_unresolved(tmp_path, monkeypatch):
    from app.application.agent_orchestrator import cross_module_execution as execution
    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
    from app.application.elt.errors import EltConflict

    with _execution_database(tmp_path, monkeypatch, "sqlite") as env:
        run = _queue_for_execution(env, _post_task(env, "unresolved-import"))
        assert (claim := env["queue"].claim("worker", lease_seconds=60, run_id=run.run_id))
        assert env["queue"].mark_open_effect(
            run.run_id, "original-write", owner_id="worker", execution_count=claim.execution_count
        )
        error = EltConflict("ELT_PREVIEW_CHANGED", "changed preview")

        def fail(*_args, **_kwargs):
            raise error

        monkeypatch.setattr(execution, "_execute_elt_import", fail)
        with pytest.raises(EltConflict) as raised:
            execution.execute_claimed_cross_module(
                AgentOrchestrator(),
                run,
                owner="worker",
                queue=env["queue"],
                request_id=str(run.metadata["approval_request_id"]),
                finish=True,
                execution=claim,
            )
        assert raised.value is error
        pending = env["queue"].get(run.run_id)
        assert pending.state == "unknown"
        assert pending.last_error_code == "needs_verification"
        assert pending.execution_count == 1
        assert not pending.finished_at
        assert env["queue"].lifecycle(run.run_id)["effects"] == ["original-write"]
        assert env["queue"].claim("another-worker", lease_seconds=60, run_id=run.run_id) is None
        assert _product_models(env) == []
        assert _business_lifecycle(env) == ([], 0)


@pytest.mark.parametrize("scenario", ["execute", "revoked", "approval_projection"])
def test_owned_import_restores_original_mod_for_execution_and_committed_receipt(
    tmp_path, monkeypatch, scenario
):
    from sqlalchemy.orm import sessionmaker
    from starlette.requests import Request

    from app import db as db_module
    from app.application.agent_orchestrator.cross_module_chain import project_rejected_approval
    from app.application.agent_orchestrator.cross_module_execution import (
        execute_claimed_cross_module,
        load_cross_module_http_result,
    )
    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
    from app.application.elt.preview_confirmation import publish_preview
    from app.db.db_base import Base
    from app.db.models.approval import ApprovalFlow
    from app.db.models.elt import EltRun, EltRunRow
    from app.db.models.user import Session as UserSession
    from app.db.models.user import User
    from app.domain.task_lifecycle.control import SessionBook
    from app.http.request_context import reset_current_http_request, set_current_http_request
    from app.infrastructure.auth.agent_mod_scope import (
        AgentModAuthorizationError,
        agent_mod_execution_scope,
        bind_agent_mod_scope,
    )
    from app.infrastructure.tenant_scope import tenant_scope
    from app.request_active_mod_ctx import (
        get_request_active_mod_id,
        reset_request_active_mod_id,
        set_request_active_mod_id,
    )
    from tests.test_application.test_core_execution_reliability import _approval_id

    with _execution_database(tmp_path, monkeypatch, "sqlite") as host:
        host_body = _task_body(host, "host-preview", _models("HOST"))
        engine = create_engine(f"sqlite:///{tmp_path / 'mod.sqlite3'}")
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        try:
            with factory.begin() as db:
                db.add(
                    User(
                        id=host["user_id"],
                        username="owner-copy",
                        password="unused",
                        tenant_id=1,
                        role="admin",
                    )
                )
            with host["factory"].begin() as db:
                db.query(UserSession).one().entitled_mod_ids_json = '["private-products"]'
                db.add(
                    host["product_model"](
                        tenant_id=1,
                        unit="host",
                        model_number="HOST-SENTINEL",
                        name="宿主原行",
                        price=7,
                    )
                )
            binding = bind_agent_mod_scope(
                session_id="sid-reliability",
                user_id=str(host["user_id"]),
                mod_id="private-products",
            )
            monkeypatch.setenv("DATABASE_URL", str(host["engine"].url))
            monkeypatch.setenv(
                "XCAGI_MOD_DATABASE_URLS", json.dumps({"private-products": str(engine.url)})
            )
            monkeypatch.setattr(db_module, "_get_test_db_manager", lambda: None)
            monkeypatch.setattr("app.db.session.SessionLocal", db_module.SessionLocal)
            monkeypatch.setattr("app.application.elt.service.SessionLocal", db_module.SessionLocal)
            mod = {**host, "factory": factory, "engine": engine, "bodies": {}}
            with agent_mod_execution_scope(binding):
                body = _task_body(mod, "mod-transaction", _models("MOD"))
            # The same authenticated owner, tenant and ELT id exist in both physical stores.
            with host["factory"]() as db, tenant_scope(1):
                old_id = host_body["params"]["run_id"]
                preview = db.get(EltRun, old_id)
                preview.id = body["params"]["run_id"]
                db.query(EltRunRow).filter_by(run_id=old_id).update({"run_id": preview.id})
                publish_preview(db, preview)
                db.commit()
            host["client"].headers["X-XCAGI-Active-Mod-Id"] = "private-products"
            created = _post_task(mod, "mod-transaction")
            run = host["runs"].get(created["data"]["run_id"])
            context = run.metadata["runtime_context"]
            checkpoint = context["cross_module_checkpoint"]
            with host["factory"].begin() as db:
                SessionBook(db).put(
                    "cross_module_http_response",
                    "1",
                    checkpoint["idempotency_key"],
                    {"body": {"sentinel": "host"}},
                )
            assert get_request_active_mod_id() == ""
            if scenario == "approval_projection":
                with host["factory"]() as db:
                    approval = db.get(host["approval_model"], _approval_id(created))
                    data = {
                        column.name: getattr(approval, column.name)
                        for column in approval.__table__.columns
                    }
                    flow = db.get(ApprovalFlow, approval.flow_id)
                    flow_data = {
                        column.name: getattr(flow, column.name) for column in flow.__table__.columns
                    }
                with factory.begin() as db:
                    db.execute(ApprovalFlow.__table__.insert().values(flow_data))
                    db.execute(
                        host["approval_model"]
                        .__table__.insert()
                        .values({**data, "status": "rejected"})
                    )
                with agent_mod_execution_scope(binding):
                    assert project_rejected_approval(run).status == "waiting_user"
                with host["factory"].begin() as db:
                    db.get(host["approval_model"], _approval_id(created)).status = "rejected"
                with factory.begin() as db:
                    db.get(host["approval_model"], _approval_id(created)).status = "pending"
                with agent_mod_execution_scope(binding):
                    assert project_rejected_approval(run).status == "rejected"
                assert host["queue"].get(run.run_id).state == "rejected"
                assert _product_models(mod) == []
            elif scenario == "revoked":
                run = _queue_for_execution(host, created)
                assert (claim := host["queue"].claim("worker", lease_seconds=60, run_id=run.run_id))
                with host["factory"].begin() as db:
                    db.query(UserSession).one().entitled_mod_ids_json = "[]"
                with pytest.raises(AgentModAuthorizationError):
                    execute_claimed_cross_module(
                        AgentOrchestrator(),
                        run,
                        owner="worker",
                        queue=host["queue"],
                        request_id=str(run.metadata["approval_request_id"]),
                        finish=True,
                        execution=claim,
                    )
                assert _product_models(mod) == []
            else:
                # Approval is a host API; its ambient request must not redirect business reads.
                request_token = set_current_http_request(
                    Request(
                        {"type": "http", "path": "/api/approval/requests/1/approve", "headers": []}
                    )
                )
                mod_token = set_request_active_mod_id("unrelated-ambient-mod")
                try:
                    approved = host["client"].post(
                        f"/api/approval/requests/{_approval_id(created)}/approve",
                        json={"opinion": "确认原预演"},
                    )
                    assert approved.status_code == 200, approved.text
                    assert approved.json()["success"] is True, approved.text
                    assert get_request_active_mod_id() == "unrelated-ambient-mod"
                finally:
                    reset_current_http_request(request_token)
                    reset_request_active_mod_id(mod_token)
                assert _product_models(mod) == ["MOD-1", "MOD-2"]
                receipt = load_cross_module_http_result(
                    "1", checkpoint["idempotency_key"], runtime_context=context
                )
                assert receipt["body"]["data"]["run_id"] == run.run_id
                assert receipt["body"]["data"]["stored_count"] == 2
                with factory() as db:
                    assert db.get(EltRun, body["params"]["run_id"]).executed_rows == 2
                    assert db.query(host["approval_model"]).count() == 0
                with host["factory"].begin() as db:
                    db.query(UserSession).one().entitled_mod_ids_json = "[]"
                with pytest.raises(AgentModAuthorizationError):
                    load_cross_module_http_result(
                        "1", checkpoint["idempotency_key"], runtime_context=context
                    )
                assert _product_models(mod) == ["MOD-1", "MOD-2"]
            assert get_request_active_mod_id() == ""
            assert _product_models(host) == ["HOST-SENTINEL"]
            with host["factory"]() as db:
                assert db.get(EltRun, body["params"]["run_id"]).executed_rows == 0
                assert SessionBook(db).get(
                    "cross_module_http_response", "1", checkpoint["idempotency_key"]
                )["body"] == {"sentinel": "host"}
        finally:
            engine.dispose()


@pytest.mark.parametrize("dialect", _dialects())
def test_concurrent_task_admission_persists_one_complete_run_and_replays_it(
    tmp_path, monkeypatch, dialect
):
    import copy

    from app.application.agent_orchestrator import AgentRun, SQLAlchemyAgentRunRepository
    from app.db.models.agent import AgentRunRecord, AgentTaskRecord

    with _execution_database(tmp_path, monkeypatch, dialect) as env:
        candidates = [
            AgentRun(user_id=str(env["user_id"]), message=f"candidate-{index}", status="queued")
            for index in range(2)
        ]
        for run in candidates:
            run.metadata["task_context"] = {"task_id": "concurrent-admission"}
            run.metadata["runtime_context"] = {"tenant_id": "1"}
        barrier = threading.Barrier(2)

        def publish(run):
            repository = SQLAlchemyAgentRunRepository(
                session_factory=env["factory"], auto_create=False
            )
            barrier.wait(timeout=10)
            return repository.create_task_run(run)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(publish, candidates))
        assert sum(created for _, created in results) == 1
        winner = next(run for run, created in results if created)
        assert all(
            run.run_id == winner.run_id and run.message == winner.message for run, _ in results
        )
        before = env["runs"].get(winner.run_id)
        assert before is not None
        assert before.message == winner.message and before.status == "queued"

        # Exact-run admission must discard both a stale snapshot and the task
        # identity tentatively inserted for it, without publishing another run.
        stale = copy.deepcopy(before)
        stale.message = "must not replace the persisted winner"
        stale.metadata["task_context"]["task_id"] = "losing-task"
        replayed, created = env["runs"].create_task_run(stale, initial_only=False)
        assert not created and replayed.to_dict() == before.to_dict()
        assert env["runs"].get(winner.run_id).to_dict() == before.to_dict()
        with env["factory"]() as db:
            assert db.query(AgentRunRecord).count() == db.query(AgentTaskRecord).count() == 1
            task = db.query(AgentTaskRecord).one()
            assert task.task_id == "concurrent-admission"
            assert task.active_run_id == winner.run_id and task.run_count == 1


@pytest.mark.parametrize("dialect", _dialects())
def test_drive_parks_when_dispatcher_already_owns_the_queue(tmp_path, monkeypatch, dialect):
    from app.application.agent_orchestrator.cross_module_execution import (
        drive_cross_module_execution,
    )
    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.task_dispatcher import (
        AgentTaskDispatcher,
        set_agent_task_dispatcher_for_tests,
    )

    with _execution_database(tmp_path, monkeypatch, dialect) as env:
        created = _post_task(env, "task-exec-park", _models("PARK"))
        run = _queue_for_execution(env, created)
        claimed = env["queue"].claim("worker-a", lease_seconds=60, run_id=run.run_id)
        assert claimed is not None and claimed.state == "running"
        assert claimed.lease_owner == "worker-a"
        dispatcher = AgentTaskDispatcher(
            execution_repository=env["queue"],
            run_repository=env["runs"],
            poll_seconds=30,
            max_workers=1,
        )
        set_agent_task_dispatcher_for_tests(dispatcher)
        dispatcher.start()
        try:
            assert dispatcher.snapshot()["running"] is True
            receipt = drive_cross_module_execution(
                AgentOrchestrator(),
                run,
                env["queue"],
                str(run.metadata["approval_request_id"]),
            )
        finally:
            dispatcher.stop(timeout=2)
        assert receipt["success"] is False
        assert receipt["execution_accepted"] is True
        assert receipt["queue_state"] == "running"
        parked = env["queue"].get(run.run_id)
        assert parked is not None
        assert parked.state == "running"
        assert parked.lease_owner == "worker-a"
        assert parked.execution_count == 1
        assert _product_models(env) == []
        assert _business_lifecycle(env) == ([], 0)


@pytest.mark.parametrize("dialect", _dialects())
def test_rejected_approval_finishes_the_claim_without_import(tmp_path, monkeypatch, dialect):
    from app.application.agent_orchestrator.cross_module_execution import (
        execute_claimed_cross_module,
    )
    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator

    with _execution_database(tmp_path, monkeypatch, dialect) as env:
        created = _post_task(env, "task-exec-reject", _models("REJX"))
        run = _queue_for_execution(env, created)
        claimed = env["queue"].claim("worker-reject", lease_seconds=60, run_id=run.run_id)
        assert claimed is not None
        run.status = "rejected"
        run.error = "不得写入"
        env["runs"].save(run)
        receipt = execute_claimed_cross_module(
            AgentOrchestrator(),
            env["runs"].get(run.run_id),
            owner="worker-reject",
            queue=env["queue"],
            request_id=str(run.metadata["approval_request_id"]),
            finish=True,
            execution=claimed,
        )
        assert receipt["success"] is False
        assert receipt["loaded_from_storage"] is True
        finished = env["queue"].get(run.run_id)
        assert finished is not None
        assert finished.state == "failed"
        assert finished.last_error_code == "approval_rejected"
        assert finished.execution_count == 1
        assert env["runs"].get(run.run_id).status == "rejected"
        assert _product_models(env) == []
        assert _business_lifecycle(env) == ([], 0)


@pytest.mark.parametrize("dialect", _dialects())
def test_http_result_persists_and_reload_ignores_a_later_body(tmp_path, monkeypatch, dialect):
    from app.application.agent_orchestrator.cross_module_execution import (
        _persist_http_result,
        load_cross_module_http_result,
    )

    with _execution_database(tmp_path, monkeypatch, dialect) as env:
        checkpoint = {
            "tenant_id": "1",
            "user_id": "7",
            "run_id": "run-exec-body",
            "task_id": "task-exec-body",
            "idempotency_key": "task-exec-body-key",
            "approval_fingerprint": "b" * 64,
        }
        body = {
            "success": True,
            "idempotency_key": checkpoint["idempotency_key"],
            "request_digest": checkpoint["approval_fingerprint"],
            "execution_status": "committed",
            "data": {"run_id": "run-exec-body", "stored_count": 2, "replayed": False},
        }
        with env["factory"].begin() as db:
            _persist_http_result(
                db,
                checkpoint,
                http_status=200,
                execution_status="committed",
                body=body,
                overwrite=False,
            )
        stored = load_cross_module_http_result("1", checkpoint["idempotency_key"])
        assert stored is not None
        assert stored["http_status"] == 200
        assert stored["execution_status"] == "committed"
        assert stored["request_digest"] == checkpoint["approval_fingerprint"]
        assert stored["body"]["data"]["stored_count"] == 2
        replaced = {
            **body,
            "data": {"run_id": "run-exec-body", "stored_count": 9, "replayed": True},
        }
        with env["factory"].begin() as db:
            _persist_http_result(
                db,
                checkpoint,
                http_status=500,
                execution_status="failed",
                body=replaced,
                overwrite=False,
            )
        again = load_cross_module_http_result("1", checkpoint["idempotency_key"])
        assert again is not None
        assert again["http_status"] == 200
        assert again["body"]["data"]["stored_count"] == 2
        assert again["body"]["data"]["replayed"] is False
        records, keys = _lifecycle_counts(env)
        assert records == 1
        assert keys == 0


@pytest.mark.parametrize("dialect", _dialects())
def test_rollback_before_commit_leaves_no_rows_and_recovery_inserts_once(
    tmp_path, monkeypatch, dialect
):
    from app.application.agent_orchestrator.cross_module_execution import (
        InjectedTransactionFault,
        execute_claimed_cross_module,
    )
    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator

    with _execution_database(tmp_path, monkeypatch, dialect) as env:
        created = _post_task(env, "task-exec-rollback", _models("ROLL"))
        run = _queue_for_execution(env, created)
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
                execution=claimed,
            )
        assert _product_models(env) == []
        assert _business_lifecycle(env) == ([], 0)
        assert env["queue"].get(run.run_id).state == "running"
        monkeypatch.delenv("XCAGI_TX_FAULT")
        recovered = env["queue"].claim(
            "worker-b",
            lease_seconds=60,
            run_id=run.run_id,
            now="2099-01-01T00:00:00+00:00",
        )
        assert recovered is not None
        assert recovered.lease_owner == "worker-b"
        assert recovered.recovery_count == 1
        receipt = execute_claimed_cross_module(
            AgentOrchestrator(),
            env["runs"].get(run.run_id),
            owner="worker-b",
            queue=env["queue"],
            request_id=str(run.metadata["approval_request_id"]),
            finish=True,
            execution=recovered,
        )
        assert receipt["success"] is True
        assert receipt["replayed"] is False
        assert receipt["stored_count"] == 2
        assert _product_models(env) == ["ROLL-1", "ROLL-2"]
        assert env["queue"].get(run.run_id).state == "succeeded"
        assert env["queue"].get(run.run_id).execution_count == 2
        assert _business_lifecycle(env) == (
            ["cross_module_http_response", "cross_module_import"],
            1,
        )


@pytest.mark.parametrize("dialect", _dialects())
def test_crash_after_commit_replays_the_stored_response(tmp_path, monkeypatch, dialect):
    from app.application.agent_orchestrator.cross_module_execution import (
        InjectedTransactionFault,
        execute_claimed_cross_module,
        load_cross_module_http_result,
    )
    from app.application.agent_orchestrator.orchestrator import AgentOrchestrator

    with _execution_database(tmp_path, monkeypatch, dialect) as env:
        created = _post_task(env, "task-exec-crash", _models("CRASH"))
        run = _queue_for_execution(env, created)
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
                execution=claimed,
            )
        assert _product_models(env) == ["CRASH-1", "CRASH-2"]
        committed_records, committed_keys = _lifecycle_counts(env)
        assert committed_records >= 1
        assert committed_keys == 1
        checkpoint = run.metadata["runtime_context"]["cross_module_checkpoint"]
        stored = load_cross_module_http_result(
            checkpoint["tenant_id"], checkpoint["idempotency_key"]
        )
        assert stored is not None
        assert stored["http_status"] == 200
        assert stored["execution_status"] == "committed"
        assert stored["request_digest"] == checkpoint["approval_fingerprint"]
        assert stored["business_result_ref"]["task_id"] == "task-exec-crash"
        assert stored["body"]["data"]["stored_count"] == 2
        assert stored["body"]["data"]["replayed"] is False
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
            execution=recovered,
        )
        assert receipt["success"] is True
        assert receipt["replayed"] is True
        assert receipt["stored_count"] == 2
        assert _product_models(env) == ["CRASH-1", "CRASH-2"]
        replayed = load_cross_module_http_result(
            checkpoint["tenant_id"], checkpoint["idempotency_key"]
        )
        assert replayed is not None
        assert replayed["body"]["data"]["replayed"] is True
        assert replayed["body"]["data"]["stored_count"] == 2
        assert _lifecycle_counts(env) == (committed_records, committed_keys)
