"""Real tool-process timeout and scheduler crash boundaries for E28/E30."""

from __future__ import annotations

import json
import multiprocessing
import os
import signal
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event

import psutil
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.application.agent_orchestrator.orchestrator import AgentOrchestrator, _runtime_dependencies
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_dispatcher import AgentTaskDispatcher
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.agent_orchestrator.unified_task import create_unified_task
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, plan_to_dict
from app.db.models.purchase_unit import PurchaseUnit


class BlockingCustomerQuery(AgentToolExecutor):
    """Inject a hang inside the shipped isolated executor, including its descendant."""

    def execute(self, step, *, runtime_context):
        child = subprocess.Popen(
            [sys.executable, "-c", "from threading import Event; Event().wait(60)"]
        )
        Path(runtime_context["fault_receipt"]).write_text(
            json.dumps(
                {
                    "pids": [os.getpid(), child.pid],
                    "run_id": runtime_context["run_id"],
                    "step_id": runtime_context["step_id"],
                }
            ),
            encoding="utf-8",
        )
        Event().wait(60)
        return {"success": False, "error_code": "injected_hang_not_interrupted"}


def observe_tool_timeout(root: Path, context: dict) -> dict:
    children_before = {child.pid for child in multiprocessing.active_children()}
    receipt = root / "e28-worker.json"
    engine = create_engine(f"sqlite:///{root / 'e28-task.sqlite'}")
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    runs = SQLAlchemyAgentRunRepository(session_factory=factory)
    run = AgentRun(
        user_id=context["user_id"],
        message="中断正在执行的查询",
        steps=[
            AgentStep(
                node_id="query",
                tool_id="customers",
                action="query",
                params={"keyword": "闭环指定客户甲"},
                risk="low",
                idempotent=True,
            ),
        ],
    )
    context = {**context, "task_id": run.run_id, "fault_receipt": str(receipt)}
    run.metadata.update(
        runtime_context=context,
        task_context={"task_id": run.run_id},
        plan=plan_to_dict(
            PlanGraph(
                plan_id=run.run_id,
                intent="customer_query",
                nodes=[
                    WorkflowNode(
                        node_id="query",
                        tool_id="customers",
                        action="query",
                        params={"keyword": "闭环指定客户甲"},
                        risk="low",
                        idempotent=True,
                    )
                ],
            )
        ),
    )
    runtime = _runtime_dependencies()

    def bounded_spec(tool, action):
        spec = runtime.action_spec(tool, action)
        return replace(spec, timeout_seconds=8) if spec is not None else None

    executor = BlockingCustomerQuery()
    orchestrator = AgentOrchestrator(
        repository=runs,
        tool_executor=executor,
        dependencies=replace(runtime, action_spec=bounded_spec),
    )
    try:
        orchestrator._execute_ready_steps(run, runtime_context=context)
        stored = SQLAlchemyAgentRunRepository(session_factory=factory).get(run.run_id)
        assert stored is not None and len(stored.tool_calls) == 1
        observation = json.loads(receipt.read_text()) if receipt.is_file() else {}
        pids = observation.get("pids") or []
        exited = len(pids) == 2 and all(not psutil.pid_exists(pid) for pid in pids)
        return {
            "process_started": observation.get("run_id") == run.run_id
            and observation.get("step_id") == stored.tool_calls[0].step_id
            and len(pids) == 2,
            "process_exited": exited,
            "resources_released": exited and not getattr(executor, "_tool_cleanup_failed", False),
            "task_state": stored.tool_calls[0].metadata.get("execution_status", ""),
            "task_id": run.run_id,
            "pids": pids,
            "tool_call_id": stored.tool_calls[0].call_id,
            "output": stored.tool_calls[0].output,
        }
    finally:
        # Failed product cleanup must fail the observation, then clean only this fault's pids.
        task_pids = (
            set(json.loads(receipt.read_text()).get("pids", [])) if receipt.is_file() else set()
        )
        for child in multiprocessing.active_children():
            if (
                child.pid not in children_before
                and (not task_pids or child.pid in task_pids)
                and child.is_alive()
            ):
                if os.name != "nt":
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                child.kill()
                child.join(timeout=5)
        engine.dispose()


class CrashAfterCustomerCommit(AgentToolExecutor):
    def execute_with_deadline(self, step, *, runtime_context, deadline_monotonic):
        # Crash the scheduler process after its real tool committed but before
        # StepExecution can replace the persisted running tool-call checkpoint.
        output = self.execute(step, runtime_context=runtime_context)
        Path(runtime_context["fault_receipt"]).write_text(json.dumps(output), encoding="utf-8")
        os._exit(30 if output.get("success") is True else 31)


def _crash_scheduler(db_url: str, run_id: str) -> None:
    engine = create_engine(db_url, connect_args={"check_same_thread": False, "timeout": 30})
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    import app.application.customer_app_service as customers

    customers.get_customers_session = factory
    queue = SQLAlchemyTaskExecutionRepository(session_factory=factory)
    runs = SQLAlchemyAgentRunRepository(session_factory=factory)
    execution = queue.claim("e30-scheduler", lease_seconds=60, run_id=run_id)
    assert execution is not None
    dispatcher = AgentTaskDispatcher(
        execution_repository=queue,
        run_repository=runs,
        orchestrator_factory=lambda repository: AgentOrchestrator(
            repository=repository,
            tool_executor=CrashAfterCustomerCommit(),
        ),
    )
    dispatcher._execute_claim(execution, "e30-scheduler")


def observe_scheduler_restart(engine, root: Path, context: dict) -> dict:
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    runs = SQLAlchemyAgentRunRepository(session_factory=factory)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=factory)
    fault_receipt = root / "e30-crash.json"
    context = {**context, "fault_receipt": str(fault_receipt)}
    orchestrator = AgentOrchestrator(repository=runs)
    created = create_unified_task(
        orchestrator=orchestrator,
        user_id=context["user_id"],
        task_id=context["task_id"],
        title="调度重启后核验原客户",
        message="创建客户后模拟调度进程退出",
        tool_id="customers",
        action="create",
        params={"unit_name": "闭环调度重启客户"},
        runtime_context=context,
    )
    run = created.run
    staged = orchestrator.stage_approved_run(
        run.run_id,
        approved_by=context["user_id"],
        approved_step_id=run.steps[0].step_id,
    )
    assert staged is not None
    queue.enqueue(staged, requested_by=context["user_id"])
    worker = multiprocessing.get_context("spawn").Process(
        target=_crash_scheduler,
        args=(str(engine.url), run.run_id),
    )
    worker.start()
    try:
        worker.join(timeout=30)
        failure = fault_receipt.read_text() if fault_receipt.is_file() else "no commit receipt"
        assert worker.exitcode == 30, (worker.exitcode, failure)
        queue = SQLAlchemyTaskExecutionRepository(session_factory=factory)
        restored = queue.get(run.run_id)
        restored_run = SQLAlchemyAgentRunRepository(session_factory=factory).get(run.run_id)
        assert restored is not None and restored_run is not None
        calls = [call for call in restored_run.tool_calls if call.step_id == run.steps[0].step_id]
        assert len(calls) == 1

        def customer_ids():
            with Session(engine) as db:
                return list(
                    db.execute(
                        select(PurchaseUnit.id)
                        .where(
                            PurchaseUnit.unit_name == "闭环调度重启客户",
                            PurchaseUnit.tenant_id == 11,
                        )
                        .execution_options(skip_tenant_filter=True)
                    ).scalars()
                )

        before = customer_ids()
        assert len(before) == 1
        assert queue.claim("restarted-scheduler", lease_seconds=60, run_id=run.run_id) is None
        after_expiry = (datetime.now(UTC) + timedelta(seconds=120)).isoformat()
        assert (
            queue.claim(
                "restarted-scheduler", lease_seconds=60, run_id=run.run_id, now=after_expiry
            )
            is None
        )
        blocked = queue.get(run.run_id)
        assert blocked is not None and blocked.last_error_code == "needs_verification"
        return {
            "repository_kind": "sql",
            "restored_state": restored.state,
            "tool_status": calls[0].status,
            "replayed": customer_ids() != before
            or blocked.execution_count != restored.execution_count,
            "task_id": restored.task_id,
            "run_id": run.run_id,
            "tool_call_id": calls[0].call_id,
            "customer_id": before[0],
            "recovery_state": blocked.state,
            "recovery_error": blocked.last_error_code,
        }
    finally:
        if worker.is_alive():
            worker.kill()
            worker.join(timeout=5)
        worker.close()
