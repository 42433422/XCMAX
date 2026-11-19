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


def test_retry_reuses_saved_chat_plan_without_another_model_request(monkeypatch):
    from app.application.agent_orchestrator import AgentOrchestrator, InMemoryAgentRunRepository
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    service = AgentOrchestrator(repository=InMemoryAgentRunRepository())
    plan = PlanGraph(
        plan_id="saved-chat-plan",
        intent="query",
        nodes=[
            WorkflowNode(
                node_id="query",
                tool_id="customers",
                action="query",
                params={"keyword": "synthetic"},
                risk="low",
                idempotent=True,
            )
        ],
    )
    original = service.start_run_from_plan(
        user_id="7", message="query", plan=plan, auto_execute=False
    )
    original.status = "failed"
    service.save_run(original)
    monkeypatch.setattr(
        service, "_plan", lambda *_a, **_k: pytest.fail("retry must reuse the saved plan")
    )
    retried = service.retry_run(original.run_id, requested_by="7", auto_execute=False)
    assert retried.status == "queued"
    assert retried.run_id == original.run_id
    assert retried.steps[0].step_id == original.steps[0].step_id
    assert retried.steps[0].params == {"keyword": "synthetic"}
    assert retried.metadata["plan"]["nodes"][0]["tool_id"] == "customers"


@pytest.mark.parametrize("tenant", ["target", 7])
def test_sql_tenant_filter_precedes_limit_across_streaming_batches(tmp_path, tenant):
    engine = create_engine(f"sqlite:///{tmp_path / 'tenant-list.db'}")
    factory = sessionmaker(bind=engine)
    repo = SQLAlchemyAgentRunRepository(session_factory=factory)
    expected = []
    try:
        # Desired records are older than more than two streaming batches of
        # another tenant's records belonging to the same user.
        for index in range(2):
            run = AgentRun(user_id="owner", message=f"target-{index}")
            run.metadata["runtime_context"] = {"tenant_id": tenant}
            run.metadata["task_context"] = {"task_id": f"target-{index}"}
            repo.save(run)
            expected.insert(0, run.run_id)
        with factory.begin() as db:
            for index in range(205):
                run = AgentRun(user_id="owner", message=f"other-{index}")
                run.metadata["runtime_context"] = {"tenant_id": "other"}
                run.metadata["task_context"] = {"task_id": f"other-{index}"}
                repo.save_in_session(db, run)
        legacy = AgentRun(user_id="owner", message="no tenant")
        legacy.metadata["task_context"] = {"task_id": "legacy"}
        repo.save(legacy)
        outsider = AgentRun(user_id="different-user", message="same tenant other user")
        outsider.metadata["runtime_context"] = {"tenant_id": tenant}
        outsider.metadata["task_context"] = {"task_id": "outsider"}
        repo.save(outsider)
        fresh = SQLAlchemyAgentRunRepository(session_factory=factory, auto_create=False)
        assert [
            run.run_id for run in fresh.list_recent(user_id="owner", tenant_id=str(tenant), limit=2)
        ] == expected
        assert [
            run.run_id for run in fresh.list_recent(user_id="owner", tenant_id=str(tenant), limit=1)
        ] == expected[:1]
        assert fresh.list_recent(user_id="owner", tenant_id="missing", limit=2) == []
        assert fresh.list_recent(user_id="owner", tenant_id="target", limit=0) == []
        assert [
            run_id
            for run_id, _, _ in fresh.recent_task_refs(
                user_id="owner", tenant_id=str(tenant), limit=2
            )
        ] == expected
        assert fresh.recent_task_refs(user_id="owner", tenant_id="missing", limit=2) == []
        assert fresh.recent_task_refs(user_id="owner", tenant_id=str(tenant), limit=0) == []
        assert fresh.recent_task_refs(user_id="owner", tenant_id="", limit=2) == [
            (legacy.run_id, "legacy", "")
        ]
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


def test_sql_plain_save_locks_before_reading_concurrently_returned_evidence(tmp_path, monkeypatch):
    from sqlalchemy import event

    from app.application.agent_orchestrator import chat_trace

    url = f"sqlite:///{tmp_path / 'save-receipt-race.sqlite'}"
    engines = [create_engine(url) for _ in range(2)]
    repo, writer = [
        SQLAlchemyAgentRunRepository(session_factory=sessionmaker(bind=e)) for e in engines
    ]
    original = repo.save(AgentRun(user_id="owner", message="write", status="running"))
    writer._ensure_schema()
    stale = repo.get(original.run_id)
    monkeypatch.setattr(chat_trace, "get_agent_run_repository", lambda: writer)
    injected = []

    def returned_before_write(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("UPDATE agent_runs") and not injected:
            injected.append(True)
            chat_trace.mark_chat_stream_interrupted(
                original, pending=True, reason="consumer_closed"
            )
            chat_trace.record_legacy_stream_tool_receipt(
                original, sequence=1, record={"receipt": "committed-once"}
            )

    event.listen(engines[0], "before_cursor_execute", returned_before_write)
    try:
        repo.save(stale)
        final = writer.get(original.run_id)
        assert injected == [True]
        assert final.metadata["non_retryable"] is True
        assert final.metadata["recovery"]["state"] == "manual_reconciliation_required"
        assert final.metadata["stream_tool_audit"][0]["record"]["receipt"] == "committed-once"
        assert {item.event_type for item in final.events} >= {
            "run.observation_interrupted",
            "tool.receipt_observed",
        }
    finally:
        for engine in engines:
            engine.dispose()


def test_concurrent_parent_saves_keep_child_receipts_and_reject_rebinding(tmp_path):
    import copy

    import pytest

    engine = create_engine(f"sqlite:///{tmp_path / 'handoff-parent.db'}")
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    repo = SQLAlchemyAgentRunRepository(session_factory=factory)
    parent = AgentRun(user_id="user-a", message="parent", status="running")
    parent.metadata["runtime_context"] = {"tenant_id": "tenant-a"}
    repo.save(parent)
    snapshots = [repo.get(parent.run_id), repo.get(parent.run_id)]
    barrier = threading.Barrier(2)
    receipts = {}
    for index, snapshot in enumerate(snapshots):
        child_id = f"child-{index}"
        receipt = {
            "status": "completed",
            "final_output": {"answer": index},
            "parent_task_id": parent.run_id,
            "parent_run_id": parent.run_id,
            "tenant_id": "tenant-a",
            "employee_id": f"employee-{index}",
        }
        snapshot.metadata["child_results"] = {child_id: receipt}
        receipts[child_id] = receipt

    def save(snapshot):
        independent = SQLAlchemyAgentRunRepository(session_factory=factory, auto_create=False)
        barrier.wait(timeout=10)
        independent.save(snapshot)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(save, snapshots))
        assert repo.get(parent.run_id).metadata["child_results"] == receipts
        # A stale writer cannot erase the other child's result or rewind completion.
        stale = copy.deepcopy(snapshots[0])
        stale.metadata["child_results"]["child-0"].update(status="running", final_output={})
        repo.save(stale)
        assert repo.get(parent.run_id).metadata["child_results"] == receipts
        for field, value in (
            ("tenant_id", "other"),
            ("parent_run_id", "other"),
            ("employee_id", "other"),
            ("final_output", {"answer": "changed"}),
        ):
            invalid = repo.get(parent.run_id)
            invalid.metadata["child_results"]["child-0"][field] = value
            with pytest.raises(ValueError, match="child result"):
                repo.save(invalid)
            assert repo.get(parent.run_id).metadata["child_results"] == receipts
    finally:
        engine.dispose()


def test_run_scopes_reads_json_projection_and_observes_saves(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'run-scopes.db'}")
    factory = sessionmaker(bind=engine)
    repo = SQLAlchemyAgentRunRepository(session_factory=factory)
    try:
        run = AgentRun(user_id="owner", message="first")
        run.metadata["task_context"] = {"task_id": "task-1"}
        run.metadata["runtime_context"] = {
            "tenant_id": "t1",
            "_mod_authorization": {"mod_id": "m1"},
        }
        repo.save(run)

        assert repo.list_run_scopes(user_id="owner") == {"task-1": [("owner", "t1", "m1")]}
        assert [item.run_id for item in repo.list_task_runs(user_id="owner", task_id="task-1")] == [
            run.run_id
        ]

        # 授权归属直接读取已提交状态，新的运行必须立即参与过滤。
        extra = AgentRun(user_id="owner", message="second")
        extra.metadata["task_context"] = {"task_id": "task-2"}
        extra.metadata["runtime_context"] = {"tenant_id": "t2"}
        repo.save(extra)
        scopes = repo.list_run_scopes(user_id="owner")
        assert scopes["task-2"] == [("owner", "t2", "")]
        assert scopes["task-1"] == [("owner", "t1", "m1")]
    finally:
        engine.dispose()


def _scope_run(user_id: str, task_id: str, mod_id: str) -> AgentRun:
    run = AgentRun(user_id=user_id, message=task_id)
    run.metadata["task_context"] = {"task_id": task_id}
    run.metadata["runtime_context"] = {
        "tenant_id": "tenant-1",
        "_mod_authorization": {"mod_id": mod_id},
    }
    return run


def _visible_scoped_task_ids(repo, user_id: str) -> list[str]:
    from types import SimpleNamespace

    from app.fastapi_routes.domains.agent.route_support import scoped_tasks

    principal = SimpleNamespace(
        user_id=user_id,
        tenant_id="tenant-1",
        mod_authorization={"mod_id": "allowed-mod"},
    )
    return [task.task_id for task in scoped_tasks(repo, principal=principal, limit=200)]


def test_scope_authority_isolated_across_databases(tmp_path) -> None:
    user_id = "scope-database-owner"
    engines = [create_engine(f"sqlite:///{tmp_path / name}") for name in ("a.db", "b.db")]
    try:
        first, second = [
            SQLAlchemyAgentRunRepository(session_factory=sessionmaker(bind=engine))
            for engine in engines
        ]
        first.save(_scope_run(user_id, "safe-a", "allowed-mod"))
        second.save(_scope_run(user_id, "secret-b", "other-mod"))
        assert first.list_run_scopes(user_id=user_id) == {
            "safe-a": [(user_id, "tenant-1", "allowed-mod")]
        }
        assert second.list_run_scopes(user_id=user_id) == {
            "secret-b": [(user_id, "tenant-1", "other-mod")]
        }
        assert _visible_scoped_task_ids(second, user_id) == []
    finally:
        for engine in engines:
            engine.dispose()


def test_scope_authority_refreshes_after_a_session_commit(tmp_path) -> None:
    user_id = "scope-commit-owner"
    engine = create_engine(f"sqlite:///{tmp_path / 'commit.db'}")
    factory = sessionmaker(bind=engine)
    repository = SQLAlchemyAgentRunRepository(session_factory=factory)
    try:
        repository.save(_scope_run(user_id, "safe-old", "allowed-mod"))
        with factory() as transaction:
            repository.save_in_session(
                transaction, _scope_run(user_id, "secret-after-commit", "other-mod")
            )
            transaction.flush()
            # Another connection reads the prior committed state while this
            # transaction is still open; it must not become authority after commit.
            assert repository.list_run_scopes(user_id=user_id) == {
                "safe-old": [(user_id, "tenant-1", "allowed-mod")]
            }
            transaction.commit()
        assert _visible_scoped_task_ids(repository, user_id) == ["safe-old"]
    finally:
        engine.dispose()


def test_sql_task_query_preserves_numeric_metadata_identity(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'numeric-task.db'}")
    repo = SQLAlchemyAgentRunRepository(session_factory=sessionmaker(bind=engine))
    try:
        run = _scope_run("owner", "42", "other-mod")
        run.metadata["task_context"]["task_id"] = 42
        repo.save(run)
        assert [item.run_id for item in repo.list_task_runs(user_id="owner", task_id="42")] == [
            run.run_id
        ]
        assert repo.list_task_runs(user_id="other-owner", task_id="42") == []
    finally:
        engine.dispose()


def test_sql_projection_skips_malformed_payload_without_losing_valid_runs(tmp_path) -> None:
    from app.db.models.agent import AgentRunRecord

    engine = create_engine(f"sqlite:///{tmp_path / 'malformed-payload.db'}")
    factory = sessionmaker(bind=engine)
    repo = SQLAlchemyAgentRunRepository(session_factory=factory)
    try:
        valid = _scope_run("owner", "valid", "allowed-mod")
        broken = _scope_run("owner", "broken", "other-mod")
        repo.save(valid)
        repo.save(broken)
        with factory.begin() as db:
            db.get(AgentRunRecord, broken.run_id).payload_json = "{"
        assert repo.list_run_scopes(user_id="owner") == {
            "valid": [("owner", "tenant-1", "allowed-mod")]
        }
        assert [item.run_id for item in repo.list_task_runs(user_id="owner", task_id="valid")] == [
            valid.run_id
        ]
        assert repo.recent_task_refs(user_id="owner") == [(valid.run_id, "valid", "tenant-1")]
    finally:
        engine.dispose()
