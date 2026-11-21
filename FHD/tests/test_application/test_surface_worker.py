"""Actual spawned Agent boundary, durable authority, and real Playwright driver.

The browser page/HTTP effect is replaced; Chromium itself remains a separate
required CI contract. Resource limits and the shipped worker adapter stay active.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
from contextlib import AsyncExitStack
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator import business_write_guard as guard
from app.application.agent_orchestrator.task_background import task_execution_context
from app.application.agent_orchestrator.task_execution_models import AgentTaskExecution
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.db.db_base import Base
from app.db.models.agent import AgentTaskExecutionRecord
from tests.test_application.test_browser_tool import harness as _browser_harness
from tests.test_application.test_browser_tool import sessions as _sessions_fixture

harness, sessions = _browser_harness, _sessions_fixture


def _effect_receipt(context):
    from app.db.session import get_db

    guard.recheck_worker_claim()
    with get_db() as db:
        marker = db.execute(text("SELECT value FROM surface_workflow_marker")).scalar_one()
    Path(os.environ["XCMAX_TEST_SURFACE_EFFECT"]).write_text("performed")
    return {
        "success": True,
        "claim": guard.capture_worker_claim(),
        "elt_scope": guard.owns_elt_step(context),
        "workflow_database": marker,
        "pid": os.getpid(),
    }


class SurfaceExecutor(AgentToolExecutor):
    """Keep the real executor; replace only the page/HTTP boundary after spawn."""

    def execute(self, step, *, runtime_context):
        if step.tool_id == "browser":
            from app.infrastructure.browser import runtime

            async def driver(plan, **options):
                async with AsyncExitStack() as resources:
                    if os.getenv("XCMAX_TEST_SURFACE_PLAYWRIGHT") == "1":
                        from playwright.async_api import async_playwright

                        playwright = await resources.enter_async_context(async_playwright())
                        assert playwright.chromium.name == "chromium"
                    if os.getenv("XCMAX_TEST_SURFACE_REVOKE") == "1":
                        from app.db import HostSessionLocal

                        with HostSessionLocal() as db:
                            row = db.get(AgentTaskExecutionRecord, runtime_context["run_id"])
                            row.execution_count += 1
                            db.commit()

                    async def callback():
                        options["before_action"]()
                        return _effect_receipt(runtime_context)

                    receipt = await asyncio.create_task(callback())
                    return {
                        **receipt,
                        "verified": not plan["observe"],
                        "outcome": "observed" if plan["observe"] else "succeeded",
                        "artifacts": [],
                    }

            runtime.execute_browser_plan = driver
        else:
            import httpx

            from app.application.aiopen import agent_bridge

            original_client = httpx.Client

            def transport(_request):
                return httpx.Response(200, json=_effect_receipt(runtime_context))

            agent_bridge.httpx.Client = lambda **kw: original_client(
                **kw, transport=httpx.MockTransport(transport)
            )
        return super().execute(step, runtime_context=runtime_context)


@pytest.fixture
def surface(harness, sessions, monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", str(sessions.kw["bind"].url))
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "0")
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("XCAGI_TOOL_SANDBOX", "1")
    monkeypatch.setenv("XCMAX_TEST_SURFACE_EFFECT", str(tmp_path / "effect"))
    monkeypatch.delenv("XCMAX_TEST_SURFACE_REVOKE", raising=False)
    monkeypatch.delenv("XCMAX_TEST_SURFACE_PLAYWRIGHT", raising=False)
    engine = create_engine(f"sqlite:///{tmp_path / 'workflow.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with engine.begin() as db:
        db.execute(text("CREATE TABLE surface_workflow_marker (value TEXT)"))
        db.execute(text("INSERT INTO surface_workflow_marker VALUES ('caller-workflow-db')"))
    monkeypatch.setattr("app.application.customer_app_service.get_customers_session", factory)
    harness.workflow_sessions = factory
    harness.effect = tmp_path / "effect"
    try:
        yield harness
    finally:
        engine.dispose()


def _claim(sessions, run):
    execution = AgentTaskExecution(
        run_id=run.run_id, task_id=run.run_id, user_id="71", tenant_id="7", execution_count=1
    )
    with sessions() as db:
        db.add(
            AgentTaskExecutionRecord(
                run_id=run.run_id,
                task_id=run.run_id,
                user_id="71",
                tenant_id="7",
                state="claimed",
                available_at="",
                created_at="",
                updated_at="",
                lease_owner="surface-worker",
                lease_expires_at="2999-01-01T00:00:00+00:00",
                execution_count=1,
            )
        )
        db.commit()
    return execution


def _execute(surface, sessions, run, step, context):
    import time

    execution = _claim(sessions, run)
    # Caller-controlled fields must not replace the trusted held generation or
    # activate the unrelated ELT checkpoint capability.
    context.update(surface_claim=[run.run_id, "forged", 999], durable_elt_batch=True)
    with guard.worker_claim_scope(surface.repository, execution, "surface-worker"):
        return SurfaceExecutor().execute_with_deadline(
            step, runtime_context=context, deadline_monotonic=time.monotonic() + 30
        )


def test_real_playwright_driver_starts_in_spawn_under_worker_limits(surface, sessions, monkeypatch):
    if os.getenv("XCMAX_BROWSER_REQUIRE_REAL") == "1":
        try:
            importlib.import_module("playwright.async_api")
        except ImportError:
            pytest.fail("Required Playwright driver is not installed", pytrace=False)
    else:
        pytest.importorskip(
            "playwright.async_api", reason="Optional browser extra is not installed"
        )
    monkeypatch.setenv("XCMAX_TEST_SURFACE_PLAYWRIGHT", "1")
    run, step, context = surface.task("observe", approved=False)
    result = _execute(surface, sessions, run, step, context)
    assert result.get("success") is True, result
    assert result["pid"] != os.getpid() and surface.effect.exists()


@pytest.mark.parametrize("tool", ["browser", "aiopen"])
def test_spawn_restores_surface_claim_and_workflow_database_without_elt_scope(
    surface, sessions, tool
):
    run, step, context = surface.task("observe", approved=False)
    if tool == "aiopen":
        step.tool_id, step.action, step.params = "aiopen", "ui_snapshot", {}
        node = run.metadata["plan"]["nodes"][0]
        node.update(tool_id=step.tool_id, action=step.action, params=step.params)
        surface.repository.save(run)
        context.update(task_execution_context(run, step))
    result = _execute(surface, sessions, run, step, context)
    assert result.get("success") is True, result
    assert result["claim"] == [run.run_id, "surface-worker", 1]
    assert result["elt_scope"] is False
    assert result["workflow_database"] == "caller-workflow-db"
    assert result["pid"] != os.getpid() and surface.effect.exists()
    assert result["run_id"] == run.run_id
    assert guard.capture_worker_claim() is None


def test_changed_queue_generation_is_fenced_inside_async_browser_callback(
    surface, sessions, monkeypatch
):
    run, step, context = surface.task()
    monkeypatch.setenv("XCMAX_TEST_SURFACE_REVOKE", "1")
    result = _execute(surface, sessions, run, step, context)
    assert result.get("success") is False and result["outcome"] == "unknown", result
    assert result["retryable"] is False and result["reconciliation_required"] is True
    assert not surface.effect.exists()
    with sessions() as db:
        assert db.get(AgentTaskExecutionRecord, run.run_id).execution_count == 2


def test_spawned_browser_loads_real_workspace_approval_from_caller_database(surface, sessions):
    from app.application.workflow.approval_persistence import SNAPSHOT_KEY, _build_workflow_snapshot
    from app.application.workflow.workflow_types import ApprovalRequest as WorkflowApprovalRequest
    from app.application.workflow.workflow_types import ApprovalStatus as WorkflowApprovalStatus
    from app.application.workflow.workflow_types import plan_fingerprint, plan_from_dict
    from app.db.models.approval import ApprovalFlow, ApprovalRequest
    from app.db.models.user import User
    from app.infrastructure.tenant_scope import tenant_scope
    from app.utils.time import utc_now_naive

    run, step, context = surface.task(approved=False)
    plan = plan_from_dict(run.metadata["plan"])
    request = WorkflowApprovalRequest(
        "surface-workspace",
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
        "approval_request_id": request.request_id,
        "plan_sha256": plan_fingerprint(plan_from_dict(snapshot["plan"])),
    }
    with surface.workflow_sessions() as db:
        db.add(User(id=71, username="workflow-applicant", password="unused", tenant_id=7))
        flow = ApprovalFlow(flow_key="browser-workspace", flow_name="Browser")
        db.add(flow)
        db.flush()
        db.add(
            ApprovalRequest(
                request_no=request.request_id,
                flow_id=flow.id,
                business_type="workflow_tool",
                business_data=json.dumps(
                    {
                        "plan_id": plan.plan_id,
                        "node_id": step.node_id,
                        "tool_id": step.tool_id,
                        "action": step.action,
                        "params": step.params,
                        SNAPSHOT_KEY: snapshot,
                        "agent_execution_claim": {
                            "agent_run_id": run.run_id,
                            "approved_step_id": step.step_id,
                        },
                    }
                ),
                applicant_id=71,
                title="Browser task",
                status="approved",
                tenant_id=7,
            )
        )
        db.commit()
    surface.repository.save(run)
    result = _execute(surface, sessions, run, step, context)
    assert result.get("success") is True and result["verified"] is True, result
    assert result["workflow_database"] == "caller-workflow-db" and surface.effect.exists()
