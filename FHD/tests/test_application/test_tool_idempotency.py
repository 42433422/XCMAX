"""Durable tool ownership across live workers, crashes, and uncertain receipts."""

from __future__ import annotations

import multiprocessing
import os
import sqlite3

import pytest

from app.application.agent_orchestrator import tool_permission as permissions
from app.application.agent_orchestrator.run_models import AgentStep
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor

CONTEXT = {"tenant_id": "421", "task_id": "same-task", "user_id": "421"}
PARAMS = {"idempotency_key": "same-call", "name": "fixture"}


@pytest.mark.parametrize("field,value", [("user_id", "other-user"), ("mod_id", "other-mod")])
def test_replay_cannot_disclose_another_actor_or_mod_result(claims, field, value):
    context = {**CONTEXT, "mod_id": "mod-a"}
    key, replay = permissions.begin_idempotent_replay(context, "products", "create", PARAMS)
    assert replay is None
    permissions.finish_idempotent_replay(
        key, {"success": True, "data": {"private": "original-scope"}}
    )
    permissions.drop_process_idempotency_memory()
    changed_key, denied = permissions.begin_idempotent_replay(
        {**context, field: value},
        "products",
        "create",
        PARAMS,
    )
    assert changed_key == key
    assert denied["error_code"] == "idempotency_conflict" and denied["retryable"] is False
    assert "original-scope" not in str(denied)
    assert (
        permissions.begin_idempotent_replay(context, "products", "create", PARAMS)[1]["success"]
        is True
    )


def test_same_actor_and_mod_session_renewal_replays_original_effect(claims):
    context = {
        **CONTEXT,
        "_actor_authorization": {
            "user_id": "421",
            "mod_id": "mod-a",
            "session_row_id": 1,
        },
    }
    key, replay = permissions.begin_idempotent_replay(context, "products", "create", PARAMS)
    assert replay is None
    permissions.finish_idempotent_replay(key, {"success": True, "data": {"id": 7}})
    context["_actor_authorization"]["session_row_id"] = 2
    assert permissions.begin_idempotent_replay(context, "products", "create", PARAMS)[1] == {
        "success": True,
        "data": {"id": 7},
    }


@pytest.mark.parametrize(
    "output", [{"success": True, "data": {"private": "legacy"}}, {"outcome": "unknown"}]
)
def test_legacy_unbound_identity_neither_replays_nor_reclaims_effect(claims, output):
    key, replay = _begin()
    assert replay is None
    permissions.finish_idempotent_replay(key, output)
    with sqlite3.connect(claims) as conn:
        conn.execute(
            "update tool_idempotency set fingerprint = ? where scope_key = ?",
            ("legacy-params-only", key),
        )
    permissions.drop_process_idempotency_memory()
    returned_key, denied = _begin()
    assert returned_key == key and denied["error_code"] == "idempotency_scope_unverified"
    assert denied["outcome"] == "unknown" and denied["reconciliation_required"] is True
    assert denied["retryable"] is False and "legacy" not in str(denied)
    with sqlite3.connect(claims) as conn:
        assert conn.execute("select count(*) from tool_idempotency").fetchone()[0] == 1


def _begin():
    return permissions.begin_idempotent_replay(CONTEXT, "products", "create", PARAMS)


@pytest.fixture
def claims(tmp_path, monkeypatch):
    path = tmp_path / "claims.sqlite"
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(path))
    permissions.clear_idempotent_replay_for_tests()
    with sqlite3.connect(path) as conn:
        conn.execute("create table effects(id integer primary key)")
    yield path
    permissions.clear_idempotent_replay_for_tests()


def test_reconcile_turn_effect_reports_committed(claims):
    key, replay = _begin()
    assert replay is None
    permissions.finish_idempotent_replay(key, {"success": True, "data": {"ok": True}})

    result = permissions.reconcile_turn_effect(tenant_id="421", idempotency_key="same-call")

    assert result["effect"] == "committed"
    assert result["committed"] is True
    assert result["records"] == 1


def test_reconcile_turn_effect_none_without_records(claims):
    result = permissions.reconcile_turn_effect(tenant_id="421", idempotency_key="unknown-turn")

    assert result == {
        "effect": "none",
        "committed": False,
        "records": 0,
        "in_flight": 0,
        "unknown": 0,
    }


def test_reconcile_turn_effect_unknown_while_inflight(claims):
    _begin()

    result = permissions.reconcile_turn_effect(tenant_id="421", idempotency_key="same-call")

    assert result["effect"] == "unknown"
    assert result["in_flight"] == 1


def _process_claim(path, sender, barrier, release, mode):
    os.environ["XCAGI_TOOL_IDEMPOTENCY_PATH"] = str(path)
    permissions.drop_process_idempotency_memory()
    report = permissions.recover_idempotent_claims() if mode == "recover" else None
    if barrier is not None:
        barrier.wait(timeout=30)
    key, replay = _begin()
    if replay is None:
        # Deliberately no business-key uniqueness: a duplicate dispatch really writes twice.
        with sqlite3.connect(path) as conn:
            conn.execute("insert into effects default values")
    sender.send({"claimed": replay is None, "result": replay, "pid": os.getpid(), "report": report})
    sender.close()
    if replay is None and mode == "crash":
        os._exit(23)  # Side effect committed, no result receipt or Python cleanup.
    if replay is None and not release.wait(timeout=30):
        raise TimeoutError("test worker was not released")
    # A losing worker must not be able to settle the winner's claim.
    permissions.finish_idempotent_replay(key, {"success": True, "data": {"effect_id": 1}})


def _start(ctx, path, release, *, barrier=None, mode="complete"):
    receiver, sender = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_process_claim, args=(path, sender, barrier, release, mode))
    process.start()
    sender.close()
    return process, receiver


def _receive(receiver):
    assert receiver.poll(30), "worker did not report its claim"
    return receiver.recv()


def _close_workers(workers, release):
    release.set()
    for process, receiver in workers:
        process.join(timeout=10)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        receiver.close()


def _effect_count(path):
    with sqlite3.connect(path) as conn:
        return conn.execute("select count(*) from effects").fetchone()[0]


def test_two_live_processes_cannot_claim_the_same_tool_effect(claims):
    ctx = multiprocessing.get_context("spawn")
    barrier, release = ctx.Barrier(3), ctx.Event()
    workers = [_start(ctx, claims, release, barrier=barrier) for _ in range(2)]
    try:
        barrier.wait(timeout=30)
        outcomes = [_receive(receiver) for _process, receiver in workers]
        assert sum(item["claimed"] for item in outcomes) == 1
        winner = next(item for item in outcomes if item["claimed"])
        assert next(process for process, _ in workers if process.pid == winner["pid"]).is_alive()
        blocked = next(item["result"] for item in outcomes if not item["claimed"])
        assert blocked["error_code"] == "idempotency_in_progress"
        assert blocked["retryable"] is False
        assert permissions.recover_idempotent_claims()["retained_unknown"] == 1
        assert _effect_count(claims) == 1
        release.set()
        for process, _receiver in workers:
            process.join(timeout=30)
            assert process.exitcode == 0
        _key, replay = _begin()
        assert replay == {"success": True, "data": {"effect_id": 1}}
        assert _effect_count(claims) == 1
    finally:
        _close_workers(workers, release)


def test_fresh_process_retains_a_crashed_workers_committed_effect(claims):
    ctx, release = (
        multiprocessing.get_context("spawn"),
        multiprocessing.get_context("spawn").Event(),
    )
    release.set()
    workers = [_start(ctx, claims, release, mode="crash")]
    try:
        first, receiver = workers[0]
        assert _receive(receiver)["claimed"] is True
        first.join(timeout=30)
        assert first.exitcode == 23 and _effect_count(claims) == 1
        workers.append(_start(ctx, claims, release, mode="recover"))
        restarted, receiver = workers[1]
        recovered = _receive(receiver)
        restarted.join(timeout=30)
        assert restarted.exitcode == 0
        assert recovered["claimed"] is False
        assert recovered["report"] == {"cleared_unknown": 0, "retained_unknown": 1, "replayable": 0}
        assert recovered["result"]["outcome"] == "unknown"
        assert recovered["result"]["retryable"] is False
        assert _effect_count(claims) == 1
        with sqlite3.connect(claims) as conn:
            assert conn.execute(
                "select inflight, output_json from tool_idempotency"
            ).fetchone() == (1, "")
    finally:
        _close_workers(workers, release)


@pytest.mark.parametrize(
    "output",
    [
        {"success": False, "outcome": "unknown", "retryable": True},
        {"success": True, "requires_reconciliation": True},
        {"success": True, "outcome_unknown": True},
        {"success": False, "execution_status": "unknown"},
        {"success": False, "error_code": "tool_timeout_unknown"},
        {"success": False, "result": {"outputs": [{"execution_state": "unknown"}]}},
        {"status": "accepted"},
    ],
)
def test_unsettled_receipt_is_retained_across_restart(claims, output):
    key, replay = _begin()
    assert replay is None
    permissions.finish_idempotent_replay(key, output)
    permissions.drop_process_idempotency_memory()
    assert permissions.recover_idempotent_claims()["retained_unknown"] == 1
    _key, replay = _begin()
    assert replay["success"] is False
    assert replay["retryable"] is False
    if output.get("status") == "accepted":
        assert replay == {**output, "success": False, "retryable": False}
    else:
        assert replay["outcome"] == "unknown"
        assert replay["reconciliation_required"] is True
    _key, conflict = permissions.begin_idempotent_replay(
        CONTEXT, "products", "create", {**PARAMS, "name": "changed"}
    )
    assert conflict["error_code"] == "idempotency_conflict"


@pytest.mark.parametrize("backend", ["sqlite", "memory"])
def test_known_failure_releases_claim_and_success_stays_replayable(claims, monkeypatch, backend):
    if backend == "memory":
        monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", "memory")
    key, replay = _begin()
    assert replay is None
    permissions.finish_idempotent_replay(key, {"success": False, "error_code": "tool_bad_request"})
    key, replay = _begin()
    assert replay is None
    result = {"success": True, "data": {"id": 7}}
    permissions.finish_idempotent_replay(key, result)
    assert _begin()[1] == result
    assert permissions.recover_idempotent_claims()["replayable"] == 1


@pytest.mark.parametrize("output", [{"success": True}, {"success": False}, {"outcome": "unknown"}])
def test_stale_owner_cannot_finish_or_delete_another_claim(claims, output):
    key, replay = _begin()
    assert replay is None
    with sqlite3.connect(claims) as conn:
        conn.execute(
            "update tool_idempotency set owner = ? where scope_key = ?", ("another-owner", key)
        )
    with pytest.raises(RuntimeError, match="执行权已变化"):
        permissions.finish_idempotent_replay(key, output)
    with sqlite3.connect(claims) as conn:
        assert conn.execute(
            "select owner, inflight, output_json from tool_idempotency"
        ).fetchone() == ("another-owner", 1, "")


@pytest.mark.parametrize(
    "mode", ["runtime_error", "connection_error", "non_object", "invalid_contract", "empty_result"]
)
def test_executor_keeps_ambiguous_dispatch_non_replayable(claims, monkeypatch, mode):
    calls = []

    def dispatch(*_args, **_kwargs):
        calls.append(mode)
        if mode == "runtime_error":
            raise RuntimeError("fixture interrupted after dispatch")
        if mode == "connection_error":
            raise ConnectionError("fixture response lost")
        if mode == "non_object":
            return "unreadable receipt"
        if mode == "empty_result":
            return {"success": True, "data": None}
        return {"success": True, "file_name": "fixture.docx"}

    monkeypatch.setattr(
        "app.application.facades.tools_facade.execute_registered_workflow_tool", dispatch
    )
    executor = AgentToolExecutor()
    step = AgentStep(
        node_id="write",
        tool_id="generate_office_document",
        action="execute",
        params={"user_request": "fixture export", "output_format": "docx"},
    )
    context = {**CONTEXT, "idempotency_key": "uncertain-dispatch"}
    if mode == "runtime_error":
        with pytest.raises(RuntimeError, match="fixture interrupted"):
            executor.execute(step, runtime_context=context)
    else:
        assert executor.execute(step, runtime_context=context)["outcome"] == "unknown"
    replay = executor.execute(step, runtime_context=context)
    assert replay["success"] is False and replay["outcome"] == "unknown"
    assert replay["retryable"] is False
    assert calls == [mode]


@pytest.mark.parametrize(
    "failure",
    [
        408,
        429,
        500,
        503,
        "hidden_io",
        "nested_unknown",
        "generic_false",
        "spoofed_not_started",
    ],
)
def test_valid_receipt_cannot_release_or_complete_an_uncertain_effect(claims, monkeypatch, failure):
    import time

    from app.application.tool_execution_deadline import invocation_deadline

    calls = []
    with invocation_deadline(time.monotonic() + 30) as budget:

        def dispatch(*_args, **_kwargs):
            calls.append(failure)
            # This result satisfies the real ToolSpec, so output validation cannot
            # accidentally turn the regression into an unrelated schema failure.
            result = {
                "success": failure in {"hidden_io", "nested_unknown"},
                "file_name": "fixture.docx",
                "download_url": "/files/fixture.docx",
                "artifacts": [],
            }
            if isinstance(failure, int):
                result["status_code"] = failure
            elif failure == "hidden_io":
                budget.uncertain.append({"kind": "http_transport_error", "method": "POST"})
            elif failure == "nested_unknown":
                result["result"] = {"outputs": [{"outcome": "unknown"}]}
            elif failure == "spoofed_not_started":
                result.update(execution_status="not_started", retryable=True)
            with sqlite3.connect(claims) as conn:
                conn.execute("insert into effects default values")
            return result

        monkeypatch.setattr(
            "app.application.facades.tools_facade.execute_registered_workflow_tool",
            dispatch,
        )
        executor = AgentToolExecutor()
        step = AgentStep(
            node_id="write",
            tool_id="generate_office_document",
            action="execute",
            params={"user_request": "fixture export", "output_format": "docx"},
        )
        context = {**CONTEXT, "idempotency_key": "valid-uncertain-dispatch"}
        result = executor.execute(step, runtime_context=context)
    assert result["success"] is False and result["outcome"] == "unknown"
    assert result.get("error_code") != "output_schema_validation_failed"
    permissions.drop_process_idempotency_memory()
    replay = executor.execute(step, runtime_context=context)
    assert replay["success"] is False and replay["outcome"] == "unknown"
    assert replay["retryable"] is False and replay["reconciliation_required"]
    assert calls == [failure] and _effect_count(claims) == 1


@pytest.mark.parametrize(
    "marker",
    [
        {"requires_reconciliation": True},
        {"outcome_unknown": True},
        {"execution_status": "unknown"},
        {"result": {"execution_status": "timeout"}},
        {"result": {"outputs": [{"execution_state": "unknown"}]}},
        {"payload": {"final_output": {"node_outputs": {"job": {"status": "accepted"}}}}},
    ],
)
def test_first_executor_receipt_matches_durable_unknown_replay(claims, monkeypatch, marker):
    def dispatch(*_args, **_kwargs):
        with sqlite3.connect(claims) as conn:
            conn.execute("insert into effects default values")
        return {
            "success": True,
            "file_name": "fixture.docx",
            "download_url": "/api/files/fixture.docx",
            "artifacts": [],
            "request_id": "original-request",
            "action_id": "original-effect",
            **marker,
        }

    monkeypatch.setattr(
        "app.application.facades.tools_facade.execute_registered_workflow_tool",
        dispatch,
    )
    step = AgentStep(
        node_id="export",
        tool_id="generate_office_document",
        action="execute",
        params={"user_request": "fixture export", "output_format": "docx"},
    )
    context = {**CONTEXT, "idempotency_key": "unknown-export"}
    first = AgentToolExecutor().execute(step, runtime_context=context)
    assert first["success"] is False and first["outcome"] == "unknown"
    assert first["retryable"] is False and first["reconciliation_required"] is True
    assert first["request_id"] == "original-request" and first["action_id"] == "original-effect"
    for key, value in marker.items():
        assert first[key] == value

    permissions.drop_process_idempotency_memory()
    replay = AgentToolExecutor().execute(step, runtime_context=context)
    assert replay == first
    assert _effect_count(claims) == 1
    assert (
        permissions.reconcile_turn_effect(tenant_id="421", idempotency_key="unknown-export")[
            "effect"
        ]
        == "unknown"
    )
