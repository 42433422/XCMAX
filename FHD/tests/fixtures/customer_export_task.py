"""Exercise customer export through the product's durable background dispatcher."""

from __future__ import annotations

import multiprocessing
import time
from pathlib import Path

from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_dispatcher import AgentTaskDispatcher
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)
from app.application.agent_orchestrator.unified_task import create_unified_task


def run_customer_export_task(tmp_path: Path, *, context: dict, expected_ids: set[int]) -> dict:
    children_before = {child.pid for child in multiprocessing.active_children()}
    engine = create_engine(f"sqlite:///{tmp_path / 'export-task.sqlite'}")
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    runs = SQLAlchemyAgentRunRepository(session_factory=factory)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=factory)
    orchestrator = AgentOrchestrator(repository=runs)
    created = create_unified_task(
        orchestrator=orchestrator,
        user_id=context["user_id"],
        task_id=context["task_id"],
        title="后台导出客户",
        message="导出当前企业客户并生成 Excel",
        tool_id="customers",
        action="export",
        params={"keyword": "闭环指定客户甲"},
        runtime_context=context,
    )
    run = created.run
    assert run.status == "waiting_user"
    assert not run.tool_calls
    staged = orchestrator.stage_approved_run(
        run.run_id, approved_by=context["user_id"], approved_step_id=run.steps[0].step_id
    )
    assert staged is not None
    queued = queue.enqueue(staged, requested_by=context["user_id"])
    phases = {queued.state}
    dispatcher = AgentTaskDispatcher(
        execution_repository=queue, run_repository=runs, max_workers=1, poll_seconds=0.02
    )
    dispatcher.start()
    asynchronous = dispatcher.snapshot()["running"] is True
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            state = queue.get(run.run_id)
            if state is not None:
                phases.add(state.state)
                if state.state in {"succeeded", "failed", "cancelled", "timed_out"}:
                    break
            time.sleep(0.02)
    finally:
        dispatcher.stop()
        # A failed cleanup remains a failed run; reap this test's own surviving
        # worker only after observing its result so pytest can still terminate.
        for child in multiprocessing.active_children():
            if child.pid not in children_before and child.is_alive():
                child.kill()
                child.join(timeout=5)
    finished = runs.get(run.run_id)
    assert finished is not None
    # Persisted dispatcher events retain short running phases even if the export
    # finishes between two polls. They belong to this exact run, not a probe job.
    if any(event.event_type == "task.dispatched" for event in finished.events):
        phases.add("running")
    if finished.status == "completed" and "succeeded" in phases:
        phases.add("completed")
    result = finished.steps[0].output
    path = Path(str(result.get("file_path") or ""))
    file_ready = False
    if result.get("success") is True and path.is_file():
        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            rows = list(workbook.active.iter_rows(values_only=True))
            file_ready = (
                rows[0] == ("ID", "客户名称", "联系人", "电话", "地址")
                and {row[0] for row in rows[1:]} == expected_ids
                and len(rows) - 1 == len(expected_ids)
            )
        finally:
            workbook.close()
    proof = {
        "entries": [{"name": "task_center:customers.export", "async": asynchronous}],
        "phases": phases,
        "file_ready": file_ready,
        "run_id": run.run_id,
        "error": (finished.error or str(result)) if not file_ready else "",
        "file_path": str(path) if file_ready else "",
        "run": finished.to_dict(),
    }
    engine.dispose()
    return proof
