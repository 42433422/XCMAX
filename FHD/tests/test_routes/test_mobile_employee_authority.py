"""Authenticated adapters retain real session authority through local execution."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["user", "operator"])
async def test_mobile_route_denies_host_employee_before_agent(trusted_actor, monkeypatch, role):
    from app.application.employee_runtime.agent import EmployeeAgent
    from app.fastapi_routes.mobile_extensions.backends import execute_employee
    from app.fastapi_routes.mobile_extensions.routes_employee_chat import (
        EmployeeChatRoutes,
        EmployeeChatRoutesPorts,
    )

    actor = trusted_actor(role=role)
    run = MagicMock(side_effect=AssertionError("host employee must not execute"))
    monkeypatch.setattr(EmployeeAgent, "run", run)
    observed = []

    def execute(*args, **kwargs):
        result = execute_employee(*args, **kwargs)
        observed.append(result)
        return result

    routes = EmployeeChatRoutes(
        EmployeeChatRoutesPorts(
            extract_employee_failure_text=lambda r: "",
            chunk_employee_reply=lambda s: [s],
            extract_employee_reply_text=lambda r: json.dumps(r),
            sse_line=lambda p: json.dumps(p).encode(),
            execute_employee=execute,
        ),
        lambda: None,
    )
    response = await routes.mobile_employee_chat_stream(
        "artifact-generator",
        actor.request,
        SimpleNamespace(id=actor.user_id),
        {"message": "host operation", "role": "admin", "runtime_context": {"role": "admin"}},
    )
    async for _ in response.body_iterator:
        pass
    assert observed[0]["error_code"] == "employee_host_admin_required"
    run.assert_not_called()


@pytest.mark.parametrize("scope", ["missing", "wrong_user", "trusted"])
def test_default_group_executor_requires_bound_actor(trusted_actor, monkeypatch, scope):
    from app.application.employee_runtime.agent import EmployeeAgent
    from app.application.group_chat.employee_registry import _default_employee_executor

    actor = trusted_actor()
    run = MagicMock(side_effect=AssertionError("host employee must not execute"))
    monkeypatch.setattr(EmployeeAgent, "run", run)
    context = actor.context if scope != "missing" else None
    result = _default_employee_executor(
        "artifact-generator",
        "task",
        {
            "handler": "specialized",
            "tool": "sandbox_python",
            "params": {"code": "print(1)", "confirm": True},
        },
        actor.user_id + (1 if scope == "wrong_user" else 0),
        runtime_context=context,
    )
    assert result["error_code"] == (
        "employee_host_admin_required" if scope == "trusted" else "tool_identity_required"
    )
    run.assert_not_called()


@pytest.mark.asyncio
async def test_group_post_binds_request_not_body(trusted_actor, monkeypatch, tmp_path):
    from app.application.ai_group_chat_service import AiGroupChatService
    from app.application.employee_runtime.agent import EmployeeAgent
    from app.fastapi_routes.mobile_extensions.models import AiGroupMessageBody
    from app.fastapi_routes.mobile_extensions.routes_ai_groups import GroupRoutes, GroupRoutesPorts

    actor = trusted_actor()
    observed = []
    run = MagicMock(side_effect=AssertionError("host employee must not execute"))
    monkeypatch.setattr(EmployeeAgent, "run", run)

    async def post(self, **kwargs):
        result = self._employee_executor_fn("artifact-generator", "task", {}, kwargs["user_id"])
        observed.append(result)
        return result

    monkeypatch.setattr(AiGroupChatService, "post_message", post)
    routes = GroupRoutes(
        GroupRoutesPorts(
            mobile_request_user_id=lambda r, u: actor.user_id,
            mobile_session_meta=lambda r: {},
            require_mobile_admin_or_enterprise=lambda r, u: (u, None),
            ai_group_service=lambda **kw: AiGroupChatService(storage_root=tmp_path, **kw),
            mobile_group_mode=lambda r: "enterprise",
            mobile_group_uid=lambda r, u: actor.user_id,
        ),
        lambda: None,
    )
    await routes.mobile_ai_group_post(
        actor.request,
        "group",
        AiGroupMessageBody(message="task", context={"_actor_authorization": {"role": "admin"}}),
        SimpleNamespace(id=actor.user_id),
    )
    assert observed[0]["error_code"] == "employee_host_admin_required"
    run.assert_not_called()


@pytest.fixture
def group_reader(trusted_actor, monkeypatch, tmp_path):
    from contextlib import contextmanager
    from io import BytesIO

    from app.application.agent_orchestrator import SQLAlchemyAgentRunRepository
    from app.application.ai_group_chat_service import AiGroupChatService
    from app.application.elt.service import get_elt_service
    from app.application.employee_runtime.agent import EmployeeAgent
    from app.application.group_chat.employee_registry import _default_employee_executor
    from app.infrastructure.tenant_scope import tenant_scope
    from app.request_active_mod_ctx import set_request_active_mod_id

    set_request_active_mod_id(None)
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "group-office-reader-test-secret")
    monkeypatch.delenv("XCAGI_MOD_ISOLATED_DATABASES", raising=False)
    owner, other = trusted_actor(), trusted_actor()
    repository = SQLAlchemyAgentRunRepository(session_factory=owner.factory)
    repository._ensure_schema()
    for module in ("orchestrator", "run_repository"):
        monkeypatch.setattr(
            f"app.application.agent_orchestrator.{module}.get_agent_run_repository",
            lambda: SQLAlchemyAgentRunRepository(session_factory=owner.factory, auto_create=False),
        )
    with tenant_scope(owner.tenant_id), owner.factory.begin() as db:
        upload = get_elt_service().save_upload(
            db,
            owner_user_id=owner.user_id,
            file_name="orders.csv",
            content_type="text/csv",
            stream=BytesIO(b"amount\n20\n"),
        )
    with tenant_scope(owner.tenant_id):
        groups = AiGroupChatService(
            storage_root=tmp_path / "groups",
            runtime_context=owner.context,
            department_loader=lambda: {},
            employee_loader=lambda: [],
        )
        group = groups.create_group(user_id=owner.user_id, name="文档复核")
        work_order = groups._message_row(
            user_id=owner.user_id,
            group_id=group["id"],
            role="ai",
            sender_id="ai-group-dispatcher",
            sender_name="工作流调度",
            sender_avatar="",
            body="读取已上传 CSV",
            kind="work_order",
            status="assigned",
            work_order_id="original-office-order",
            payload={"task": "read", "target_employee_ids": ["csv-full-read-employee"]},
        )
        groups._append_messages([work_order])

    @contextmanager
    def same_database():
        db = owner.factory()
        try:
            yield db
            db.commit()
        finally:
            db.close()

    monkeypatch.setattr(
        "app.application.tools.workflow_spreadsheet_scope.get_db",
        same_database,
    )
    seen = []
    original_run = EmployeeAgent.run

    def run(self, task, payload, **kwargs):
        from pathlib import Path

        seen.append((Path(payload["file_path"]).read_bytes(), dict(kwargs["runtime_context"])))
        return original_run(self, task, payload, **kwargs)

    monkeypatch.setattr(EmployeeAgent, "run", run)
    params = {
        "upload_id": upload["upload_id"],
        "group_id": group["id"],
        "work_order_id": work_order["work_order_id"],
    }

    def execute(actor=owner, **changes):
        with tenant_scope(actor.tenant_id):
            return _default_employee_executor(
                "csv-full-read-employee",
                "read",
                {**params, **changes},
                actor.user_id,
                runtime_context=actor.context,
            )

    return SimpleNamespace(
        owner=owner, other=other, repository=repository, execute=execute, seen=seen, params=params
    )


def test_group_office_upload_requires_actual_owner(group_reader):
    import hashlib

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator.artifact_files import read_verified_run_file
    from app.application.agent_orchestrator.business_action_ledger import canonical_hash
    from app.fastapi_routes.domains.agent.artifact_routes import download_agent_artifact
    from app.infrastructure.tenant_scope import tenant_scope

    case = group_reader
    app = FastAPI()
    app.add_api_route(
        "/api/agent/runs/{run_id}/artifacts/{artifact_id}",
        download_agent_artifact,
        methods=["GET"],
    )
    for actor, allowed in ((case.owner, True), (case.other, False)):
        result = case.execute(actor)
        assert result["success"] is allowed, result
        if not allowed:
            assert result["error_code"] == "employee_file_access_denied"
            continue
        with tenant_scope(actor.tenant_id):
            stored = case.repository.get(result["run_id"])
            assert stored is not None and stored.status == "completed"
            [call] = stored.tool_calls
            [receipt] = result["artifacts"]
            assert (
                result["file_path"]
                == receipt["uri"]
                == (f"/api/agent/runs/{stored.run_id}/artifacts/{receipt['artifact_id']}")
            )
            expected = {
                "run_id": stored.run_id,
                "owner_user_id": str(actor.user_id),
                "tenant_id": str(actor.tenant_id),
                "step_id": call.step_id,
                "node_id": call.node_id,
                "call_id": call.call_id,
                "params_sha256": canonical_hash(call.params),
            }
            assert {key: receipt["metadata"][key] for key in expected} == expected
            parsed = json.loads(read_verified_run_file(stored.run_id, receipt))
            assert parsed["rows"] == [{"amount": "20"}] and parsed["row_count"] == 1
            with TestClient(app) as client:
                downloaded = client.get(receipt["uri"], headers=actor.headers)
                assert downloaded.status_code == 200, downloaded.text
                assert downloaded.json() == parsed
                assert (
                    hashlib.sha256(downloaded.content).hexdigest() == receipt["metadata"]["sha256"]
                )
                assert client.get(receipt["uri"], headers=case.other.headers).status_code == 403
            saved_context = stored.metadata["runtime_context"]
            assert saved_context["_actor_authorization"] == actor.context["_actor_authorization"]
            assert saved_context["source"] == "ai_group_chat"
            assert saved_context["group_id"] == case.params["group_id"]
            assert saved_context["work_order_id"] == case.params["work_order_id"]
            assert stored.run_id not in (case.params["group_id"], case.params["work_order_id"])
            replay = case.execute(actor)
            assert replay["success"] and replay["deduplicated"]
            assert replay["run_id"] == result["run_id"] and replay["artifacts"] == [receipt]
            reopened = case.repository.get(result["run_id"])
            assert reopened is not None
            assert [item.artifact_id for item in reopened.artifacts] == [receipt["artifact_id"]]
    assert [raw for raw, _ in case.seen] == [b"amount\n20\n"]


def test_group_reader_rejects_changed_input_and_revoked_session(group_reader):
    from app.db.models.user import Session

    case = group_reader
    original = case.execute()
    changed = case.execute(upload_id="different-upload")
    assert original["success"] is True
    assert changed["success"] is False
    assert changed["error_code"] == "execution_idempotency_conflict"
    with case.owner.factory.begin() as db:
        db.delete(db.get(Session, case.owner.session_row_id))
    revoked = case.execute()
    assert revoked["success"] is False and revoked["error_code"] == "tool_identity_required"
    assert len(case.seen) == 1


@pytest.mark.parametrize("missing", ["group_id", "work_order_id"])
def test_group_reader_requires_original_work_identity(group_reader, missing):
    from app.db.models.agent import AgentRunRecord

    case = group_reader
    result = case.execute(**{missing: ""})
    assert result["error_code"] == "task_identity_required" and result["retryable"] is False
    assert not case.seen
    with case.owner.factory() as db:
        assert db.query(AgentRunRecord).count() == 0


@pytest.mark.parametrize("interruption", ["cancelled", "unknown"])
def test_group_reader_replay_does_not_repeat_cancelled_or_unknown_call(
    group_reader, monkeypatch, interruption
):
    from app.application.admin_control import employee_run
    from app.application.employee_runtime import executor

    case = group_reader
    if interruption == "cancelled":
        publish = employee_run.publish_task_run

        def cancel_after_admission(**kwargs):
            publication = publish(**kwargs)
            if not publication.deduplicated:
                kwargs["orchestrator"].cancel_run(publication.run.run_id, requested_by="user")
            return publication

        monkeypatch.setattr(employee_run, "publish_task_run", cancel_after_admission)
    else:
        execute = executor.execute_employee_task_local

        def lose_response(*args, **kwargs):
            result = execute(*args, **kwargs)
            assert result["success"] and result["artifacts"]
            raise RuntimeError("reader output published; caller response interrupted")

        monkeypatch.setattr(executor, "execute_employee_task_local", lose_response)
    first, replay = case.execute(), case.execute()
    assert first["success"] is replay["success"] is False
    assert first["execution_state"] == replay["execution_state"] == interruption
    assert first["run_id"] == replay["run_id"] and replay["deduplicated"] is True
    assert first["retryable"] is replay["retryable"] is False
    assert len(case.seen) == (0 if interruption == "cancelled" else 1)


@pytest.mark.parametrize("drift", ["owner", "call", "uri", "bytes"])
def test_admission_does_not_register_an_invalid_published_file(group_reader, monkeypatch, drift):
    from app.application.agent_orchestrator.artifact_files import artifact_path
    from app.application.employee_runtime import executor
    from app.infrastructure.tenant_scope import tenant_scope

    case = group_reader
    execute = executor.execute_employee_task_local

    def corrupt_receipt_after_real_publication(*args, **kwargs):
        result = execute(*args, **kwargs)
        assert result["success"] is True
        [receipt] = result["artifacts"]
        if drift == "owner":
            receipt["metadata"]["owner_user_id"] = str(case.other.user_id)
        elif drift == "call":
            receipt["metadata"]["call_id"] = "another-call"
        elif drift == "uri":
            receipt["uri"] = "/api/agent/runs/another-run/artifacts/another-artifact"
        else:
            artifact_path(kwargs["runtime_context"]["run_id"], receipt["artifact_id"]).write_bytes(
                b'{"corrupted":true}'
            )
        return result

    monkeypatch.setattr(
        executor, "execute_employee_task_local", corrupt_receipt_after_real_publication
    )
    first, replay = case.execute(), case.execute()
    assert first["success"] is replay["success"] is False
    assert first["execution_state"] == replay["execution_state"] == "unknown"
    assert first["requires_reconciliation"] is replay["requires_reconciliation"] is True
    assert first["run_id"] == replay["run_id"] and replay["deduplicated"] is True
    assert not first.get("artifacts") and not replay.get("artifacts")
    with tenant_scope(case.owner.tenant_id):
        stored = case.repository.get(first["run_id"])
        assert stored is not None and stored.status == "blocked" and stored.artifacts == []
        assert stored.final_output["admin_employee_receipt"]["success"] is False
    assert len(case.seen) == 1


def test_late_reader_receipt_does_not_overwrite_cancelled_run(group_reader, monkeypatch):
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.artifact_files import read_verified_run_file
    from app.application.employee_runtime import executor
    from app.infrastructure.tenant_scope import tenant_scope

    case = group_reader
    execute = executor.execute_employee_task_local
    cancelled_snapshots = []

    def cancel_after_actual_file_publication(*args, **kwargs):
        result = execute(*args, **kwargs)
        assert result["success"] is True
        run_id = kwargs["runtime_context"]["run_id"]
        [receipt] = result["artifacts"]
        assert json.loads(read_verified_run_file(run_id, receipt))["rows"] == [{"amount": "20"}]
        cancelled = AgentOrchestrator().cancel_run(run_id, requested_by=str(case.owner.user_id))
        assert cancelled is not None and cancelled.status == "cancelled"
        cancelled_snapshots.append(cancelled.to_dict())
        return result

    monkeypatch.setattr(
        executor, "execute_employee_task_local", cancel_after_actual_file_publication
    )
    first, replay = case.execute(), case.execute()
    assert first["success"] is replay["success"] is False
    assert first["execution_state"] == replay["execution_state"] == "cancelled"
    assert first["run_id"] == replay["run_id"] and replay["deduplicated"] is True
    with tenant_scope(case.owner.tenant_id):
        stored = case.repository.get(first["run_id"])
        assert stored is not None and stored.to_dict() == cancelled_snapshots[0]
        assert stored.artifacts == []
    assert not first.get("artifacts") and not replay.get("artifacts")
    assert len(case.seen) == len(cancelled_snapshots) == 1


@pytest.mark.parametrize("producer_drift", [False, True])
def test_default_admin_admission_binds_real_reader_artifact_to_original_call(
    group_reader, producer_drift
):
    from app.application.admin_control.employee_run import EmployeeWork, execute_admitted_employee
    from app.application.employee_runtime.executor import execute_employee_task_local
    from app.infrastructure.tenant_scope import tenant_scope

    case = group_reader
    work = EmployeeWork(
        "csv-full-read-employee",
        "read",
        dict(case.params),
        case.owner.user_id,
        case.owner.tenant_id,
        case.owner.session_id,
        case.owner.context["workspace_root"],
        "admin-original-reader",
        dict(case.owner.context),
    )

    def execute(admitted):
        result = execute_employee_task_local(
            admitted.employee_id,
            admitted.task,
            admitted.payload,
            user_id=admitted.user_id,
            runtime_context=admitted.runtime_context,
        )
        if producer_drift:
            admitted.runtime_context.update(call_id="rewritten-call", input_sha256="0" * 64)
            result["artifacts"][0]["metadata"].update(
                call_id="rewritten-call", params_sha256="0" * 64
            )
        return result

    with tenant_scope(case.owner.tenant_id):
        result = execute_admitted_employee(work, execute)
        stored = case.repository.get(result["run_id"])
        assert (
            stored is not None
            and stored.metadata["runtime_context"]["source"] == "admin_employee_execute"
        )
        if producer_drift:
            assert result["success"] is False and result["execution_state"] == "unknown", result
            assert stored.artifacts == [] and stored.status == "blocked"
            replay = execute_admitted_employee(work, execute)
            assert replay["run_id"] == stored.run_id and replay["deduplicated"] is True
            assert replay["success"] is False and replay["execution_state"] == "unknown"
            assert result["retryable"] is replay["retryable"] is False
        else:
            assert result["success"] is True, result
            [receipt] = result["artifacts"]
            assert receipt["metadata"]["call_id"] == stored.tool_calls[0].call_id
            assert [artifact.artifact_id for artifact in stored.artifacts] == [
                receipt["artifact_id"]
            ]
    assert len(case.seen) == 1


@pytest.mark.parametrize("scope", ["missing", "forged", "mismatch", "revoked"])
def test_mobile_backend_revalidates_session_before_execution(trusted_actor, monkeypatch, scope):
    from app.db.models.user import Session
    from app.fastapi_routes.mobile_extensions.backends import execute_employee

    actor = trusted_actor()
    context = actor.context
    if scope == "missing":
        context = {}
    elif scope == "forged":
        context = {"_actor_authorization": {"role": "admin"}}
    elif scope == "revoked":
        with actor.factory.begin() as db:
            db.delete(db.get(Session, actor.session_row_id))
    run = MagicMock(side_effect=AssertionError("must not execute"))
    monkeypatch.setattr(
        "app.application.employee_runtime.executor.execute_employee_task_local", run
    )
    result = execute_employee(
        "excel-generate-employee",
        "task",
        {},
        user_id=actor.user_id + (scope == "mismatch"),
        workspace_root=None,
        session_id="mobile",
        runtime_context=context,
    )
    assert result["error_code"] == "tool_identity_required"
    run.assert_not_called()
