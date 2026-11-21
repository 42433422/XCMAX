"""Real actor/approval/run persistence through Agent -> HTTP -> screen hub.

Only the HTTP transport and browser screen are replaced. These are E2 contract
tests; they do not claim that a deployed browser or desktop was exercised.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator.approval_grant import (
    consume_approval_grant,
    issue_approval_grant,
)
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_background import task_execution_context
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.aiopen import agent_bridge, service
from app.application.aiopen.runtime import ApiKeyRegistry, RuntimeState
from app.application.tools.surface_authority import surface_invocation_scope
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, plan_to_dict
from app.db.models.user import Session, User
from app.domain.aiopen.principal import ScreenPrincipal
from app.fastapi_routes import ai_open
from app.infrastructure.aiopen.cursor_hub import AiOpenCursorHub
from app.infrastructure.auth.agent_mod_scope import bind_agent_actor_scope
from app.utils.time import utc_now_naive
from tests.test_application.test_authenticated_principal_propagation import (
    sessions as _sessions_fixture,
)

sessions = _sessions_fixture


@pytest.fixture
def bridge(sessions, monkeypatch, tmp_path):
    monkeypatch.setattr("app.db.session.SessionLocal", sessions)
    with sessions() as db:
        db.get(User, 71).role = "admin"
        db.commit()
    repository = SQLAlchemyAgentRunRepository(session_factory=sessions)
    monkeypatch.setattr(
        "app.application.agent_orchestrator.run_repository._agent_run_repository", repository
    )
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "idempotency.sqlite"))
    monkeypatch.setenv("XCAGI_AIOPEN_INTERNAL_URL", "http://127.0.0.1:5000")
    clock = [time.time()]
    keys = ApiKeyRegistry(
        RuntimeState({"runtime_keys": {}}),
        lambda: "",
        secrets.token_urlsafe,
        lambda: clock[0],
        storage=lambda: tmp_path / "aiopen-keys.json",
    )
    monkeypatch.setattr(service, "_keys", keys)
    monkeypatch.setitem(service.AIOPEN_STATE, "remote_control_enabled", True)
    hub = AiOpenCursorHub()

    class Screen:
        def __init__(self, sid):
            self.sid, self.sent = sid, []

        async def send_text(self, raw):
            message = json.loads(raw)
            self.sent.append(message)
            hub.handle_client_message(
                json.dumps(
                    {
                        "id": message["id"],
                        "result": {"success": True, "observed": message["action"]},
                    }
                ),
                session_id=self.sid,
            )

    own, foreign = Screen("owned"), Screen("foreign")
    for screen, user, tenant in [(own, "71", "7"), (foreign, "81", "8")]:
        asyncio.run(hub.connect(screen.sid, screen, {"principal_id": user, "tenant_id": tenant}))
    monkeypatch.setattr(service, "aiopen_cursor_hub", hub)
    monkeypatch.setattr(ai_open, "aiopen_cursor_hub", hub)
    # Child trace reporting must not rename the original durable Agent run.
    monkeypatch.setattr(ai_open, "_trace_aiopen_tool_call", lambda **kwargs: "http-child-trace")
    app = FastAPI()
    app.include_router(ai_open.router)
    owner = ScreenPrincipal("71", "7")
    posts, host_responses, client_options = [], [], []
    mode = {"value": "normal"}
    original_client = httpx.Client

    with TestClient(app) as server:

        def transport(request):
            key = request.headers["X-AIOPEN-Key"]
            body = json.loads(request.content)
            posts.append((key, body))
            assert keys.resolve_principal(key) == owner
            assert keys.authorize(key, body["tool"])["ok"]
            assert not keys.authorize(key, "operation_call")["ok"]
            assert 0 < keys._entries()[key]["expires_at"] - clock[0] <= 40
            if mode["value"] == "expired-key":
                clock[0] = keys._entries()[key]["expires_at"] + 1
            response = server.post(request.url.path, json=body, headers={"X-AIOPEN-Key": key})
            host_responses.append((response.status_code, response.json()))
            if mode["value"] == "timeout":
                raise httpx.ReadTimeout("receipt lost", request=request)
            if mode["value"] == "malformed":
                return httpx.Response(200, json={"success": "true"})
            if mode["value"] == "server-error":
                return httpx.Response(500, json={"success": False, "message": "receipt failed"})
            if mode["value"] == "failed-ack":
                return httpx.Response(
                    200, json={"success": False, "message": "event handler failed"}
                )
            return httpx.Response(response.status_code, content=response.content)

        def client(**options):
            client_options.append(options)
            return original_client(**options, transport=httpx.MockTransport(transport))

        monkeypatch.setattr(agent_bridge.httpx, "Client", client)

        def task(action="ui_snapshot", *, approved=False, params=None, persist_verification=True):
            params = dict(params if params is not None else {"session_id": "owned"})
            if action == "ui_verify":
                params.setdefault("text", "Saved")
            context = {
                "user_id": "71",
                "actor_id": "71",
                "tenant_id": "7",
                "_actor_authorization": bind_agent_actor_scope(session_id="valid", user_id="71"),
            }
            step = AgentStep("screen", "aiopen", action, params, status="waiting_user")
            plan = PlanGraph(
                "screen-plan",
                "screen task",
                nodes=[
                    WorkflowNode(step.node_id, step.tool_id, step.action, deepcopy(step.params))
                ],
            )
            verification = AgentStep(
                "verify-screen",
                "aiopen",
                "ui_verify",
                {"session_id": params.get("session_id"), "text": "Saved"},
                depends_on=[step.node_id],
            )
            plan.nodes.append(
                WorkflowNode(
                    verification.node_id,
                    verification.tool_id,
                    verification.action,
                    deepcopy(verification.params),
                    depends_on=verification.depends_on[:],
                )
            )
            run = AgentRun(
                "71",
                "operate the owned screen",
                status="running",
                steps=[step, verification] if persist_verification else [step],
                metadata={
                    "runtime_context": deepcopy(context),
                    "plan": plan_to_dict(plan),
                },
            )
            if approved:
                grant = issue_approval_grant(run, principal_id="71")
                assert grant is not None
                claims = consume_approval_grant(grant["grant"], run=run, principal_id="71")
                run.metadata["approval_receipt"] = {
                    "grant_id": claims["jti"],
                    "step_id": step.step_id,
                    "tool_id": "aiopen",
                    "action": action,
                    "approved_by": "71",
                    "params_sha256": claims["params_sha256"],
                }
            step.status = "running"
            repository.save(run)
            context.update(
                run_id=run.run_id, step_id=step.step_id, **task_execution_context(run, step)
            )
            return run, step, context

        yield SimpleNamespace(
            task=task,
            repository=repository,
            keys=keys,
            own=own,
            foreign=foreign,
            posts=posts,
            responses=host_responses,
            mode=mode,
            options=client_options,
        )


@pytest.mark.parametrize(
    "action,approved,verified",
    [
        ("ui_snapshot", False, False),
        ("ui_click", True, False),
        ("ui_verify", False, True),
    ],
)
def test_executor_reaches_live_hub_with_bound_key_and_original_run(
    bridge, action, approved, verified
):
    run, step, context = bridge.task(action, approved=approved)
    result = AgentToolExecutor().execute(step, runtime_context=context)
    assert result["success"] is True, result
    assert result["run_id"] == run.run_id
    assert "agent_run_id" not in result
    assert result["action_completed"] is True and result["verified"] is verified
    assert result["observed"] == action.removeprefix("ui_")
    assert len(bridge.own.sent) == len(bridge.posts) == 1
    assert not bridge.foreign.sent
    key = bridge.posts[0][0]
    assert not bridge.keys.authorize(key, action)["ok"]
    assert bridge.keys.resolve_principal(key) is None
    assert bridge.options[0]["follow_redirects"] is False
    assert bridge.options[0]["trust_env"] is False


def test_registered_dispatch_without_executor_scope_cannot_operate_screen(bridge):
    from app.application.facades.tools_facade import execute_registered_workflow_tool

    _, step, context = bridge.task("ui_click", approved=True)
    result = execute_registered_workflow_tool(
        "aiopen",
        step.action,
        {
            **step.params,
            "_runtime_context": context,
        },
    )
    assert result["success"] is False and result["error_code"] == "aiopen_agent_not_authorized"
    assert not bridge.posts and not bridge.own.sent


def test_read_snapshot_without_explicit_session_or_verification_remains_usable(bridge):
    run, step, context = bridge.task(params={}, persist_verification=False)
    run.metadata["plan"]["nodes"].pop()
    bridge.repository.save(run)
    result = AgentToolExecutor().execute(step, runtime_context=context)
    assert result["success"] is True and result["verified"] is False
    assert len(bridge.own.sent) == 1 and not bridge.foreign.sent


def test_write_then_verify_retains_original_durable_task_identity(bridge):
    run, step, context = bridge.task("ui_click", approved=True)
    executor = AgentToolExecutor()
    receipt = executor.execute(step, runtime_context=context)
    assert receipt["success"] is True and receipt["verified"] is False
    step.status = "completed"
    verification = run.steps[-1]
    verification.status = "running"
    bridge.repository.save(run)
    verify_context = {
        **context,
        **task_execution_context(run, verification),
        "step_id": verification.step_id,
    }
    verified = executor.execute(verification, runtime_context=verify_context)
    assert verified["success"] is True and verified["verified"] is True
    assert receipt["run_id"] == verified["run_id"] == run.run_id
    assert [message["action"] for message in bridge.own.sent] == ["click", "verify"]
    assert all(bridge.keys.resolve_principal(key) is None for key, _ in bridge.posts)


@pytest.mark.parametrize(
    "mutation",
    [
        "run",
        "tenant",
        "user",
        "step",
        "params",
        "plan",
        "actor-proof",
        "idempotency",
        "new-idempotency",
    ],
)
def test_current_actor_and_stored_task_must_match_exact_invocation(bridge, mutation):
    run, step, context = bridge.task()
    if mutation == "run":
        context["run_id"] = "missing-run"
    elif mutation == "tenant":
        context["tenant_id"] = "8"
    elif mutation == "user":
        context["user_id"] = "81"
    elif mutation == "step":
        context["step_id"] = "different-step"
    elif mutation == "params":
        step.params["session_id"] = "foreign"
    elif mutation == "plan":
        run.metadata["plan"]["nodes"][0]["params"]["session_id"] = "foreign"
        bridge.repository.save(run)
    elif mutation == "actor-proof":
        context["_actor_authorization"]["proof"] = "forged"
    elif mutation == "idempotency":
        context["idempotency_key"] = ""
    else:
        context["idempotency_key"] = "different-attempt-key"
    with surface_invocation_scope("aiopen", step.action, step.params, context):
        result = agent_bridge.execute_aiopen_step(step.action, step.params, context)
    assert result["success"] is False and result["execution_status"] == "not_started"
    assert not bridge.posts and not bridge.own.sent and not bridge.foreign.sent


@pytest.mark.parametrize(
    "state",
    [
        "no-approval",
        "missing-consumption",
        "wrong-digest",
        "cancelled",
        "cancelled-run",
        "expired-session",
        "expired-invocation",
    ],
)
def test_writes_require_live_identity_task_and_consumed_exact_approval(bridge, sessions, state):
    from app.application.tool_execution_deadline import invocation_deadline
    from app.db.models.agent_approval import AgentApprovalConsumption

    run, step, context = bridge.task("ui_click", approved=state != "no-approval")
    if state == "missing-consumption":
        with sessions() as db:
            db.delete(
                db.get(AgentApprovalConsumption, run.metadata["approval_receipt"]["grant_id"])
            )
            db.commit()
    elif state == "wrong-digest":
        run.metadata["approval_receipt"]["params_sha256"] = "wrong"
        bridge.repository.save(run)
    elif state == "cancelled":
        context["cancel_requested"] = True
    elif state == "cancelled-run":
        run.status = "cancelled"
        bridge.repository.save(run)
    elif state == "expired-session":
        with sessions() as db:
            db.query(Session).filter_by(session_id="valid").one().expires_at = (
                utc_now_naive() - timedelta(seconds=1)
            )
            db.commit()
    with invocation_deadline(time.monotonic() + (-1 if state == "expired-invocation" else 30)):
        result = AgentToolExecutor().execute(step, runtime_context=context)
    assert result["success"] is False
    assert not bridge.posts and not bridge.own.sent


def test_foreign_screen_is_denied_by_real_http_principal_binding(bridge):
    _, step, context = bridge.task(params={"session_id": "foreign"})
    result = AgentToolExecutor().execute(step, runtime_context=context)
    assert result["success"] is False
    assert bridge.responses[0][0] == 403
    assert bridge.responses[0][1]["code"] == "SCREEN_NOT_AUTHORIZED"
    assert not bridge.own.sent and not bridge.foreign.sent


@pytest.mark.parametrize(
    "graph",
    [
        "missing",
        "parallel",
        "other-session",
        "implicit-session",
        "blank-session",
        "plan-only",
        "skipped",
    ],
)
def test_writes_require_executable_downstream_verification_on_explicit_session(bridge, graph):
    params = (
        {}
        if graph == "implicit-session"
        else {"session_id": " " if graph == "blank-session" else "owned"}
    )
    run, step, context = bridge.task(
        "ui_click", approved=True, params=params, persist_verification=graph != "plan-only"
    )
    verification = run.steps[-1]
    node = run.metadata["plan"]["nodes"][-1]
    if graph == "missing":
        run.steps.pop()
        run.metadata["plan"]["nodes"].pop()
    elif graph == "parallel":
        node["depends_on"] = verification.depends_on = []
    elif graph == "other-session":
        node["params"]["session_id"] = verification.params["session_id"] = "foreign"
    elif graph == "skipped":
        verification.status = "skipped"
    bridge.repository.save(run)
    result = AgentToolExecutor().execute(step, runtime_context=context)
    expected = (
        "schema_validation_failed"
        if graph in {"implicit-session", "blank-session"}
        else "aiopen_agent_verification_required"
    )
    assert result["success"] is False and result["error_code"] == expected, result
    if expected == "aiopen_agent_verification_required":
        assert result["execution_status"] == "not_started"
    assert not bridge.posts and not bridge.own.sent and not bridge.foreign.sent
    assert not bridge.keys._entries()


@pytest.mark.parametrize("edge", ["depends_on", "next", "branch"])
def test_indirect_verification_reuses_graph_edges_but_refuses_optional_branches(bridge, edge):
    run, step, context = bridge.task("ui_click", approved=True)
    verification = run.steps[-1]
    node, verify = run.metadata["plan"]["nodes"]
    observe = AgentStep(
        "observe", "aiopen", "ui_snapshot", {"session_id": "owned"}, depends_on=[step.node_id]
    )
    run.steps.insert(1, observe)
    observation = plan_to_dict(
        PlanGraph(
            "p",
            "observe",
            nodes=[
                WorkflowNode(
                    observe.node_id,
                    observe.tool_id,
                    observe.action,
                    observe.params,
                    depends_on=observe.depends_on,
                )
            ],
        )
    )["nodes"][0]
    if edge == "depends_on":
        verify["depends_on"] = verification.depends_on = [observe.node_id]
    else:
        verify["depends_on"] = verification.depends_on = []
        observation[edge if edge == "next" else "branches"] = (
            verification.node_id
            if edge == "next"
            else [{"target": verification.node_id, "condition": {"key": "success", "equals": True}}]
        )
    run.metadata["plan"]["nodes"] = [verify, observation, node]
    bridge.repository.save(run)
    result = AgentToolExecutor().execute(step, runtime_context=context)
    assert result["success"] is (edge != "branch"), result
    assert len(bridge.own.sent) == len(bridge.posts) == (0 if edge == "branch" else 1)
    if edge == "branch":
        assert result["error_code"] == "aiopen_agent_verification_required"
        assert not bridge.keys._entries()


@pytest.mark.parametrize("proof", ["metadata-only", "approved", "cancelled"])
def test_workspace_proof_requires_a_matching_live_durable_approval(bridge, sessions, proof):
    from app.application.workflow.approval_persistence import SNAPSHOT_KEY, _build_workflow_snapshot
    from app.application.workflow.workflow_types import (
        ApprovalRequest as WorkflowApprovalRequest,
    )
    from app.application.workflow.workflow_types import (
        ApprovalStatus as WorkflowApprovalStatus,
    )
    from app.application.workflow.workflow_types import (
        plan_fingerprint,
        plan_from_dict,
    )
    from app.db.models.approval import ApprovalFlow, ApprovalRequest
    from app.infrastructure.tenant_scope import tenant_scope

    run, step, context = bridge.task("ui_click")
    request_id = "workspace-approval"
    plan = plan_from_dict(run.metadata["plan"])
    request = WorkflowApprovalRequest(
        request_id,
        plan.plan_id,
        step.node_id,
        step.tool_id,
        step.action,
        step.params,
        WorkflowApprovalStatus.PENDING,
        utc_now_naive(),
        tenant_id=7,
    )
    with tenant_scope(7):
        snapshot = _build_workflow_snapshot(request, context, plan)
    snapshot.update(agent_run_id=run.run_id, approved_step_id=step.step_id)
    run.metadata["plan"] = snapshot["plan"]
    run.metadata["approval_receipt"] = {
        "step_id": step.step_id,
        "tool_id": step.tool_id,
        "action": step.action,
        "approved_by": "71",
        "approval_request_id": request_id,
        "plan_sha256": plan_fingerprint(plan_from_dict(snapshot["plan"])),
    }
    bridge.repository.save(run)
    if proof != "metadata-only":
        business_data = {
            "plan_id": plan.plan_id,
            "node_id": step.node_id,
            "tool_id": step.tool_id,
            "action": step.action,
            "params": step.params,
            SNAPSHOT_KEY: snapshot,
            "agent_execution_claim": {"agent_run_id": run.run_id, "approved_step_id": step.step_id},
        }
        with sessions() as db:
            flow = ApprovalFlow(flow_key="browser-workspace", flow_name="Browser")
            db.add(flow)
            db.flush()
            db.add(
                ApprovalRequest(
                    request_no=request_id,
                    flow_id=flow.id,
                    business_type="workflow_tool",
                    business_data=json.dumps(business_data),
                    applicant_id=71,
                    title="Browser task",
                    status=proof,
                    tenant_id=7,
                )
            )
            db.commit()
    result = AgentToolExecutor().execute(step, runtime_context=context)
    assert result["success"] is (proof == "approved"), result
    assert len(bridge.own.sent) == (1 if proof == "approved" else 0)


def test_expired_one_action_key_is_rejected_at_the_host_and_revoked(bridge):
    _, step, context = bridge.task()
    bridge.mode["value"] = "expired-key"
    result = AgentToolExecutor().execute(step, runtime_context=context)
    assert result["success"] is False
    assert bridge.responses[0][0] == 401
    assert bridge.responses[0][1]["code"] == "AIOPEN_KEY_EXPIRED"
    assert not bridge.own.sent and not bridge.foreign.sent
    assert bridge.keys.resolve_principal(bridge.posts[0][0]) is None


@pytest.mark.parametrize("mode", ["timeout", "malformed", "server-error", "failed-ack"])
def test_lost_or_invalid_write_receipt_is_never_replayed(bridge, mode):
    run, step, context = bridge.task("ui_click", approved=True)
    bridge.mode["value"] = mode
    executor = AgentToolExecutor()
    result = executor.execute(step, runtime_context=context)
    assert result["success"] is False
    assert result["outcome"] == "unknown"
    assert result["run_id"] == run.run_id
    assert result["retryable"] is False and result["reconciliation_required"] is True
    repeated = executor.execute(step, runtime_context=context)
    assert repeated["success"] is False and repeated["retryable"] is False
    assert len(bridge.own.sent) == len(bridge.posts) == 1
    assert bridge.keys.resolve_principal(bridge.posts[0][0]) is None
