"""Admin employee admission reuses canonical SQL task/run identity across requests."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier, Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import SQLAlchemyAgentRunRepository
from app.application.employee_runtime import run_ledger
from app.db.models.agent import AgentRunRecord, AgentTaskRecord
from app.db.models.employee_run_log import EmployeeRunLog
from app.fastapi_routes.admin_control import employee_run
from app.fastapi_routes.admin_control.employee_backend import (
    CanonicalEmployeeBackend,
    employee_identity,
)
from app.fastapi_routes.admin_control.employee_execution import EmployeeExecution
from app.fastapi_routes.admin_control.employee_run import EmployeeRunner
from app.infrastructure.auth.agent_mod_scope import validate_actor_context
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def admin_employee(monkeypatch, trusted_actor):
    actor = trusted_actor(user_id=17, role="admin")
    factory = actor.factory
    repository = SQLAlchemyAgentRunRepository(session_factory=factory)
    repository._ensure_schema()
    engine = factory.kw["bind"]
    with engine.begin() as db:
        db.exec_driver_sql("CREATE TABLE admin_employee_effects (employee_id TEXT, run_id TEXT)")

    @contextmanager
    def database():
        with factory() as db:
            yield db

    monkeypatch.setattr(run_ledger, "get_db", database)
    monkeypatch.setattr(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        lambda: SQLAlchemyAgentRunRepository(session_factory=factory, auto_create=False),
    )
    state = SimpleNamespace(output={"success": True, "summary": "stored effect"}, error=False)

    def execute(employee_id, task, payload, **kwargs):
        context = kwargs["runtime_context"]
        assert context["user_id"] == 17 and str(context["tenant_id"]) == "7"
        assert context["run_id"].startswith("run_")
        with engine.begin() as db:
            db.exec_driver_sql(
                "INSERT INTO admin_employee_effects VALUES (?, ?)",
                (employee_id, context["run_id"]),
            )
        if state.error:
            raise RuntimeError("receipt unavailable")
        return state.output

    invocation = Mock(side_effect=execute)
    monkeypatch.setattr(
        "app.application.employee_runtime.executor.execute_employee_task_local", invocation
    )
    monkeypatch.delenv("XCAGI_AGENT_TOOL_HARD_TIMEOUT_REQUIRED", raising=False)

    def client():
        service = EmployeeExecution(
            errors=Mock(),
            identity=employee_identity,
            run=EmployeeRunner(CanonicalEmployeeBackend()).run,
        )
        app = FastAPI()
        app.add_api_route(
            "/employees/{employee_id}/execute", service.local_employee_execute, methods=["POST"]
        )
        app.add_api_route(
            "/employees/{employee_id}/runs", service.local_employee_runs, methods=["GET"]
        )
        return TestClient(app, headers=actor.headers)

    return SimpleNamespace(
        actor=actor,
        factory=factory,
        repository=repository,
        client=client,
        invocation=invocation,
        state=state,
        body={
            "task": "observe effect",
            "input_data": {"value": 1},
            "idempotency_key": "stable-request",
        },
    )


@pytest.mark.parametrize(
    "identity",
    [
        {},
        {"idempotency_key": None},
        {"idempotency_key": ""},
        {"idempotency_key": " "},
        {"idempotency_key": 1},
        {"idempotency_key": "x" * 161},
        {"idempotency_key": "one", "turn_id": "another"},
        {"input_data": {"idempotency_key": "untrusted-nested-key"}},
    ],
)
def test_admin_missing_or_invalid_request_key_creates_no_run_or_effect(admin_employee, identity):
    entry = admin_employee
    with entry.client() as client:
        response = client.post("/employees/clerk/execute", json={"task": "write", **identity})
    assert response.status_code == 400, response.text
    assert response.json()["error_code"] == "task_identity_required"
    assert response.json()["execution_state"] == "not_started"
    assert response.json()["success"] is response.json()["retryable"] is False
    entry.invocation.assert_not_called()
    with entry.factory() as db:
        assert db.query(AgentRunRecord).count() == db.query(AgentTaskRecord).count() == 0
        assert db.query(EmployeeRunLog).count() == 0
        assert (
            db.connection().exec_driver_sql("SELECT count(*) FROM admin_employee_effects").scalar()
            == 0
        )


@pytest.mark.parametrize("source", ["header", "turn_id"])
def test_admin_key_sources_enter_same_authenticated_admission(admin_employee, source):
    entry = admin_employee
    body = {"task": "observe effect"}
    headers = {}
    if source == "header":
        headers["Idempotency-Key"] = "same-key"
    else:
        body["turn_id"] = "same-key"
    with entry.client() as client:
        first = client.post("/employees/clerk/execute", json=body, headers=headers)
        replay = client.post("/employees/clerk/execute", json=body, headers=headers)
    assert first.status_code == replay.status_code == 200
    assert first.json()["run_id"] == replay.json()["run_id"]
    assert replay.json()["deduplicated"] is True and replay.json()["success"] is False
    assert replay.json()["execution_state"] == "unknown"
    context = entry.repository.get(first.json()["run_id"]).metadata["runtime_context"]
    assert validate_actor_context(context) is None
    assert context["_actor_authorization"]["session_row_id"] == entry.actor.session_row_id
    assert context["user_id"] == str(entry.actor.user_id)
    entry.invocation.assert_called_once()


def test_concurrent_admin_requests_execute_once_and_reopen_original_receipt(
    admin_employee, monkeypatch
):
    entry = admin_employee
    barrier = Barrier(2)
    publish = employee_run.publish_task_run

    def competing_publish(**kwargs):
        barrier.wait(timeout=10)
        return publish(**kwargs)

    monkeypatch.setattr(employee_run, "publish_task_run", competing_publish)

    def send(_):
        with entry.client() as client:
            return client.post("/employees/clerk/execute", json=entry.body)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(send, range(2)))
    assert [response.status_code for response in responses] == [200, 200], [
        r.text for r in responses
    ]
    assert len({response.json()["run_id"] for response in responses}) == 1
    assert sum(response.json()["deduplicated"] for response in responses) == 1
    monkeypatch.setattr(employee_run, "publish_task_run", publish)
    with entry.client() as client:
        replay = client.post("/employees/clerk/execute", json=entry.body).json()
        read = client.get(
            "/employees/clerk/runs", params={"idempotency_key": "stable-request"}
        ).json()
    assert replay == read
    assert read["execution_state"] == "unknown" and read["success"] is False
    assert read["requires_reconciliation"] is True and read["retryable"] is False
    assert read["verification"]["code"] == "result_verifier_unavailable"
    assert isinstance(read["employee_run_id"], int)
    assert read["agent_run_id"] == responses[0].json()["run_id"]
    assert entry.invocation.call_count == 1
    with entry.factory() as db:
        assert db.query(AgentRunRecord).count() == db.query(AgentTaskRecord).count() == 1
        assert db.query(EmployeeRunLog).count() == 1
        assert (
            db.connection().exec_driver_sql("SELECT count(*) FROM admin_employee_effects").scalar()
            == 1
        )


def test_admin_marker_collision_rejects_generic_task_without_mutation(admin_employee, monkeypatch):
    from app.application.agent_orchestrator import AgentRun
    from app.application.agent_orchestrator.approval_grant import authorization_scope_hash
    from app.application.agent_orchestrator.run_models import AgentStep, ToolCall
    from app.application.agent_orchestrator.task_context import apply_task_context

    entry = admin_employee
    publish = employee_run.publish_task_run
    original = {}

    def publish_after_generic_collision(**kwargs):
        context = {**kwargs["runtime_context"], "source": "unified_task_api"}
        generic = AgentRun(
            user_id=kwargs["run"].user_id, message="original generic task", status="running"
        )
        generic.metadata["runtime_context"] = context
        generic.metadata["execution_authorization_scope"] = authorization_scope_hash(context)
        apply_task_context(generic, context)
        step = AgentStep(
            "employee", "employee", "execute", params=kwargs["params"], status="running"
        )
        generic.steps = [step]
        generic.tool_calls = [
            ToolCall(step.step_id, step.node_id, step.tool_id, step.action, params=step.params)
        ]
        created = publish(**{**kwargs, "run": generic, "runtime_context": context})
        assert not created.deduplicated
        original["run"] = entry.repository.get(generic.run_id).to_dict()
        original["task"] = entry.repository.get_task(
            user_id=generic.user_id, tenant_id="7", task_id=context["task_id"]
        ).to_dict()
        result = publish(**kwargs)
        assert result.deduplicated
        assert (
            result.run.metadata["task_request_fingerprint"]
            == kwargs["run"].metadata["task_request_fingerprint"]
        )
        return result

    monkeypatch.setattr(employee_run, "publish_task_run", publish_after_generic_collision)
    with entry.client() as client:
        response = client.post("/employees/clerk/execute", json=entry.body)
        read = client.get("/employees/clerk/runs", params={"idempotency_key": "stable-request"})
    assert response.status_code == read.status_code == 409
    assert entry.invocation.call_count == 0
    assert entry.repository.get(original["run"]["run_id"]).to_dict() == original["run"]
    assert (
        entry.repository.get_task(
            user_id="17", tenant_id="7", task_id=original["task"]["task_id"]
        ).to_dict()
        == original["task"]
    )
    with entry.factory() as db:
        assert db.query(AgentRunRecord).count() == db.query(AgentTaskRecord).count() == 1
        assert db.query(EmployeeRunLog).count() == 0
        assert (
            db.connection().exec_driver_sql("SELECT count(*) FROM admin_employee_effects").scalar()
            == 0
        )


@pytest.mark.parametrize("change", ["employee", "task", "input", "approval"])
def test_admin_request_key_rejects_changed_execution(admin_employee, change):
    entry = admin_employee
    with entry.client() as client:
        assert client.post("/employees/clerk/execute", json=entry.body).status_code == 200
        body, employee = dict(entry.body), "clerk"
        if change == "employee":
            employee = "other-clerk"
        elif change == "task":
            body["task"] = "different action"
        elif change == "input":
            body["input_data"] = {"value": 2}
        else:
            body["approval_token"] = "different-token"
        response = client.post(f"/employees/{employee}/execute", json=body)
    assert response.status_code == 409, response.text
    assert entry.invocation.call_count == 1


@pytest.mark.parametrize(
    "state", ["queued", "waiting_approval", "waiting_input", "paused", "blocked", "unknown"]
)
def test_admin_pending_receipt_is_not_reexecuted_or_completed(admin_employee, state):
    entry = admin_employee
    entry.state.output = {"success": True, "summary": "pending", "execution_state": state}
    with entry.client() as client:
        first = client.post("/employees/clerk/execute", json=entry.body).json()
        repeated = client.post("/employees/clerk/execute", json=entry.body).json()
        read = client.get(
            "/employees/clerk/runs", params={"idempotency_key": "stable-request"}
        ).json()
    assert not first["success"] and not repeated["success"] and not read["success"]
    assert first["run_id"] == repeated["run_id"] == read["run_id"]
    assert read["execution_state"] == state, read
    assert entry.invocation.call_count == 1
    run = entry.repository.get(first["run_id"])
    assert run.tool_calls[0].status == "running" and not run.tool_calls[0].finished_at
    assert not run.steps[0].finished_at


def test_admin_unknown_exception_and_missing_key_read_never_dispatch(admin_employee):
    entry = admin_employee
    entry.state.error = True
    with entry.client() as client:
        missing = client.get("/employees/clerk/runs", params={"idempotency_key": "missing"})
        assert missing.status_code == 404 and entry.invocation.call_count == 0
        first = client.post("/employees/clerk/execute", json=entry.body).json()
        repeated = client.post("/employees/clerk/execute", json=entry.body).json()
    assert first["execution_state"] == repeated["execution_state"] == "unknown"
    assert first["run_id"] == repeated["run_id"]
    assert entry.invocation.call_count == 1


def test_admin_read_is_owner_tenant_mod_scoped_and_runtime_input_is_untrusted(
    admin_employee, trusted_actor
):
    entry = admin_employee
    forged = {
        **entry.body,
        "input_data": {"value": 1, "mod_id": "forged", "runtime_context": {"tenant_id": 999}},
    }
    with entry.client() as client:
        first = client.post("/employees/clerk/execute", json=forged)
        assert first.status_code == 200, first.text
        assert (
            client.post("/employees/clerk/execute", json=entry.body).json()["run_id"]
            == first.json()["run_id"]
        )
        for actor in (
            trusted_actor(user_id=18, role="admin"),
            trusted_actor(user_id=19, tenant_id=8, role="admin"),
        ):
            response = client.get(
                "/employees/clerk/runs",
                params={"idempotency_key": "stable-request"},
                headers=actor.headers,
            )
            assert response.status_code == 404, response.text
        mod_actor = trusted_actor(user_id=17, role="admin", mod_id="different-mod")
        response = client.post(
            "/employees/clerk/execute", json=entry.body, headers=mod_actor.headers
        )
        assert response.status_code == 409, response.text
        with entry.factory.begin() as db:
            db.query(AgentRunRecord).filter_by(run_id=first.json()["run_id"]).delete()
        for headers in (entry.actor.headers, mod_actor.headers):
            missing = client.get(
                "/employees/clerk/runs",
                params={"idempotency_key": "stable-request"},
                headers=headers,
            )
            assert missing.status_code == 404 and missing.json()["execution_state"] == "unknown"
            assert "run_id" not in missing.json()
    assert entry.invocation.call_count == 1


@pytest.mark.parametrize(
    "outcome",
    [
        "completed",
        "failed",
        "missing",
        "foreign_parent",
        "foreign_mod",
        "manual",
        "interrupted",
        "extra_effect",
        "other_child",
        "cas_lost",
    ],
)
def test_admin_reads_current_exact_child_receipt_without_reexecution(
    admin_employee, outcome, monkeypatch
):
    from app.application.agent_orchestrator import AgentRun
    from app.application.agent_orchestrator.task_context import apply_task_context

    entry = admin_employee

    def delegate(employee_id, task, payload, **kwargs):
        context = dict(kwargs["runtime_context"])
        child = AgentRun(user_id="17", message="delegated original", status="running")
        context.update(parent_run_id=context["run_id"], task_id="child-task")
        child.metadata["runtime_context"] = context
        apply_task_context(child, context)
        entry.repository.save(child)
        return {
            "success": True,
            "summary": "accepted",
            "execution_state": "queued",
            "agent_run_id": child.run_id,
        }

    entry.invocation.side_effect = delegate
    with entry.client() as client:
        first = client.post("/employees/clerk/execute", json=entry.body).json()
        child = entry.repository.get(first["child_run_id"])
        assert first["success"] is False
        if outcome == "missing":
            with entry.factory.begin() as db:
                db.query(AgentRunRecord).filter_by(run_id=child.run_id).delete()
        else:
            child.status = "failed" if outcome == "failed" else "completed"
            child.final_output = {
                "response": "original child result",
                "success": outcome != "failed",
            }
            if outcome == "foreign_parent":
                child.metadata["runtime_context"]["parent_run_id"] = "unrelated"
            if outcome == "foreign_mod":
                child.metadata["runtime_context"]["mod_id"] = "unrelated"
            entry.repository.save(child)
        if outcome in {"manual", "interrupted", "extra_effect", "other_child"}:
            parent = entry.repository.get(first["run_id"])
            if outcome == "manual":
                parent.metadata["recovery"] = {"state": "manual_reconciliation_required"}
            elif outcome == "interrupted":
                parent.metadata["stream_interruption"] = {"outcome": "unknown"}
            elif outcome == "extra_effect":
                from app.application.agent_orchestrator.run_models import ToolCall

                parent.tool_calls.append(ToolCall("extra", "extra", "write", "apply"))
            else:
                from app.application.agent_orchestrator.run_audit_scope import attach_child_result

                other = AgentRun(user_id="17", message="another child", status="running")
                other.metadata["runtime_context"] = {
                    **parent.metadata["runtime_context"],
                    "parent_run_id": parent.run_id,
                    "task_id": "other-child-task",
                }
                apply_task_context(other, other.metadata["runtime_context"])
                entry.repository.save(other)
                assert attach_child_result(parent, other)
            entry.repository.save(parent)
        if outcome == "cas_lost":

            def competing_write(repository, proposed, previous):
                current = entry.repository.get(previous.run_id)
                current.add_event("audit.note", "concurrent writer retained the current parent")
                entry.repository.save(current)
                return False

            monkeypatch.setattr(SQLAlchemyAgentRunRepository, "save_if_unchanged", competing_write)
        read = client.get(
            "/employees/clerk/runs", params={"idempotency_key": "stable-request"}
        ).json()
        replay = client.post("/employees/clerk/execute", json=entry.body).json()
    expected = (
        outcome
        if outcome in {"completed", "failed"}
        else "running"
        if outcome == "cas_lost"
        else "unknown"
    )
    assert read["execution_state"] == replay["execution_state"] == expected, read
    assert read["run_id"] == first["run_id"]
    assert read["child_run_id"] == child.run_id
    assert read["success"] is (expected == "completed")
    assert entry.invocation.call_count == 1
    parent = entry.repository.get(first["run_id"])
    task = entry.repository.get_task(user_id="17", tenant_id="7", task_id=first["task_id"])
    assert parent.status == task.status == (expected if expected != "unknown" else "blocked")
    if expected == "unknown":
        assert parent.metadata["recovery"]["state"] == "manual_reconciliation_required"
    else:
        assert parent.final_output["admin_employee_receipt"]["execution_state"] == expected


def test_admin_abandoned_admission_becomes_unknown_only_after_original_budget(
    admin_employee, monkeypatch
):
    from app.fastapi_routes.admin_control.employee_run import EmployeeWork

    entry = admin_employee
    work = EmployeeWork(
        "clerk",
        "work",
        {},
        17,
        7,
        entry.actor.session_id,
        entry.actor.context["workspace_root"],
        "abandoned",
        dict(entry.actor.context),
    )

    class ProcessStopped(BaseException):
        pass

    def stop(_):
        raise ProcessStopped

    with pytest.raises(ProcessStopped):
        employee_run.execute_admitted_employee(work, stop)
    before = employee_run.read_employee_receipt("clerk", "abandoned", entry.actor.context)
    assert before["execution_state"] == "running"
    monkeypatch.setattr(employee_run, "utc_now_iso", lambda: "2999-01-01T00:00:00+00:00")
    after = employee_run.read_employee_receipt("clerk", "abandoned", entry.actor.context)
    assert after["run_id"] == before["run_id"] and after["execution_state"] == "unknown"
    assert after["requires_reconciliation"] is True and after["retryable"] is False
    canonical = entry.repository.get(after["run_id"])
    assert canonical.status == "blocked"
    assert canonical.metadata["recovery"]["state"] == "manual_reconciliation_required"
    assert (
        entry.repository.get_task(user_id="17", tenant_id="7", task_id=after["task_id"]).status
        == "blocked"
    )
    assert entry.invocation.call_count == 0  # Receipt CAS never dispatches employee work.


@pytest.mark.parametrize("child_state", ["missing", "running", "unknown"])
def test_admin_first_claimed_success_requires_original_child_evidence(admin_employee, child_state):
    from app.application.agent_orchestrator import AgentRun
    from app.application.agent_orchestrator.task_context import apply_task_context

    entry = admin_employee

    def delegate(employee_id, task, payload, **kwargs):
        context = dict(kwargs["runtime_context"])
        child = AgentRun(
            user_id="17",
            message="original child",
            status="running" if child_state == "running" else "completed",
        )
        context.update(parent_run_id=context["run_id"], task_id="initial-child-task")
        child.metadata["runtime_context"] = context
        apply_task_context(child, context)
        if child_state == "unknown":
            child.final_output = {"success": False, "requires_reconciliation": True}
        if child_state != "missing":
            entry.repository.save(child)
        return {
            "success": True,
            "execution_state": "completed",
            "agent_run_id": child.run_id,
            "summary": "claimed child completion",
        }

    entry.invocation.side_effect = delegate
    with entry.client() as client:
        response = client.post("/employees/clerk/execute", json=entry.body).json()
    expected = "running" if child_state == "running" else "unknown"
    assert response["execution_state"] == expected and response["success"] is False
    parent = entry.repository.get(response["run_id"])
    task = entry.repository.get_task(user_id="17", tenant_id="7", task_id=response["task_id"])
    assert parent.status == task.status == ("running" if expected == "running" else "blocked")
    assert entry.invocation.call_count == 1
