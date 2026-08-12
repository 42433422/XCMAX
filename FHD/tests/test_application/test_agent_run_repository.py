from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator import (
    AgentArtifact,
    AgentRun,
    AgentStep,
    LLMCall,
    MemoryReference,
    RetrievalCall,
    SQLAlchemyAgentRunRepository,
    ToolCall,
)


def test_sqlalchemy_agent_run_repository_persists_runs_across_instances(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'agent-runs.db'}")
    session_factory = sessionmaker(bind=engine)
    repo = SQLAlchemyAgentRunRepository(session_factory=session_factory)

    run = AgentRun(user_id="u1", message="查数据库产品 XG-5003")
    run.intent = "business_db_read"
    run.steps.append(
        AgentStep(
            node_id="node_1",
            tool_id="business_db",
            action="read",
            params={"keyword": "XG-5003"},
            risk="low",
            idempotent=True,
            status="completed",
            output={"success": True},
        )
    )
    run.tool_calls.append(
        ToolCall(
            step_id=run.steps[0].step_id,
            node_id="node_1",
            tool_id="business_db",
            action="read",
            params={"keyword": "XG-5003"},
            status="completed",
            output={"success": True},
            cost_units=1,
            permission="business_db.read",
            duration_ms=12,
        )
    )
    run.llm_calls.append(
        LLMCall(
            provider_id="openai_compatible",
            provider="xcauto",
            model="xcauto-account",
            prompt_tokens=2,
            completion_tokens=3,
            total_tokens=5,
            latency_ms=12.5,
            cost_units=1,
            billing_status="metered",
            billing_source="estimated_token_units",
        )
    )
    run.retrieval_calls.append(
        RetrievalCall(
            query="合同条款",
            retriever="rag",
            source="contract-v1",
            top_k=1,
            chunks=[{"chunk_index": 0, "text": "付款条款", "score": 0.9}],
            citations=[{"index": 1, "source": "contract.pdf", "chunk_index": 0}],
        )
    )
    run.memory_references.append(
        MemoryReference(
            query="上次客户偏好",
            memory_type="user_memory",
            source="user_memory_rag",
            hits=[
                {
                    "chunk_id": "mem1",
                    "content": "客户偏好先看涂料类报价",
                    "score": 0.88,
                }
            ],
            summary="【UserMemoryRAG】客户偏好先看涂料类报价",
        )
    )
    run.artifacts.append(
        AgentArtifact(
            artifact_type="excel_records",
            name="报价.xlsx",
            source="excel_analysis",
            summary="Excel 入库记录",
            fields=[{"name": "产品名称"}],
            preview={"record_count": 1},
        )
    )
    run.metadata["cost_units_total"] = 1
    run.metadata["tool_call_count"] = 1
    run.metadata["llm_call_count"] = 1
    run.metadata["llm_token_total"] = 5
    run.metadata["llm_cost_units_total"] = 1
    run.metadata["ai_cost_units_total"] = 2
    run.metadata["retrieval_call_count"] = 1
    run.metadata["retrieval_chunk_count"] = 1
    run.metadata["citation_count"] = 1
    run.metadata["memory_reference_count"] = 1
    run.metadata["memory_hit_count"] = 1
    run.metadata["artifact_count"] = 1
    run.metadata["runtime_context"] = {"tenant_id": "tenant-a"}
    run.metadata["task_context"] = {"task_id": "task-xg-5003"}
    first_event = run.add_event("run.created", "created")
    run.add_event("run.completed", "completed", {"ok": True})
    saved = repo.save(run)

    assert saved.run_id == run.run_id
    assert saved.steps[0].output["success"] is True

    restored_repo = SQLAlchemyAgentRunRepository(session_factory=session_factory)
    restored = restored_repo.get(run.run_id)

    assert restored is not None
    assert restored.run_id == run.run_id
    assert restored.intent == "business_db_read"
    assert restored.steps[0].params["keyword"] == "XG-5003"
    assert restored.tool_calls[0].tool_id == "business_db"
    assert restored.tool_calls[0].cost_units == 1
    assert restored.llm_calls[0].provider == "xcauto"
    assert restored.llm_calls[0].model == "xcauto-account"
    assert restored.llm_calls[0].total_tokens == 5
    assert restored.llm_calls[0].cost_units == 1
    assert restored.llm_calls[0].billing_status == "metered"
    assert restored.retrieval_calls[0].query == "合同条款"
    assert restored.retrieval_calls[0].source == "contract-v1"
    assert restored.retrieval_calls[0].citations[0]["source"] == "contract.pdf"
    assert restored.memory_references[0].query == "上次客户偏好"
    assert restored.memory_references[0].hits[0]["chunk_id"] == "mem1"
    assert restored.memory_references[0].summary.startswith("【UserMemoryRAG】")
    assert restored.artifacts[0].artifact_type == "excel_records"
    assert restored.artifacts[0].preview["record_count"] == 1
    assert restored.metadata["cost_units_total"] == 1
    assert restored.metadata["llm_token_total"] == 5
    assert restored.metadata["llm_cost_units_total"] == 1
    assert restored.metadata["ai_cost_units_total"] == 2
    assert restored.metadata["citation_count"] == 1
    assert restored.metadata["memory_hit_count"] == 1
    assert restored.metadata["artifact_count"] == 1
    assert [event.event_type for event in restored.events] == ["run.created", "run.completed"]

    recent = restored_repo.list_recent(user_id="u1", limit=10)
    assert [item.run_id for item in recent] == [run.run_id]

    task_runs = restored_repo.list_task_runs(user_id="u1", task_id="task-xg-5003")
    assert [item.run_id for item in task_runs] == [run.run_id]
    assert restored_repo.list_task_runs(user_id="u2", task_id="task-xg-5003") == []

    events_after_first = restored_repo.list_events(run.run_id, after_event_id=first_event.event_id)
    assert [event.event_type for event in events_after_first] == ["run.completed"]

    task = restored_repo.get_task(
        user_id="u1",
        task_id="task-xg-5003",
        tenant_id="tenant-a",
    )
    assert task is not None
    assert task.active_run_id == run.run_id
    assert task.title == run.message
    assert (
        restored_repo.get_task(
            user_id="u1",
            task_id="task-xg-5003",
            tenant_id="tenant-b",
        )
        is None
    )
    assert [
        item.task_id
        for item in restored_repo.list_tasks(
            user_id="u1",
            tenant_id="tenant-a",
        )
    ] == ["task-xg-5003"]

    command = restored_repo.request_task_control(
        run.run_id,
        "pause",
        requested_by="u1",
    )
    process_two_repo = SQLAlchemyAgentRunRepository(session_factory=session_factory)
    durable_command = process_two_repo.latest_task_control(run.run_id)
    assert durable_command is not None
    assert durable_command.command_id == command.command_id
    assert durable_command.status == "requested"
    replacement = process_two_repo.request_task_control(
        run.run_id,
        "cancel",
        requested_by="u1",
    )
    latest = restored_repo.latest_task_control(run.run_id)
    assert latest is not None
    assert latest.command_id == replacement.command_id
    assert latest.action == "cancel"
    applied = process_two_repo.mark_task_control(
        replacement.command_id,
        "applied",
        applied_at="2026-08-12T12:00:00+00:00",
    )
    assert applied is not None
    assert applied.status == "applied"

    archived = process_two_repo.archive_task(
        user_id="u1",
        task_id="task-xg-5003",
        archived_at="2026-08-12T12:01:00+00:00",
    )
    assert archived is not None
    assert archived.archived_at == "2026-08-12T12:01:00+00:00"
    assert process_two_repo.list_tasks(user_id="u1", tenant_id="tenant-a") == []
    assert (
        len(
            process_two_repo.list_tasks(
                user_id="u1",
                tenant_id="tenant-a",
                include_archived=True,
            )
        )
        == 1
    )

    tenant_b_run = AgentRun(user_id="u1", message="同标识的另一租户任务")
    tenant_b_run.metadata["runtime_context"] = {"tenant_id": "tenant-b"}
    tenant_b_run.metadata["task_context"] = {"task_id": "task-xg-5003"}
    process_two_repo.save(tenant_b_run)
    assert (
        process_two_repo.get_task(
            user_id="u1",
            task_id="task-xg-5003",
            tenant_id="tenant-a",
        )
        is not None
    )
    assert (
        process_two_repo.get_task(
            user_id="u1",
            task_id="task-xg-5003",
            tenant_id="tenant-b",
        )
        is not None
    )
    assert process_two_repo.get_task(user_id="u1", task_id="task-xg-5003") is None


def test_desktop_repository_persists_four_tasks_concurrently(tmp_path, monkeypatch) -> None:
    from app.db import _create_engine_for_url

    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")
    engine = _create_engine_for_url(f"sqlite:///{tmp_path / 'agent-runs-concurrent.db'}")
    session_factory = sessionmaker(bind=engine)
    repository = SQLAlchemyAgentRunRepository(session_factory=session_factory)

    try:
        repository._ensure_schema()
        barrier = threading.Barrier(4)

        def persist_task(index: int) -> str:
            run = AgentRun(user_id="desktop-user", message=f"并发任务 {index}")
            run.metadata["runtime_context"] = {"tenant_id": "tenant-1"}
            run.metadata["task_context"] = {
                "task_id": f"desktop-task-{index}",
                "title": f"并发任务 {index}",
            }
            barrier.wait(timeout=5)
            return repository.save(run).run_id

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(persist_task, index) for index in range(4)]
            saved_run_ids = [future.result(timeout=10) for future in futures]

        assert len(set(saved_run_ids)) == 4
        tasks = repository.list_tasks(user_id="desktop-user", tenant_id="tenant-1")
        assert {task.task_id for task in tasks} == {
            "desktop-task-0",
            "desktop-task-1",
            "desktop-task-2",
            "desktop-task-3",
        }
    finally:
        engine.dispose()
