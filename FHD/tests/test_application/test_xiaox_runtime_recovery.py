"""Fault-injection regressions for runtime shutdown and lost SQL receipts."""

from __future__ import annotations

import asyncio
import copy
import json
import threading
from dataclasses import asdict

import pytest

from app.infrastructure.xiaox import XiaoxTransportError
from app.infrastructure.xiaox.binding import XiaoxBindingError, XiaoxBindingStore
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_xiaox_gateway import setup_gateway as setup_gateway
from tests.test_application.test_xiaox_runtime import Store, Transport, completed, receipt
from tests.test_application.test_xiaox_runtime import setup_runtime as setup_runtime


class ShutdownTransport(Transport):
    async def interrupt(self):
        # A storage outage can prevent durable revocation. Process shutdown must
        # still happen; the unknown ledger is recovered independently afterwards.
        self.store.log.append("interrupt")


@pytest.mark.parametrize(
    "failure_stage,uncertain", [("callback", False), ("callback", True), ("verification", False)]
)
def test_unexpected_task_error_finalizes_original_run_before_propagating(
    setup_runtime, monkeypatch, uncertain, failure_stage
):
    invoke, _ = setup_runtime
    store = Store(
        rows=[receipt(status="unknown", verified=False, success=False)] if uncertain else []
    )
    transport = Transport(store)
    failure = TypeError("injected private callback bug")
    released = []
    monkeypatch.setattr(
        "app.application.tools.mcp.registry.release_run_browser_sessions", released.append
    )

    def broken_callback(*_args, **_kwargs):
        raise failure

    if failure_stage == "verification":
        # The verifier runs after the model's successful terminal event. That
        # transport event must not skip failure finalization either.
        monkeypatch.setattr(
            "app.application.agent_runtime.goal_verifier.verify_runtime_goal", broken_callback
        )

    with pytest.raises(TypeError) as raised:
        asyncio.run(
            invoke(
                store,
                transport,
                on_event=broken_callback if failure_stage == "callback" else None,
            )
        )

    assert raised.value is failure
    metadata = store.run.metadata["xiaox_runtime"]
    assert metadata["coordinator_active"] is False
    assert metadata["revoked"] is True
    assert "active_started_at" not in metadata
    assert store.run.status == ("blocked" if uncertain else "failed")
    result = store.run.final_output["xiaox_result"]
    assert result["ok"] is False and result["runtime_completed"] is False
    assert result.get("reconciliation_required", False) is uncertain
    assert "private callback bug" not in json.dumps(result)
    if uncertain:
        assert store.run.metadata["non_retryable"] is True
        assert released == []
    else:
        assert len(released) == 1 and released[0]["run_id"] == store.run.run_id
    assert store.log.index("revoke") < store.log.index("interrupt") < store.log.index("exit")


@pytest.mark.parametrize("failure_stage", ["revocation", "snapshot", "terminal_write"])
def test_finalization_storage_failure_still_releases_owned_coordinator(
    setup_runtime, monkeypatch, failure_stage
):
    invoke, _ = setup_runtime
    store = Store()
    transport = Transport(store)
    failure = RuntimeError("injected finalization storage outage")
    close, snapshot, update = store.close, store.receipt_snapshot, store.update
    releases = []
    browsers = []
    monkeypatch.setattr(
        "app.application.tools.mcp.registry.release_run_browser_sessions", browsers.append
    )

    def close_with_failure(run_id, reason, *, generation, release_coordinator):
        releases.append(release_coordinator)
        if failure_stage == "revocation" and not release_coordinator:
            raise failure
        return close(run_id, reason, generation=generation, release_coordinator=release_coordinator)

    def snapshot_with_failure(run_id):
        if failure_stage == "snapshot" and store.run.metadata["xiaox_runtime"].get("revoked"):
            raise failure
        return snapshot(run_id)

    def update_with_failure(run_id, mutation):
        candidate = copy.deepcopy(store.run)
        mutation(candidate, candidate.metadata["xiaox_runtime"])
        if failure_stage == "terminal_write" and "xiaox_result" in candidate.final_output:
            raise failure
        return update(run_id, mutation)

    monkeypatch.setattr(store, "close", close_with_failure)
    monkeypatch.setattr(store, "receipt_snapshot", snapshot_with_failure)
    monkeypatch.setattr(store, "update", update_with_failure)
    with pytest.raises(RuntimeError) as raised:
        asyncio.run(invoke(store, transport, completion_mode="reply"))

    assert raised.value is failure
    assert releases[-1] is True
    metadata = store.run.metadata["xiaox_runtime"]
    assert metadata["coordinator_active"] is False and metadata["revoked"] is True
    assert "exit" in store.log
    if failure_stage != "revocation":
        assert "xiaox_result" not in store.run.final_output
        assert browsers == []  # No terminal receipt to authorize browser disposal.
    else:
        assert len(browsers) == 1 and browsers[0]["run_id"] == store.run.run_id


@pytest.mark.parametrize("failure_stage", ["revocation", "snapshot", "terminal_write", "interrupt"])
def test_original_callback_error_survives_finalization_storage_failure(
    setup_runtime, monkeypatch, failure_stage
):
    invoke, _ = setup_runtime
    store = Store(rows=[receipt(status="unknown", verified=False, success=False)])
    failure = TypeError("original callback failure")
    transport = ShutdownTransport(store)

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("secondary finalization storage failure")

    if failure_stage == "revocation":
        monkeypatch.setattr(store, "close", unavailable)
    elif failure_stage == "snapshot":
        monkeypatch.setattr(store, "receipt_snapshot", unavailable)
    elif failure_stage == "interrupt":

        async def broken_interrupt():
            store.log.append("interrupt")
            unavailable()

        monkeypatch.setattr(transport, "interrupt", broken_interrupt)
    else:
        update = store.update

        def terminal_unavailable(run_id, mutation):
            candidate = copy.deepcopy(store.run)
            mutation(candidate, candidate.metadata["xiaox_runtime"])
            if "xiaox_result" in candidate.final_output:
                unavailable()
            return update(run_id, mutation)

        monkeypatch.setattr(store, "update", terminal_unavailable)

    def broken_callback(_event):
        raise failure

    with pytest.raises(TypeError) as raised:
        asyncio.run(invoke(store, transport, on_event=broken_callback))
    assert raised.value is failure
    assert "interrupt" in store.log and "exit" in store.log
    if failure_stage == "revocation":
        assert store.run.final_output["xiaox_result"]["reconciliation_required"] is True
        assert store.run.metadata["non_retryable"] is True
    else:
        assert store.run.metadata["xiaox_runtime"]["coordinator_active"] is False


@pytest.mark.parametrize("fail_lease_write", [False, True])
def test_late_cancellation_during_browser_release_keeps_original_cancellation(
    setup_runtime, monkeypatch, fail_lease_write
):
    invoke, _ = setup_runtime
    store = Store()
    started, finish = threading.Event(), threading.Event()
    close = store.close

    def release_browser(_scope):
        started.set()
        assert finish.wait(5)

    def close_with_failure(run_id, reason, *, generation, release_coordinator):
        if fail_lease_write and release_coordinator:
            raise RuntimeError("injected final lease-write outage")
        return close(run_id, reason, generation=generation, release_coordinator=release_coordinator)

    monkeypatch.setattr(store, "close", close_with_failure)
    monkeypatch.setattr(
        "app.application.tools.mcp.registry.release_run_browser_sessions", release_browser
    )

    async def scenario():
        task = asyncio.create_task(invoke(store, Transport(store), completion_mode="reply"))
        try:
            assert await asyncio.to_thread(started.wait, 5)
            task.cancel("request disconnected during browser release")
            with pytest.raises(asyncio.CancelledError, match="request disconnected"):
                await task
        finally:
            finish.set()

    asyncio.run(scenario())
    assert store.run.status == "completed"
    assert store.run.final_output["xiaox_result"]["reply_completed"] is True
    assert store.run.metadata["xiaox_runtime"]["coordinator_active"] is fail_lease_write


def test_failed_revocation_still_interrupts_the_runtime(setup_runtime, monkeypatch):
    invoke, _ = setup_runtime
    store = Store()
    transport = ShutdownTransport(
        store,
        events=completed()[:1],
        error=XiaoxTransportError("xiaox_connection_lost", "lost", outcome_unknown=True),
    )

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("injected SQL revocation outage")

    monkeypatch.setattr(store, "close", unavailable)
    with pytest.raises(RuntimeError, match="SQL revocation outage"):
        asyncio.run(invoke(store, transport))
    assert "interrupt" in store.log
    assert store.log.index("interrupt") < store.log.index("exit")


@pytest.mark.parametrize("failure", [RuntimeError, TypeError])
def test_cancellation_survives_secondary_interrupt_error(setup_runtime, monkeypatch, failure):
    invoke, _ = setup_runtime
    store = Store(rows=[receipt(status="unknown", verified=False, success=False)])
    transport = ShutdownTransport(store, events=completed()[:1], hang=True)

    async def broken_interrupt():
        store.log.append("interrupt")
        raise failure("secondary interrupt failure")

    monkeypatch.setattr(transport, "interrupt", broken_interrupt)

    async def cancel():
        task = asyncio.create_task(invoke(store, transport))
        await transport.active.wait()
        task.cancel("original request cancellation")
        with pytest.raises(asyncio.CancelledError, match="original request cancellation"):
            await task

    asyncio.run(cancel())
    assert store.log.index("interrupt") < store.log.index("exit")
    metadata = store.run.metadata["xiaox_runtime"]
    assert metadata["coordinator_active"] is False and metadata["revoked"] is True
    assert metadata["runtime_status"] == store.run.status == "cancelled"
    assert store.run.metadata["non_retryable"] is True
    assert store.run.final_output["xiaox_result"]["reconciliation_required"] is True


def test_interrupt_programming_error_propagates_without_prior_failure(setup_runtime, monkeypatch):
    invoke, _ = setup_runtime
    store = Store()
    events = completed()
    events[-1]["payload"]["turn"]["status"] = "failed"
    transport = ShutdownTransport(store, events=events)
    failure = RuntimeError("original interrupt programming error")

    async def broken_interrupt():
        store.log.append("interrupt")
        raise failure

    monkeypatch.setattr(transport, "interrupt", broken_interrupt)
    with pytest.raises(RuntimeError) as caught:
        asyncio.run(invoke(store, transport))
    assert caught.value is failure
    assert "exit" in store.log
    assert store.run.status == "failed"
    assert store.run.metadata["xiaox_runtime"]["coordinator_active"] is False


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
            mutation(candidate, candidate.metadata["xiaox_runtime"])
            if "xiaox_result" in candidate.final_output:
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
        assert store.run.final_output["xiaox_result"]["reconciliation_required"] is True


def test_stale_coordinator_cleanup_cannot_revoke_a_new_generation(setup_runtime, monkeypatch):
    invoke, _ = setup_runtime
    store = Store()
    transport = ShutdownTransport(store)
    released = []
    monkeypatch.setattr(
        "app.application.tools.mcp.registry.release_run_browser_sessions", released.append
    )

    def replace_generation(event):
        if event["method"] == "turn/started":
            store.run.metadata["xiaox_runtime"].update(
                generation=2,
                coordinator_active=True,
                revoked=False,
                token_hashes={"model": "new-owner-grant"},
            )

    with pytest.raises(XiaoxBindingError, match="原运行授权已被更新"):
        asyncio.run(invoke(store, transport, completion_mode="reply", on_event=replace_generation))
    metadata = store.run.metadata["xiaox_runtime"]
    assert metadata["generation"] == 2 and metadata["coordinator_active"] is True
    assert metadata["revoked"] is False and metadata["token_hashes"] == {"model": "new-owner-grant"}
    assert released == []


@pytest.mark.parametrize("commit_before_loss", [False, True])
def test_request_receipt_loss_never_replaces_the_original_outcome(
    setup_gateway, monkeypatch, commit_before_loss
):
    state = setup_gateway
    update = XiaoxBindingStore.update
    attempted = []

    def lose_receipt(store, run_id, mutation, **options):
        if mutation.__name__ != "finish":
            return update(store, run_id, mutation, **options)
        attempted.append(run_id)
        if commit_before_loss:
            update(store, run_id, mutation, **options)
        raise OSError("injected original-request receipt loss")

    monkeypatch.setattr(XiaoxBindingStore, "update", lose_receipt)
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


@pytest.mark.parametrize("failure", [KeyError, IndexError, TypeError, AttributeError, RuntimeError])
def test_unexpected_runtime_failure_propagates_after_cleanup(setup_runtime, failure):
    invoke, _ = setup_runtime
    store = Store()
    error = failure("invalid internal runtime contract")
    transport = ShutdownTransport(store, events=completed()[:1], error=error)

    with pytest.raises(failure) as caught:
        asyncio.run(invoke(store, transport))

    assert caught.value is error
    assert "interrupt" in store.log and "exit" in store.log
    assert store.log.index("interrupt") < store.log.index("exit")


@pytest.mark.parametrize("lost_certificate_ack", [False, True])
def test_deployment_upgrade_preserves_original_waiting_request_and_thread(
    setup_gateway, monkeypatch, tmp_path, lost_certificate_ack
):
    """Synthetic probe I/O verifies admission/recovery, never live model acceptance."""
    from app.application.agent_runtime.configuration import (
        RuntimeSetupError,
        get_deployment_runtime_settings,
    )
    from app.infrastructure.xiaox import qualification
    from app.infrastructure.xiaox.policy import QUALIFICATION_CHECKS
    from tests.fixtures.xiaox_qualification import synthetic_qualification

    state = setup_gateway
    certificate = state.settings.qualification_file
    config_path = tmp_path / "deployment.json"
    deployment = {
        "route": asdict(state.settings.route),
        "runtime_root": str(tmp_path),
        "qualification_file": str(certificate),
    }
    config_path.write_text(json.dumps(deployment))
    monkeypatch.setenv("XCAGI_AGENT_RUNTIME_CONFIG", str(config_path))
    first = asyncio.run(state.invoke(settings=None))
    original = state.repository.get(first["run_id"])
    original_requests = copy.deepcopy(original.metadata["runtime_requests"])
    thread = original.metadata["xiaox_runtime"]["thread_id"]
    old = synthetic_qualification(
        state.settings.route,
        certificate.parent,
        checks=dict.fromkeys(QUALIFICATION_CHECKS[:-1], "PASS"),
    )
    certificate.write_text(json.dumps(old))
    # This scenario starts from a completed old qualification, including its
    # original ledger. Missing-ledger cases separately require explicit retry.
    qualification._write_private(
        certificate.with_name("setup-attempt.json"),
        json.dumps(
            {
                "state": "passed",
                "route_identity": old["route_identity"],
                "host_identity": old["host_identity"],
                "checks": old["checks"],
                "model_attempted": True,
            }
        ),
    )
    resume = {
        "settings": None,
        "run_id": first["run_id"],
        "runtime_context": {**state.context, "turn_id": "continue-original"},
    }
    denied = asyncio.run(state.invoke(**resume))
    assert denied["error_code"] == "runtime_policy_blocked"
    assert len(state.calls) == 1
    assert state.repository.get(first["run_id"]).to_dict() == original.to_dict()

    probes = []

    async def synthetic_probe(settings, owner_scope, probe):
        probes.append((settings.route.identity, owner_scope))
        # Only the external probe I/O is scripted. The actual qualifier must
        # independently read SQLite, check the full protocol, publish, and reread.
        first_step = {"nonce": probe.nonce, "step": 1}
        second_step = {"nonce": probe.nonce, "step": 2}
        assert probe.invoke("execute_action", first_step)["success"]
        assert probe.invoke("task_evidence", first_step)["verified"]
        probe.phase = "resumed"
        assert probe.invoke("task_evidence", first_step)["verified"]
        assert probe.invoke("execute_action", second_step)["success"]
        assert probe.invoke("task_evidence", second_step)["verified"]
        probe.models.append(
            {
                "completed": True,
                "stream_deltas": 1,
                "single_attempt": True,
                "model": settings.route.response_model,
            }
        )
        probe.network = {"denied_before_connect": True}
        probe.recovery = {
            "thread_id": "synthetic-probe-only",
            "resumed_thread_id": "synthetic-probe-only",
            "compaction": {"thread_id": "synthetic-probe-only", "turn_id": "compacted"},
            "first_process_id": 1,
            "second_process_id": 2,
        }

    monkeypatch.setattr(qualification, "_run_probe", synthetic_probe)
    if lost_certificate_ack:
        write = qualification._write_private
        failed = False

        def lost_ack(path, content):
            nonlocal failed
            write(path, content)
            if path == certificate and not failed:
                failed = True
                raise OSError("certificate write acknowledgement lost")

        monkeypatch.setattr(qualification, "_write_private", lost_ack)
        with pytest.raises(RuntimeSetupError) as failure:
            get_deployment_runtime_settings()
        assert failure.value.code == "runtime_storage_invalid"
        assert len(probes) == 1
        assert (
            json.loads(certificate.with_name("setup-attempt.json").read_text())["state"]
            == "started"
        )
    qualified = get_deployment_runtime_settings()
    assert qualified.require_qualified().identity == original.metadata["runtime_route_identity"]
    assert json.loads(certificate.read_text())["checks"] == dict.fromkeys(
        QUALIFICATION_CHECKS, "PASS"
    )
    assert len(probes) == 1
    assert state.repository.get(first["run_id"]).to_dict() == original.to_dict()
    # Replaying the original request cannot invoke its runtime or effects again.
    replay = asyncio.run(state.invoke(settings=None))
    assert replay["deduplicated"] is True and len(state.calls) == 1
    continued = asyncio.run(state.invoke(**resume))
    saved = state.repository.get(first["run_id"])
    assert continued["run_id"] == first["run_id"] and len(state.calls) == 2
    assert saved.metadata["xiaox_runtime"]["thread_id"] == thread
    for key in (
        "runtime_goal_contract",
        "runtime_goal_digest",
        "runtime_context",
        "runtime_route_identity",
    ):
        assert saved.metadata[key] == original.metadata[key]
    assert all(
        saved.metadata["runtime_requests"][key] == value for key, value in original_requests.items()
    )

    deployment["route"]["model"] = "changed-route-model"
    config_path.write_text(json.dumps(deployment))
    get_deployment_runtime_settings(retry=True)
    rejected = asyncio.run(
        state.invoke(**{**resume, "runtime_context": {**state.context, "turn_id": "route-changed"}})
    )
    assert rejected["error_code"] == "runtime_changed" and len(state.calls) == 2
    assert len(state.repository.list_recent()) == 1
