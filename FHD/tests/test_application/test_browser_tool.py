"""Real Agent authority/schema/artifact persistence with only Playwright mocked.

Actual Chromium behavior is covered separately by test_browser_runtime.py.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from PIL import Image

from app.application.agent_orchestrator import artifact_files
from app.application.agent_orchestrator.approval_grant import (
    consume_approval_grant,
    issue_approval_grant,
)
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep, artifact_from_dict
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_background import task_execution_context
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.agent_orchestrator.tool_spec import build_tool_specs_v2, validate_tool_call
from app.application.tools import browser
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, plan_to_dict
from app.db.models.user import User
from app.infrastructure.auth.agent_mod_scope import bind_agent_actor_scope
from app.infrastructure.browser import runtime
from tests.test_application.test_authenticated_principal_propagation import (
    sessions as _sessions_fixture,
)

sessions = _sessions_fixture


def execute_params():
    return {
        "url": "https://allowed.example/form",
        "steps": [{"action": "click", "locator": {"role": "button", "name": "Submit"}}],
        "verify": [{"kind": "text", "locator": {"selector": "#receipt"}, "expected": "saved"}],
    }


@pytest.fixture
def harness(sessions, monkeypatch, tmp_path):
    with sessions() as db:
        db.get(User, 71).role = "admin"
        db.commit()
    repository = SQLAlchemyAgentRunRepository(session_factory=sessions)
    monkeypatch.setattr(
        "app.application.agent_orchestrator.run_repository._agent_run_repository", repository
    )
    monkeypatch.setattr(artifact_files, "get_app_data_dir", lambda: str(tmp_path / "data"))
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "idempotency.sqlite"))
    monkeypatch.setenv(
        "XCAGI_BROWSER_ALLOWED_ORIGINS",
        json.dumps({"7": ["https://allowed.example"], "8": ["https://foreign.example"]}),
    )
    calls, behavior = [], {}

    async def driver(plan, **options):
        calls.append((deepcopy(plan), options))
        options["before_action"]()
        if "build" in behavior:
            return behavior["build"](plan, options)
        return {
            "success": True,
            "verified": not plan["observe"],
            "outcome": "observed" if plan["observe"] else "succeeded",
            "url": plan["url"],
            "snapshot": "untrusted page content",
            "steps": [],
            "verification": [{"kind": "text", "status": "passed"}],
            "artifacts": [],
        }

    monkeypatch.setattr(runtime, "execute_browser_plan", driver)

    def task(action="execute", *, approved=True, params=None):
        if params is None:
            params = execute_params() if action == "execute" else {"url": "https://allowed.example"}
        context = {
            "user_id": "71",
            "actor_id": "71",
            "tenant_id": "7",
            "_actor_authorization": bind_agent_actor_scope(session_id="valid", user_id="71"),
        }
        step = AgentStep("browser", "browser", action, deepcopy(params), status="waiting_user")
        plan = PlanGraph(
            "browser-plan",
            "browser task",
            nodes=[WorkflowNode(step.node_id, step.tool_id, step.action, deepcopy(step.params))],
        )
        run = AgentRun(
            "71",
            "operate the approved site",
            status="running",
            steps=[step],
            metadata={"runtime_context": deepcopy(context), "plan": plan_to_dict(plan)},
        )
        if approved:
            grant = issue_approval_grant(run, principal_id="71")
            assert grant is not None
            claims = consume_approval_grant(grant["grant"], run=run, principal_id="71")
            run.metadata["approval_receipt"] = {
                "grant_id": claims["jti"],
                "step_id": step.step_id,
                "tool_id": "browser",
                "action": action,
                "approved_by": "71",
                "params_sha256": claims["params_sha256"],
            }
        step.status = "running"
        repository.save(run)
        context.update(run_id=run.run_id, step_id=step.step_id, **task_execution_context(run, step))
        return run, step, context

    def upload(*, owner="71", tenant="7", content=b"owned evidence"):
        source = AgentRun(
            owner,
            "source artifact",
            status="completed",
            metadata={"runtime_context": {"user_id": owner, "tenant_id": tenant}},
        )
        artifact = artifact_files.store_run_file(
            source.run_id, content, name="evidence.txt", owner_user_id=int(owner), tenant_id=tenant
        )
        source.artifacts = [artifact_from_dict(artifact)]
        repository.save(source)
        return {"run_id": source.run_id, "artifact_id": artifact["artifact_id"]}

    return SimpleNamespace(
        task=task, upload=upload, repository=repository, calls=calls, behavior=behavior
    )


def test_registered_executor_persists_bound_screenshot_download_and_receipt(harness):
    def build(plan, options):
        folder = options["artifact_dir"]
        png = folder / "screenshot.png"
        Image.new("RGB", (2, 2), "black").save(png)
        download = folder / "download.txt"
        download.write_bytes(b"approved receipt")
        return {
            "success": True,
            "verified": True,
            "outcome": "succeeded",
            "snapshot": "untrusted content omitted from durable receipt",
            "verification": [{"kind": "text", "status": "passed"}],
            "artifacts": [
                {
                    "path": str(path),
                    "name": path.name,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
                for path in (png, download)
            ],
        }

    harness.behavior["build"] = build
    params = {**execute_params(), "screenshot": True}
    run, step, context = harness.task(params=params)
    spec = build_tool_specs_v2()[("browser", "execute")]
    assert spec.risk == "high" and not spec.idempotent and not spec.read_only
    assert validate_tool_call("browser", "execute", params).ok
    result = AgentToolExecutor().execute(step, runtime_context=context)
    assert result["success"] is True and result["verified"] is True, result
    assert result["run_id"] == run.run_id and result["untrusted_page_content"] is True
    plan, options = harness.calls[0]
    assert plan["screenshot"] is True and plan["observe"] is False
    assert options["allowed_origins"] == frozenset({"https://allowed.example"})
    assert not options["artifact_dir"].exists()
    artifacts = {item["name"]: item for item in result["artifacts"]}
    assert set(artifacts) == {"screenshot.png", "download.txt", "browser-receipt.json"}
    for item in artifacts.values():
        content = artifact_files.read_verified_run_file(run.run_id, item)
        assert item["metadata"]["sha256"] == hashlib.sha256(content).hexdigest()
        assert item["metadata"]["owner_user_id"] == "71" and item["metadata"]["tenant_id"] == "7"
    receipt = json.loads(
        artifact_files.read_verified_run_file(run.run_id, artifacts["browser-receipt.json"])
    )
    assert receipt["run_id"] == run.run_id and receipt["verified"] is True
    assert "snapshot" not in receipt and len(receipt["artifacts"]) == 2


def test_observe_uses_authenticated_tenant_policy_without_write_approval(harness):
    run, step, context = harness.task("observe", approved=False)
    result = AgentToolExecutor().execute(step, runtime_context=context)
    assert result["success"] is True and result["verified"] is False, result
    assert result["run_id"] == run.run_id and result["untrusted_page_content"] is True
    assert harness.calls[0][1]["allowed_origins"] == frozenset({"https://allowed.example"})


@pytest.mark.parametrize("proof", ["missing", "wrong-action", "wrong-digest", "unconsumed"])
def test_effects_require_exact_consumed_approval_before_runtime(harness, sessions, proof):
    from app.db.models.agent_approval import AgentApprovalConsumption

    run, step, context = harness.task(approved=proof != "missing")
    if proof == "wrong-action":
        run.metadata["approval_receipt"]["action"] = "observe"
    elif proof == "wrong-digest":
        run.metadata["approval_receipt"]["params_sha256"] = "different-params"
    elif proof == "unconsumed":
        with sessions() as db:
            db.delete(
                db.get(AgentApprovalConsumption, run.metadata["approval_receipt"]["grant_id"])
            )
            db.commit()
    harness.repository.save(run)
    result = AgentToolExecutor().execute(step, runtime_context=context)
    assert result["success"] is False and not harness.calls


def test_registered_dispatch_cannot_skip_the_executor_authority_scope(harness):
    from app.application.facades.tools_facade import execute_registered_workflow_tool

    _, step, context = harness.task()
    result = execute_registered_workflow_tool(
        "browser", "execute", {**step.params, "_runtime_context": context}
    )
    assert result["success"] is False and result["execution_status"] == "not_started"
    assert not harness.calls


@pytest.mark.parametrize(
    "extra",
    [
        {"allowed_origins": ["https://evil.example"]},
        {"executable_path": "/tmp/browser"},
        {"tenant_id": "8"},
    ],
)
def test_model_parameters_cannot_override_tenant_or_browser_operator_policy(harness, extra):
    _, step, context = harness.task(params={**execute_params(), **extra})
    result = AgentToolExecutor().execute(step, runtime_context=context)
    assert result["success"] is False and not harness.calls


def test_missing_tenant_origin_policy_prevents_runtime(harness, monkeypatch):
    monkeypatch.setenv("XCAGI_BROWSER_ALLOWED_ORIGINS", '{"8":["https://allowed.example"]}')
    _, step, context = harness.task()
    result = AgentToolExecutor().execute(step, runtime_context=context)
    assert result["success"] is False and not harness.calls


@pytest.mark.parametrize(
    "source", ["owned", "foreign-user", "foreign-tenant", "corrupt", "oversize"]
)
def test_upload_resolves_only_verified_owned_artifacts(harness, monkeypatch, source):
    reference = harness.upload(
        owner="81" if source == "foreign-user" else "71",
        tenant="8" if source == "foreign-tenant" else "7",
    )
    if source == "corrupt":
        artifact_files.artifact_path(reference["run_id"], reference["artifact_id"]).write_bytes(
            b"tampered"
        )
    if source == "oversize":
        monkeypatch.setattr(browser, "MAX_ARTIFACT_BYTES", 4)
    params = execute_params()
    params["steps"] = [{"action": "upload", "locator": {"label": "Evidence"}, "files": [reference]}]
    _, step, context = harness.task(params=params)
    result = AgentToolExecutor().execute(step, runtime_context=context)
    if source == "owned":
        assert result["success"] is True, result
        assert harness.calls[0][0]["steps"][0]["files"] == [
            {"name": "evidence.txt", "mime_type": "text/plain", "buffer": b"owned evidence"}
        ]
    else:
        assert result["success"] is False and not harness.calls


@pytest.mark.parametrize("damage", ["escape", "symlink", "digest", "oversize"])
def test_invalid_runtime_artifacts_block_success_and_are_not_replayed(
    harness, monkeypatch, tmp_path, damage
):
    def build(plan, options):
        path = options["artifact_dir"] / "download.txt"
        if damage in {"escape", "symlink"}:
            outside = tmp_path / "outside.txt"
            outside.write_bytes(b"outside artifact")
            if damage == "symlink":
                path.symlink_to(outside)
            else:
                path = outside
        else:
            path.write_bytes(b"receipt")
        return {
            "success": True,
            "verified": True,
            "artifacts": [
                {
                    "path": str(path),
                    "name": "download.txt",
                    "sha256": "wrong"
                    if damage == "digest"
                    else hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            ],
        }

    harness.behavior["build"] = build
    if damage == "oversize":
        monkeypatch.setattr(browser, "MAX_ARTIFACT_BYTES", 4)
    _, step, context = harness.task()
    executor = AgentToolExecutor()
    result = executor.execute(step, runtime_context=context)
    assert result["success"] is False and result["outcome"] == "unknown", result
    assert result["retryable"] is False and result["reconciliation_required"] is True
    repeated = executor.execute(step, runtime_context=context)
    assert repeated["success"] is False and len(harness.calls) == 1


def test_action_callback_rechecks_cancelled_run_before_next_effect(harness):
    run, step, context = harness.task()

    def build(plan, options):
        run.status = "cancelled"
        harness.repository.save(run)
        options["before_action"]()
        pytest.fail("cancelled browser task reached a subsequent effect")

    harness.behavior["build"] = build
    result = AgentToolExecutor().execute(step, runtime_context=context)
    assert result["success"] is False and result["outcome"] == "unknown", result
    assert result["retryable"] is False
