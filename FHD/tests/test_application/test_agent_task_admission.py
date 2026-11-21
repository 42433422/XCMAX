"""Atomic task/run admission and stale execution receipt fences."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator import AgentRun, SQLAlchemyAgentRunRepository


def _scope_run(user_id: str, task_id: str, mod_id: str) -> AgentRun:
    run = AgentRun(user_id=user_id, message=task_id)
    run.metadata["task_context"] = {"task_id": task_id}
    run.metadata["runtime_context"] = {
        "tenant_id": "tenant-1",
        "_mod_authorization": {"mod_id": mod_id},
    }
    return run


@pytest.mark.parametrize("durable", [False, True])
def test_task_projection_keeps_the_bound_run_until_a_new_attempt(tmp_path, durable):
    from app.application.agent_orchestrator import InMemoryAgentRunRepository

    engine = create_engine(f"sqlite:///{tmp_path / 'task-generations.db'}")
    factory = sessionmaker(bind=engine)
    repo = (
        SQLAlchemyAgentRunRepository(session_factory=factory)
        if durable
        else InMemoryAgentRunRepository()
    )
    first = _scope_run("owner", "same-task", "mod")
    first.status = "running"
    repo.save(first)
    competing = _scope_run("owner", "same-task", "mod")
    competing.status = "completed"
    repo.save(competing)
    try:
        current = repo.get_task(user_id="owner", task_id="same-task", tenant_id="tenant-1")
        assert (current.active_run_id, current.status, current.run_count) == (
            first.run_id,
            "running",
            1,
        )
        competing.metadata["task_context"]["attempt"] = 2
        competing.status = "running"
        repo.save(competing)
        first.status = "completed"
        late_writer = (
            SQLAlchemyAgentRunRepository(session_factory=factory, auto_create=False)
            if durable
            else repo
        )
        late_writer.save(first)
        current = repo.get_task(user_id="owner", task_id="same-task", tenant_id="tenant-1")
        assert (current.active_run_id, current.attempt, current.run_count) == (
            competing.run_id,
            2,
            2,
        )
    finally:
        engine.dispose()


@pytest.mark.parametrize("conflict", ["", "params", "mod"])
def test_unified_task_concurrent_admission_uses_one_complete_sql_record(
    tmp_path, monkeypatch, conflict
):
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.unified_task import (
        UnifiedTaskConflictError,
        create_unified_task,
    )
    from app.db.models.agent import AgentRunRecord, AgentTaskRecord

    engine = create_engine(f"sqlite:///{tmp_path / 'admission.db'}")
    factory = sessionmaker(bind=engine)
    repo = SQLAlchemyAgentRunRepository(session_factory=factory)
    repo._ensure_schema()
    barrier = threading.Barrier(2)
    original = AgentOrchestrator.start_task_from_plan

    def prepare(service, **kwargs):
        barrier.wait(timeout=10)
        return original(service, **kwargs)

    monkeypatch.setattr(AgentOrchestrator, "start_task_from_plan", prepare)

    def submit(index):
        try:
            return create_unified_task(
                orchestrator=AgentOrchestrator(
                    repository=SQLAlchemyAgentRunRepository(
                        session_factory=factory, auto_create=False
                    )
                ),
                user_id="owner",
                task_id="shared-task",
                title="query",
                message="query",
                tool_id="customers",
                action="query",
                params={"keyword": str(index if conflict == "params" else 0)},
                runtime_context={
                    "tenant_id": "tenant-a",
                    "_mod_authorization": {"mod_id": str(index if conflict == "mod" else 0)},
                },
            )
        except UnifiedTaskConflictError as exc:
            return exc

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit, (0, 1)))
        successful = [result for result in results if not isinstance(result, Exception)]
        assert len(successful) == (1 if conflict else 2)
        assert len({result.run.run_id for result in successful}) == 1
        assert sum(not result.deduplicated for result in successful) == 1
        with factory() as db:
            assert db.query(AgentRunRecord).count() == 1
            task = db.query(AgentTaskRecord).one()
            assert task.active_run_id == successful[0].run.run_id
            assert task.status == "waiting_user"
        assert successful[0].run.metadata["task_request_fingerprint"]
    finally:
        engine.dispose()


@pytest.mark.parametrize("initial_only", [True, False])
def test_task_admission_rolls_back_identity_if_run_persistence_fails(
    tmp_path, monkeypatch, initial_only
):
    from app.db.models.agent import AgentRunRecord, AgentTaskRecord

    engine = create_engine(f"sqlite:///{tmp_path / 'admission-rollback.db'}")
    factory = sessionmaker(bind=engine)
    repo = SQLAlchemyAgentRunRepository(session_factory=factory)
    original = repo.save_in_session

    def fail_after_save(db, run):
        original(db, run)
        db.flush()
        raise RuntimeError("injected commit failure")

    run = _scope_run("owner", "atomic-task", "mod")
    monkeypatch.setattr(repo, "save_in_session", fail_after_save)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            repo.create_task_run(run, initial_only=initial_only)
        with factory() as db:
            assert db.query(AgentRunRecord).count() == db.query(AgentTaskRecord).count() == 0
    finally:
        engine.dispose()


@pytest.mark.parametrize("terminal", ["completed", "failed", "cancelled", "rejected", "unknown"])
@pytest.mark.parametrize("durable", [False, True])
def test_late_run_saves_cannot_reopen_or_replace_a_protected_outcome(tmp_path, terminal, durable):
    import copy

    from app.application.agent_orchestrator import InMemoryAgentRunRepository

    engine = create_engine(f"sqlite:///{tmp_path / 'terminal.db'}")
    repo = (
        SQLAlchemyAgentRunRepository(session_factory=sessionmaker(bind=engine))
        if durable
        else InMemoryAgentRunRepository()
    )
    run = _scope_run("owner", "finished-task", "mod")
    run.status = terminal
    if terminal == "unknown":
        run.metadata["non_retryable"] = True
    run.final_output = {"answer": "committed"}
    repo.save(run)
    try:
        for late_status in (
            "running",
            "waiting_user",
            "failed" if terminal == "completed" else "completed",
        ):
            stale = copy.deepcopy(run)
            stale.status, stale.final_output = late_status, {"answer": "stale"}
            returned = repo.save(stale)
            current = repo.get_task(user_id="owner", task_id="finished-task", tenant_id="tenant-1")
            assert current.status == returned.status == terminal
            assert returned.final_output["answer"] == "committed"
    finally:
        engine.dispose()


@pytest.mark.parametrize("durable", [False, True])
def test_planning_generation_requires_cas_and_rejects_late_saves(tmp_path, durable):
    import copy

    from app.application.agent_orchestrator import AgentStep, InMemoryAgentRunRepository
    from app.application.agent_orchestrator.business_action_ledger import canonical_hash
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, plan_to_dict

    engine = create_engine(f"sqlite:///{tmp_path / 'planning-generation.db'}")
    factory = sessionmaker(bind=engine)
    repo = (
        SQLAlchemyAgentRunRepository(session_factory=factory)
        if durable
        else InMemoryAgentRunRepository()
    )
    waiting = _scope_run("owner", "planning-task", "mod")
    question = {"question": "Which scope?", "clarification": {"reason": "planning_scope"}}
    plan = PlanGraph(
        plan_id="planning-original",
        intent="query",
        metadata={"planning_clarification": True},
        nodes=[WorkflowNode("scope", "clarify", "ask", params=question)],
    )
    waiting.status, waiting.plan_id = "waiting_user", plan.plan_id
    waiting.steps = [AgentStep("scope", "clarify", "ask", params=question, status="waiting_user")]
    waiting.metadata["plan"] = plan_to_dict(plan)
    previous = repo.save(waiting)
    replacement = copy.deepcopy(previous)
    replacement.status = "running"
    replacement.steps = [AgentStep("read", "print", "list", idempotent=True)]
    replacement.metadata["plan"] = plan_to_dict(
        PlanGraph(
            plan_id=plan.plan_id, intent="query", nodes=[WorkflowNode("read", "print", "list")]
        )
    )
    replacement.metadata["runtime_context"]["_planning_clarification_snapshot"] = canonical_hash(
        previous.to_dict()
    )
    replacement.add_event(
        "run.clarification_resumed",
        "scope answered",
        {
            "kind": "planning_scope",
            "step_id": previous.steps[0].step_id,
        },
    )
    try:
        with pytest.raises(ValueError, match="planning generation"):
            repo.save(copy.deepcopy(replacement))
        invalid = copy.deepcopy(replacement)
        invalid.metadata["runtime_context"]["_planning_clarification_snapshot"] = "wrong-snapshot"
        with pytest.raises(ValueError, match="planning generation"):
            repo.save_if_unchanged(invalid, previous)
        assert repo.get(previous.run_id) == previous
        assert repo.save_if_unchanged(replacement, previous)
        current = repo.get(previous.run_id)
        assert [step.tool_id for step in current.steps] == ["print"]
        current.status, current.steps[0].status = "completed", "completed"
        current.steps[0].output = {"success": True, "receipt": "committed"}
        completed = repo.save(current)
        writer = (
            SQLAlchemyAgentRunRepository(session_factory=factory, auto_create=False)
            if durable
            else repo
        )
        with pytest.raises(ValueError, match="planning generation"):
            writer.save(previous)
        assert repo.get(previous.run_id) == completed
        # Mutable context changes within the committed generation cannot bypass terminal receipts.
        late = copy.deepcopy(completed)
        late.metadata["runtime_context"]["turn_id"] = "late-observer"
        late.status, late.steps[0].status = "waiting_user", "waiting_user"
        late.steps[0].output = {}
        saved = writer.save(late)
        assert saved.status == "completed"
        assert saved.steps[0].output == completed.steps[0].output
    finally:
        engine.dispose()


@pytest.mark.parametrize("durable", [False, True])
def test_task_read_acknowledgement_cannot_replace_a_new_attempt(tmp_path, durable):
    from app.application.agent_orchestrator import InMemoryAgentRunRepository

    engine = create_engine(f"sqlite:///{tmp_path / 'read-ack.db'}")
    factory = sessionmaker(bind=engine)
    repo = (
        SQLAlchemyAgentRunRepository(session_factory=factory)
        if durable
        else InMemoryAgentRunRepository()
    )
    original = _scope_run("owner", "read-task", "mod")
    original.status = "completed"
    repo.save(original)
    task = repo.get_task(user_id="owner", task_id="read-task", tenant_id="tenant-1")
    newer = _scope_run("owner", "read-task", "mod")
    newer.status = "waiting_user"
    newer.metadata["task_context"]["attempt"] = 2
    repo.save(newer)
    task.attention_state = ""
    task.metadata["read_at"] = "stale acknowledgement"
    writer = (
        SQLAlchemyAgentRunRepository(session_factory=factory, auto_create=False)
        if durable
        else repo
    )
    try:
        returned = writer.save_task(task)
        assert (returned.active_run_id, returned.status, returned.attention_state) == (
            newer.run_id,
            "waiting_user",
            "approval_required",
        )
        assert "read_at" not in returned.metadata
    finally:
        engine.dispose()


@pytest.mark.parametrize("planning_clarification", [False, True])
def test_prepared_task_is_not_persisted_or_executable(planning_clarification):
    from app.application.agent_orchestrator import AgentOrchestrator, InMemoryAgentRunRepository
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    repo = InMemoryAgentRunRepository()
    service = AgentOrchestrator(repository=repo)
    kwargs = {
        "user_id": "owner",
        "message": "query",
        "plan": PlanGraph(
            plan_id="prepared",
            intent="query",
            metadata={"planning_clarification": True} if planning_clarification else {},
            nodes=[
                (
                    WorkflowNode(
                        node_id="scope",
                        tool_id="clarify",
                        action="ask",
                        params={
                            "question": "Which scope?",
                            "clarification": {"reason": "planning_scope"},
                        },
                    )
                    if planning_clarification
                    else WorkflowNode(
                        node_id="query",
                        tool_id="customers",
                        action="query",
                        params={"keyword": "x"},
                    )
                )
            ],
        ),
        "persist": False,
    }
    with pytest.raises(ValueError, match="未持久化"):
        service.start_run_from_plan(**kwargs)
    prepared = service.start_task_from_plan(**kwargs)
    assert prepared.status == "waiting_user"
    assert repo.get(prepared.run_id) is None
    assert repo.list_tasks(user_id="owner") == []


@pytest.mark.parametrize("durable", [False, True])
def test_exact_run_admission_does_not_create_a_second_task_or_save_a_losing_snapshot(
    tmp_path, durable
):
    import copy

    from app.application.agent_orchestrator import InMemoryAgentRunRepository

    engine = create_engine(f"sqlite:///{tmp_path / 'exact-admission.sqlite'}")
    repository = (
        SQLAlchemyAgentRunRepository(session_factory=sessionmaker(bind=engine))
        if durable
        else InMemoryAgentRunRepository()
    )
    first, created = repository.create_task_run(
        _scope_run("owner", "first-task", "mod"), initial_only=False
    )
    assert created
    second = copy.deepcopy(first)
    second.message = "losing snapshot"
    second.metadata["task_context"]["task_id"] = "losing-task"
    try:
        returned, created = repository.create_task_run(second, initial_only=False)
        assert not created and returned.to_dict() == first.to_dict()
        assert repository.get(first.run_id).to_dict() == first.to_dict()
        assert (
            repository.get_task(user_id="owner", task_id="losing-task", tenant_id="tenant-1")
            is None
        )
    finally:
        engine.dispose()


@pytest.mark.parametrize("scope", ["standalone", "continuation", "child"])
def test_legacy_plan_admission_executes_once_across_sql_sessions(tmp_path, monkeypatch, scope):
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.task_context import apply_task_context
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
    from app.db.models.agent import AgentRunRecord, AgentTaskRecord

    engine = create_engine(f"sqlite:///{tmp_path / 'plan-race.sqlite'}")
    factory = sessionmaker(bind=engine)
    setup = SQLAlchemyAgentRunRepository(session_factory=factory)
    setup._ensure_schema()
    from app.infrastructure.workflow.checkpoint_bridge import open_run_checkpointer

    with open_run_checkpointer(setup):
        pass
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE observed_effects (run_id TEXT NOT NULL)")
    context = {"tenant_id": "12", "session_id": "same-session"}
    parent = None
    if scope != "standalone":
        context["task_id"] = "existing-task"
        parent = AgentRun(user_id="owner", message="parent", status="completed")
        parent.metadata["runtime_context"] = dict(context)
        apply_task_context(parent, context)
        setup.save(parent)
        context.update(parent_run_id=parent.run_id, root_run_id=parent.run_id)
        context["task_attempt"] = 2 if scope == "continuation" else 1
    plan = PlanGraph(
        plan_id="same-plan",
        intent="query",
        nodes=[
            WorkflowNode(
                node_id="query",
                tool_id="business_db",
                action="read",
                params={"entity": "products"},
                risk="low",
                idempotent=True,
            )
        ],
    )
    barrier = threading.Barrier(2)
    second_effect = threading.Event()
    apply_plan = AgentOrchestrator._apply_plan

    def prepare(service, *args, **kwargs):
        result = apply_plan(service, *args, **kwargs)
        barrier.wait(timeout=10)  # Both independent repositories observed the run as absent.
        return result

    class ObservedTool:
        def execute(self, step, *, runtime_context):
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "INSERT INTO observed_effects (run_id) VALUES (?)", (runtime_context["run_id"],)
                )
                if connection.exec_driver_sql("SELECT count(*) FROM observed_effects").scalar() > 1:
                    second_effect.set()
            second_effect.wait(timeout=2)
            return {"success": True, "data": []}

    monkeypatch.setattr(AgentOrchestrator, "_apply_plan", prepare)

    def submit(_):
        service = AgentOrchestrator(
            repository=SQLAlchemyAgentRunRepository(session_factory=factory, auto_create=False),
            tool_executor=ObservedTool(),
        )
        return service.start_run_from_plan(
            user_id="owner", message="query", plan=plan, runtime_context=context
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            runs = list(pool.map(submit, (0, 1)))
        assert len({run.run_id for run in runs}) == 1
        with engine.connect() as connection:
            effects = connection.exec_driver_sql("SELECT run_id FROM observed_effects").all()
        assert [row[0] for row in effects] == [runs[0].run_id], [
            (run.status, run.error, [(step.status, step.error, step.output) for step in run.steps])
            for run in runs
        ]
        with factory() as db:
            assert db.query(AgentRunRecord).count() == (1 if parent is None else 2)
            task = db.query(AgentTaskRecord).one()
            assert task.active_run_id == (parent.run_id if scope == "child" else runs[0].run_id)
            assert task.attempt == (2 if scope == "continuation" else 1)
        assert setup.get(runs[0].run_id).status == "completed"
    finally:
        engine.dispose()
