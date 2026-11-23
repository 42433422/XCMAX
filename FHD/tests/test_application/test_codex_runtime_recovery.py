"""Fault-injection regressions for runtime shutdown and lost SQL receipts."""

from __future__ import annotations

import asyncio
import copy

import pytest

from app.infrastructure.codex import CodexTransportError
from app.infrastructure.codex.binding import CodexBindingError, CodexBindingStore
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_codex_gateway import setup_gateway as setup_gateway
from tests.test_application.test_codex_runtime import Store, Transport, completed, receipt
from tests.test_application.test_codex_runtime import setup_runtime as setup_runtime


class ShutdownTransport(Transport):
    async def interrupt(self):
        # A storage outage can prevent durable revocation. Process shutdown must
        # still happen; the unknown ledger is recovered independently afterwards.
        self.store.log.append("interrupt")


def test_failed_revocation_still_interrupts_the_runtime(setup_runtime, monkeypatch):
    invoke, _ = setup_runtime
    store = Store()
    transport = ShutdownTransport(
        store,
        events=completed()[:1],
        error=CodexTransportError("codex_connection_lost", "lost", outcome_unknown=True),
    )

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("injected SQL revocation outage")

    monkeypatch.setattr(store, "close", unavailable)
    with pytest.raises(RuntimeError, match="SQL revocation outage"):
        asyncio.run(invoke(store, transport))
    assert "interrupt" in store.log
    assert store.log.index("interrupt") < store.log.index("exit")


@pytest.mark.parametrize("fail_terminal_write", [False, True])
def test_cancellation_survives_revocation_and_terminal_write_failure(
    setup_runtime, monkeypatch, fail_terminal_write
):
    invoke, _ = setup_runtime
    store = Store(rows=[receipt(status="unknown", verified=False, success=False)])
    transport = ShutdownTransport(store, events=completed()[:1], hang=True)

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("injected SQL revocation outage")

    monkeypatch.setattr(store, "close", unavailable)
    if fail_terminal_write:
        update = store.update

        def terminal_unavailable(run_id, mutation):
            candidate = copy.deepcopy(store.run)
            mutation(candidate, candidate.metadata["codex_runtime"])
            if "codex_result" in candidate.final_output:
                raise RuntimeError("injected terminal-write outage")
            return update(run_id, mutation)

        monkeypatch.setattr(store, "update", terminal_unavailable)

    async def cancel():
        task = asyncio.create_task(invoke(store, transport))
        await transport.active.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel())
    assert "interrupt" in store.log and "exit" in store.log
    if not fail_terminal_write:
        assert store.run.status == "cancelled"
        assert store.run.metadata["non_retryable"] is True
        assert store.run.final_output["codex_result"]["reconciliation_required"] is True


def test_stale_coordinator_cleanup_cannot_revoke_a_new_generation(setup_runtime):
    invoke, _ = setup_runtime
    store = Store()
    transport = ShutdownTransport(store)

    def replace_generation(event):
        if event["method"] == "turn/started":
            store.run.metadata["codex_runtime"].update(
                generation=2,
                coordinator_active=True,
                revoked=False,
                token_hashes={"model": "new-owner-grant"},
            )

    with pytest.raises(CodexBindingError, match="原运行授权已被更新"):
        asyncio.run(invoke(store, transport, completion_mode="reply", on_event=replace_generation))
    metadata = store.run.metadata["codex_runtime"]
    assert metadata["generation"] == 2 and metadata["coordinator_active"] is True
    assert metadata["revoked"] is False and metadata["token_hashes"] == {"model": "new-owner-grant"}


@pytest.mark.parametrize("commit_before_loss", [False, True])
def test_request_receipt_loss_never_replaces_the_original_outcome(
    setup_gateway, monkeypatch, commit_before_loss
):
    state = setup_gateway
    update = CodexBindingStore.update
    attempted = []

    def lose_receipt(store, run_id, mutation, **options):
        if mutation.__name__ != "finish":
            return update(store, run_id, mutation, **options)
        attempted.append(run_id)
        if commit_before_loss:
            update(store, run_id, mutation, **options)
        raise RuntimeError("injected original-request receipt loss")

    monkeypatch.setattr(CodexBindingStore, "update", lose_receipt)
    result = asyncio.run(state.invoke())
    duplicate = asyncio.run(state.invoke())
    parent = state.repository.get(result["run_id"])
    request = next(iter(parent.metadata["runtime_requests"].values()))
    assert len(state.calls) == 1 and len(attempted) == 1
    assert parent.status == "waiting_user"
    if commit_before_loss:
        assert result["exit_status"] == duplicate["exit_status"] == "waiting_user"
        assert request["result"]["output"] == "等待补充"
        assert duplicate["deduplicated"] is True
    else:
        assert result["exit_status"] == result["execution_state"] == "unknown"
        assert result["error_code"] == "runtime_persistence_uncertain"
        assert result["reconciliation_required"] is True and result["retryable"] is False
        assert "result" not in request
        assert duplicate["error_code"] == "runtime_request_in_progress"
