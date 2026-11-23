"""Fault-injection regressions for runtime shutdown and lost SQL receipts."""

from __future__ import annotations

import asyncio
import copy
import json
from dataclasses import asdict

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


@pytest.mark.parametrize("lost_certificate_ack", [False, True])
def test_deployment_upgrade_preserves_original_waiting_request_and_thread(
    setup_gateway, monkeypatch, tmp_path, lost_certificate_ack
):
    """Synthetic probe I/O verifies admission/recovery, never live model acceptance."""
    from app.application.agent_runtime.configuration import (
        RuntimeSetupError,
        get_deployment_runtime_settings,
    )
    from app.infrastructure.codex import qualification
    from app.infrastructure.codex.policy import QUALIFICATION_CHECKS
    from tests.fixtures.codex_qualification import synthetic_qualification

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
    thread = original.metadata["codex_runtime"]["thread_id"]
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
    assert saved.metadata["codex_runtime"]["thread_id"] == thread
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
