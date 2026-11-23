from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier, Event, Lock, get_ident
from types import SimpleNamespace
from typing import Any

import pytest

from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
from app.fastapi_routes.domains.agent import route_support, task_routes
from app.infrastructure.auth.agent_principal import AgentPrincipal


class _Orchestrator:
    def __init__(self, runs: list[Any]) -> None:
        self.runs = runs
        self.get_run_calls = 0

    def list_task_runs(self, *, user_id: str, task_id: str) -> list[Any]:
        return self.runs

    def get_run(self, run_id: str) -> Any:
        self.get_run_calls += 1
        return next(run for run in self.runs if run.run_id == run_id)


def _run(run_id: str, *, user_id: str = "u1", mod_id: str = "") -> Any:
    return SimpleNamespace(
        run_id=run_id,
        user_id=user_id,
        metadata={"runtime_context": {"tenant_id": "t1", "_mod_authorization": {"mod_id": mod_id}}},
    )


def _principal(mod_id: str = "") -> Any:
    return SimpleNamespace(user_id="u1", tenant_id="t1", mod_authorization={"mod_id": mod_id})


def test_task_scope_uses_listed_runs_without_refetching() -> None:
    orchestrator = _Orchestrator([_run(f"r{i}") for i in range(20)])
    task = SimpleNamespace(user_id="u1", tenant_id="t1", task_id="task-1")

    assert route_support.task_scope_matches(orchestrator, task, _principal())
    assert orchestrator.get_run_calls == 0


def test_task_scope_still_rejects_runs_bound_to_another_mod() -> None:
    orchestrator = _Orchestrator([_run("r1"), _run("r2", mod_id="other-mod")])
    task = SimpleNamespace(user_id="u1", tenant_id="t1", task_id="task-1")

    assert not route_support.task_scope_matches(orchestrator, task, _principal("my-mod"))


def test_scoped_tasks_scans_runs_once_for_the_whole_page() -> None:
    class _PagedOrchestrator(_Orchestrator):
        def __init__(self) -> None:
            super().__init__([_run("r1")])
            self.scope_calls = 0

        def list_tasks(self, *, user_id, tenant_id, limit, offset, include_archived):
            tasks = [
                SimpleNamespace(user_id="u1", tenant_id="t1", task_id=f"task-{i}")
                for i in range(150)
            ]
            return tasks[offset : offset + limit]

        def list_run_scopes(self, *, user_id: str) -> dict[str, list[tuple[str, str, str]]]:
            self.scope_calls += 1
            return {"task-0": [("u1", "t1", "")]}

        def list_task_runs(self, *, user_id: str, task_id: str) -> list[Any]:
            raise AssertionError("list_tasks 列表不应逐任务重扫运行")

    orchestrator = _PagedOrchestrator()
    result = route_support.scoped_tasks(orchestrator, principal=_principal(), limit=200)

    assert len(result) == 150
    assert orchestrator.scope_calls == 1


def _cache_principal() -> AgentPrincipal:
    return AgentPrincipal(
        user_id="u1",
        tenant_id="t1",
        actor_authorization={"session_row_id": 1, "execution_tenant_id": "t1"},
        mod_authorization={"mod_id": "my-mod", "session_row_id": 1},
    )


@pytest.fixture(autouse=True)
def _fresh_task_view_caches(monkeypatch):
    monkeypatch.setattr(task_routes, "_SNAPSHOTS", task_routes._TaskViewCache[str](1))
    monkeypatch.setattr(task_routes, "_BACKFILL_DONE", task_routes._TaskViewCache[None](60))


@pytest.mark.parametrize(
    "error_type", [None, RuntimeError, asyncio.CancelledError, KeyboardInterrupt, SystemExit]
)
def test_concurrent_snapshot_callers_share_one_builder_and_retry_failures(monkeypatch, error_type):
    repository = InMemoryAgentRunRepository()
    key = task_routes._task_view_key(repository, _cache_principal())
    start, release, looked_up = Barrier(8), Event(), Event()
    clock_lock = Lock()
    readers: set[int] = set()
    builds = []
    failure = error_type("snapshot unavailable") if error_type is not None else None

    def clock():
        with clock_lock:
            readers.add(get_ident())
            if len(readers) == 8:
                looked_up.set()
        return 10.0

    def build():
        builds.append("build")
        assert release.wait(5)
        if failure is not None:
            raise failure
        return "one snapshot"

    def read():
        start.wait(5)
        return task_routes._cached_task_snapshot(key, build)

    monkeypatch.setattr(task_routes.time, "monotonic", clock)
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(read) for _ in range(8)]
        try:
            assert looked_up.wait(5)
            assert builds == ["build"]
        finally:
            release.set()
        for future in futures:
            if failure is not None:
                with pytest.raises(type(failure), match="snapshot unavailable") as caught:
                    future.result(timeout=5)
                assert caught.value is failure
            else:
                assert future.result(timeout=5) == "one snapshot"
    assert builds == ["build"]
    if failure is not None:
        assert key not in task_routes._SNAPSHOTS._entries
        assert task_routes._cached_task_snapshot(key, lambda: "recovered") == "recovered"


def test_snapshot_ttl_starts_after_successful_build(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(task_routes.time, "monotonic", lambda: now[0])
    key = task_routes._task_view_key(InMemoryAgentRunRepository(), _cache_principal())

    def slow_build():
        now[0] = 30.0
        return "completed snapshot"

    assert task_routes._cached_task_snapshot(key, slow_build) == "completed snapshot"
    now[0] = 30.5
    assert (
        task_routes._cached_task_snapshot(key, lambda: "premature refresh") == "completed snapshot"
    )
    now[0] = 31.1
    assert task_routes._cached_task_snapshot(key, lambda: "new snapshot") == "new snapshot"


def test_snapshot_cache_separates_repository_and_complete_authorization():
    first, second = InMemoryAgentRunRepository(), InMemoryAgentRunRepository()
    principal = _cache_principal()
    contexts = [
        (first, principal),
        (second, principal),
        (first, replace(principal, actor_authorization={"session_row_id": 2})),
        (first, replace(principal, mod_authorization={"mod_id": "my-mod", "session_row_id": 2})),
    ]
    for index, (repository, identity) in enumerate(contexts):
        key = task_routes._task_view_key(repository, identity)
        assert key[0] is repository
        assert task_routes._cached_task_snapshot(key, lambda: str(index)) == str(index)


@pytest.mark.parametrize(
    "error_type", [None, asyncio.CancelledError, KeyboardInterrupt, SystemExit]
)
def test_bounded_cache_keeps_inflight_builder_until_space_is_available(monkeypatch, error_type):
    cache = task_routes._TaskViewCache[str](60, capacity=1)
    first_key, second_key = (object(), object(), "first"), (object(), object(), "second")
    first_started, release, second_lookup, second_started = Event(), Event(), Event(), Event()
    first_thread = []
    failure = error_type("builder stopped") if error_type is not None else None

    def clock():
        if first_thread and get_ident() != first_thread[0]:
            second_lookup.set()
        return 1.0

    def first_build():
        first_thread.append(get_ident())
        first_started.set()
        assert release.wait(5)
        if failure is not None:
            raise failure
        return "first"

    def second_build():
        second_started.set()
        return "second"

    monkeypatch.setattr(task_routes.time, "monotonic", clock)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(cache.get, first_key, first_build)
        assert first_started.wait(5)
        second = pool.submit(cache.get, second_key, second_build)
        try:
            assert second_lookup.wait(5)
            assert not second_started.is_set()
            assert len(cache._entries) == 1
        finally:
            release.set()
        if failure is not None:
            with pytest.raises(type(failure), match="builder stopped") as caught:
                first.result(timeout=5)
            assert caught.value is failure
        else:
            assert first.result(timeout=5) == "first"
        assert second.result(timeout=5) == "second"
    assert len(cache._entries) == 1


def _persist_run(repository, task_id, tenant="t1"):
    return repository.save(
        AgentRun(
            user_id="u1",
            message=task_id,
            metadata={
                "task_context": {"task_id": task_id},
                "runtime_context": {"tenant_id": tenant},
            },
        )
    )


@pytest.fixture(params=["memory", "sqlite"])
def legacy_store(request, tmp_path):
    if request.param == "memory":
        repository = InMemoryAgentRunRepository()
        yield repository, repository._tasks.clear
        return
    from sqlalchemy import create_engine, delete
    from sqlalchemy.orm import sessionmaker

    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.db.models.agent import AgentTaskRecord

    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-tasks.sqlite'}")
    factory = sessionmaker(bind=engine)

    def clear_tasks():
        with factory.begin() as db:
            db.execute(delete(AgentTaskRecord))

    try:
        yield SQLAlchemyAgentRunRepository(session_factory=factory), clear_tasks
    finally:
        engine.dispose()


def test_backfill_filters_tenant_before_recent_limit(legacy_store):
    repository, clear_tasks = legacy_store
    _persist_run(repository, "eligible-old-task")
    for index in range(200):
        _persist_run(repository, f"other-{index}", tenant="another-tenant")
    clear_tasks()

    task_routes._backfill_task_records(repository, _cache_principal())

    assert repository.get_task(user_id="u1", tenant_id="t1", task_id="eligible-old-task")
    assert repository.list_tasks(user_id="u1", tenant_id="another-tenant") == []


def test_backfill_marks_success_only_and_retries_failed_scans(legacy_store, monkeypatch):
    repository, clear_tasks = legacy_store
    _persist_run(repository, "legacy-task")
    clear_tasks()
    recent = repository.recent_task_refs
    calls = []

    def intermittent(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError("storage temporarily unavailable")
        return recent(**kwargs)

    monkeypatch.setattr(repository, "recent_task_refs", intermittent)
    task_routes._backfill_task_records(repository, _cache_principal())
    assert repository.get_task(user_id="u1", tenant_id="t1", task_id="legacy-task") is None
    task_routes._backfill_task_records(repository, _cache_principal())
    assert repository.get_task(user_id="u1", tenant_id="t1", task_id="legacy-task")
    task_routes._backfill_task_records(repository, _cache_principal())
    assert len(calls) == 2
    assert calls[1]["tenant_id"] == "t1"


def test_backfill_does_not_skip_another_repository_with_same_user_and_tenant():
    repositories = [InMemoryAgentRunRepository(), InMemoryAgentRunRepository()]
    for index, repository in enumerate(repositories):
        _persist_run(repository, str(index))
        repository._tasks.clear()
        task_routes._backfill_task_records(repository, _cache_principal())
        assert repository.get_task(user_id="u1", tenant_id="t1", task_id=str(index))


@pytest.mark.asyncio
@pytest.mark.parametrize("authorization", [[False], [True, False]])
async def test_cached_stream_snapshot_cannot_bypass_live_authorization(monkeypatch, authorization):
    repository = InMemoryAgentRunRepository()
    principal = _cache_principal()
    monkeypatch.setattr(task_routes, "get_agent_run_repository", lambda: repository)
    key = task_routes._task_view_key(repository, principal)
    task_routes._cached_task_snapshot(key, lambda: "private cached result")
    answers = iter(authorization)
    calls = []

    async def authorize():
        calls.append(True)
        return next(answers)

    response = await task_routes.stream_agent_tasks(
        once=True, principal=principal, authorize=authorize
    )
    body = "".join([str(part) async for part in response.body_iterator])
    assert "private cached result" not in body
    assert "task.snapshot" not in body
    assert "stream.closed" in body
    assert len(calls) == len(authorization)


@pytest.fixture
def switching_store(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository

    engines = [create_engine(f"sqlite:///{tmp_path / (name + '.sqlite')}") for name in ("a", "b")]
    factory = sessionmaker(bind=engines[0])
    repository = SQLAlchemyAgentRunRepository(session_factory=factory)
    try:
        for index, engine in enumerate(engines):
            factory.configure(bind=engine)
            _persist_run(repository, f"database-{index}-task")
        yield repository, factory, engines
    finally:
        for engine in engines:
            engine.dispose()


@pytest.mark.asyncio
async def test_same_repository_stream_separates_switched_database_snapshots(
    monkeypatch, switching_store
):
    repository, factory, engines = switching_store
    monkeypatch.setattr(task_routes, "get_agent_run_repository", lambda: repository)
    monkeypatch.setattr(task_routes, "_execution_map", lambda tasks: {})
    monkeypatch.setattr(task_routes, "_SNAPSHOTS", task_routes._TaskViewCache[str](60))
    monkeypatch.setattr(task_routes, "_STREAM_INTERVAL_SECONDS", 0)

    async def authorize():
        return True

    response = await task_routes.stream_agent_tasks(
        once=False, principal=_cache_principal(), authorize=authorize
    )
    stream = response.body_iterator
    try:
        for index in (0, 1, 0):
            factory.configure(bind=engines[index])
            body = str(await asyncio.wait_for(anext(stream), timeout=5))
            assert f"database-{index}-task" in body
            assert f"database-{1 - index}-task" not in body
    finally:
        await stream.aclose()


def test_same_repository_backfills_each_switched_database(switching_store):
    from sqlalchemy import delete

    from app.db.models.agent import AgentTaskRecord

    repository, factory, engines = switching_store
    for engine in engines:
        factory.configure(bind=engine)
        with factory.begin() as db:
            db.execute(delete(AgentTaskRecord))
    for index, engine in enumerate(engines):
        factory.configure(bind=engine)
        task_routes._backfill_task_records(repository, _cache_principal())
        assert repository.get_task(user_id="u1", tenant_id="t1", task_id=f"database-{index}-task")
