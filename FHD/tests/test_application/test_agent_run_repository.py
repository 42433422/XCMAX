from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
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
from app.application.agent_orchestrator import run_repository, task_execution_repository
from app.utils.deployment import durable_execution_required


def _break_sql_stores(monkeypatch: pytest.MonkeyPatch) -> None:
    def _unavailable(*args, **kwargs):
        raise RuntimeError("database down")

    monkeypatch.setattr(run_repository, "SQLAlchemyAgentRunRepository", _unavailable)
    monkeypatch.setattr(
        task_execution_repository, "SQLAlchemyTaskExecutionRepository", _unavailable
    )
    run_repository.set_agent_run_repository_for_tests(None)
    task_execution_repository.set_task_execution_repository_for_tests(None)


@pytest.fixture
def clean_durable_env(monkeypatch: pytest.MonkeyPatch):
    for name in (
        "FHD_ENV",
        "XCAGI_AGENT_RUN_REQUIRE_DURABLE",
        "XCAGI_PRODUCT_SKU",
        "TESTING",
        "XCAGI_TESTING",
    ):
        monkeypatch.delenv(name, raising=False)
    yield
    run_repository.set_agent_run_repository_for_tests(None)
    task_execution_repository.set_task_execution_repository_for_tests(None)


def test_durable_execution_required_matrix(clean_durable_env, monkeypatch) -> None:
    assert durable_execution_required() is False
    monkeypatch.setenv("XCAGI_AGENT_RUN_REQUIRE_DURABLE", "on")
    assert durable_execution_required() is True
    monkeypatch.setenv("XCAGI_AGENT_RUN_REQUIRE_DURABLE", "0")
    monkeypatch.setenv("FHD_ENV", "production")
    assert durable_execution_required() is True
    monkeypatch.setenv("FHD_ENV", "staging")
    assert durable_execution_required() is True
    monkeypatch.delenv("FHD_ENV")
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    assert durable_execution_required() is True


def test_production_refuses_memory_run_and_queue(clean_durable_env, monkeypatch) -> None:
    monkeypatch.setenv("FHD_ENV", "production")
    _break_sql_stores(monkeypatch)

    with pytest.raises(RuntimeError):
        run_repository.get_agent_run_repository()
    with pytest.raises(RuntimeError):
        task_execution_repository.get_task_execution_repository()

    assert run_repository._agent_run_repository_status["mode"] == "unavailable"
    assert task_execution_repository._task_execution_repository_status["durable"] is False


def test_enterprise_sku_refuses_memory_run_and_queue(clean_durable_env, monkeypatch) -> None:
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    _break_sql_stores(monkeypatch)

    with pytest.raises(RuntimeError):
        run_repository.get_agent_run_repository()
    with pytest.raises(RuntimeError):
        task_execution_repository.get_task_execution_repository()


def test_local_dev_falls_back_to_memory_with_non_durable_status(
    clean_durable_env, monkeypatch
) -> None:
    _break_sql_stores(monkeypatch)

    runs = run_repository.get_agent_run_repository()
    queue = task_execution_repository.get_task_execution_repository()
    assert isinstance(runs, run_repository.InMemoryAgentRunRepository)
    assert isinstance(queue, task_execution_repository.InMemoryTaskExecutionRepository)

    run_status = run_repository.get_agent_run_repository_status()
    queue_status = task_execution_repository.get_task_execution_repository_status()
    assert run_status["durable"] is False
    assert queue_status["durable"] is False
    assert "database down" in str(run_status["degraded_reason"])
    assert "database down" in str(queue_status["degraded_reason"])


def test_sql_tenant_filter_precedes_limit_across_streaming_batches(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'tenant-list.db'}")
    factory = sessionmaker(bind=engine)
    repo = SQLAlchemyAgentRunRepository(session_factory=factory)
    expected = []
    try:
        # Desired records are older than more than two streaming batches of
        # another tenant's records belonging to the same user.
        for index in range(2):
            run = AgentRun(user_id="owner", message=f"target-{index}")
            run.metadata["runtime_context"] = {"tenant_id": "target"}
            repo.save(run)
            expected.insert(0, run.run_id)
        with factory.begin() as db:
            for index in range(205):
                run = AgentRun(user_id="owner", message=f"other-{index}")
                run.metadata["runtime_context"] = {"tenant_id": "other"}
                repo.save_in_session(db, run)
        legacy = AgentRun(user_id="owner", message="no tenant")
        repo.save(legacy)
        outsider = AgentRun(user_id="different-user", message="same tenant other user")
        outsider.metadata["runtime_context"] = {"tenant_id": "target"}
        repo.save(outsider)
        fresh = SQLAlchemyAgentRunRepository(session_factory=factory, auto_create=False)
        assert [
            run.run_id for run in fresh.list_recent(user_id="owner", tenant_id="target", limit=2)
        ] == expected
        assert [
            run.run_id for run in fresh.list_recent(user_id="owner", tenant_id="target", limit=1)
        ] == expected[:1]
        assert fresh.list_recent(user_id="owner", tenant_id="missing", limit=2) == []
        assert fresh.list_recent(user_id="owner", tenant_id="target", limit=0) == []
        assert [
            run.run_id for run in fresh.list_recent(user_id="owner", tenant_id="", limit=2)
        ] == [legacy.run_id]
    finally:
        engine.dispose()


def test_sql_mod_filter_precedes_limit_across_batches(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'mod-list.db'}")
    factory = sessionmaker(bind=engine)
    repo = SQLAlchemyAgentRunRepository(session_factory=factory)
    try:
        visible = AgentRun(user_id="owner", message="visible")
        visible.metadata["runtime_context"] = {"_mod_authorization": {"mod_id": "a"}}
        repo.save(visible)
        with factory.begin() as db:
            for index in range(105):
                hidden = AgentRun(user_id="owner", message=f"hidden-{index}")
                hidden.metadata["runtime_context"] = {"_mod_authorization": {"mod_id": "b"}}
                repo.save_in_session(db, hidden)
        host = AgentRun(user_id="owner", message="host")
        repo.save(host)
        fresh = SQLAlchemyAgentRunRepository(session_factory=factory, auto_create=False)
        assert [
            run.run_id
            for run in fresh.list_recent(user_id="owner", tenant_id="", mod_id="a", limit=1)
        ] == [visible.run_id]
        assert [run.run_id for run in fresh.list_recent(user_id="owner", mod_id="", limit=1)] == [
            host.run_id
        ]
        assert fresh.list_recent(user_id="owner", mod_id="missing", limit=1) == []
    finally:
        engine.dispose()


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
    assert task.to_dict()["progress"] == task.metadata["progress"]
    assert task.to_dict()["progress"]["percent"] == 99
    assert task.to_dict()["progress"]["total_units"] == 1
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
