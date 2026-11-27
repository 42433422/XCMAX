"""Account-authorized model routes remain frozen and qualified across runtime resume."""

from __future__ import annotations

import asyncio
import copy
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_runtime import gateway
from app.infrastructure.xiaox.policy import (
    CODEX_VERSION,
    QUALIFICATION_CHECKS,
    ModelRoute,
    RuntimeSettings,
    qualification_host_identity,
)
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.xiaox_qualification import synthetic_qualification
from tests.test_application.test_xiaox_gateway import (
    setup_gateway as setup_gateway,
)


def test_unqualified_or_changed_route_never_starts_runtime(setup_gateway):
    state = setup_gateway
    rejected = asyncio.run(state.invoke(settings=replace(state.settings, qualification_file=None)))
    assert rejected["error_code"] == "runtime_policy_blocked" and state.calls == []
    first = asyncio.run(state.invoke())
    changed_route = replace(state.settings.route, model="other-model")
    # A changed route must carry its own complete evidence binding.
    # Rewriting just route_identity would rightfully fail the qualification gate.
    state.settings.qualification_file.write_text(
        json.dumps(synthetic_qualification(changed_route, state.settings.qualification_file.parent))
    )
    result = asyncio.run(
        state.invoke(
            run_id=first["run_id"],
            runtime_context={**state.context, "turn_id": "answer-two"},
            settings=replace(state.settings, route=changed_route),
        )
    )
    assert result["error_code"] == "runtime_changed" and len(state.calls) == 1


def _fallback_settings(state, name="fixture-backup"):
    route = replace(state.settings.route, model=name, response_model=name)
    qualification = state.settings.qualification_file.with_name(f"{name}.json")
    qualification.write_text(json.dumps(synthetic_qualification(route, qualification.parent)))
    return replace(
        state.settings, route=route, qualification_file=qualification, authorized_fallbacks=()
    )


def test_fallback_authorization_is_persisted_before_execution_and_keeps_thread_model(setup_gateway):
    state = setup_gateway
    fallback = _fallback_settings(state)
    state.settings = replace(state.settings, authorized_fallbacks=(fallback,))
    first = asyncio.run(state.invoke())
    identities = state.settings.authorized_route_identities()
    store = state.calls[0]["binding_store"]
    parent = store.get(first["run_id"]).run
    assert parent.metadata["runtime_authorized_model_routes"] == identities
    assert (
        parent.metadata["xiaox_runtime"]["runtime_config"]["authorized_model_routes"] == identities
    )
    assert state.servers[0].state.xiaox_model_routes == (state.settings.route, fallback.route)
    assert state.servers[0].state.xiaox_model_route == state.settings.route
    store.update(
        first["run_id"],
        lambda run, _metadata: run.metadata.update(
            runtime_effective_model_route=fallback.route.identity
        ),
    )
    resumed = asyncio.run(
        state.invoke(
            run_id=first["run_id"],
            runtime_context={**state.context, "turn_id": "resume-with-fallback"},
        )
    )
    binding = store.get(first["run_id"])
    assert resumed["run_id"] == first["run_id"] and len(state.calls) == 2
    assert binding.thread_id == "thread-fixture"
    assert binding.run.metadata["runtime_effective_model_route"] == fallback.route.identity
    assert all(call["config"].model == state.settings.route.model for call in state.calls)


@pytest.mark.parametrize("change", ["remove", "reorder", "effective", "binding"])
def test_resume_cannot_change_frozen_fallback_authorization(setup_gateway, change):
    state = setup_gateway
    fallbacks = (_fallback_settings(state, "first"), _fallback_settings(state, "second"))
    state.settings = replace(state.settings, authorized_fallbacks=fallbacks)
    first = asyncio.run(state.invoke())
    if change in {"remove", "reorder"}:
        state.settings = replace(
            state.settings,
            authorized_fallbacks=fallbacks[:1]
            if change == "remove"
            else tuple(reversed(fallbacks)),
        )
    else:

        def change_binding(run, metadata):
            if change == "effective":
                run.metadata["runtime_effective_model_route"] = "unbound-route"
            else:
                metadata["runtime_config"]["authorized_model_routes"] = [
                    state.settings.route.identity
                ]

        state.calls[0]["binding_store"].update(first["run_id"], change_binding)
    denied = asyncio.run(
        state.invoke(
            run_id=first["run_id"], runtime_context={**state.context, "turn_id": "changed-fallback"}
        )
    )
    assert denied["error_code"] == "runtime_changed" and len(state.calls) == 1


@pytest.mark.parametrize("add_fallback", [False, True])
def test_legacy_task_only_migrates_its_original_single_route(setup_gateway, add_fallback):
    state = setup_gateway
    first = asyncio.run(state.invoke())
    store = state.calls[0]["binding_store"]

    def old_binding(run, metadata):
        run.metadata.pop("runtime_authorized_model_routes")
        metadata["runtime_config"].pop("authorized_model_routes")

    store.update(first["run_id"], old_binding)
    if add_fallback:
        state.settings = replace(state.settings, authorized_fallbacks=(_fallback_settings(state),))
    resumed = asyncio.run(
        state.invoke(
            run_id=first["run_id"], runtime_context={**state.context, "turn_id": "legacy-resume"}
        )
    )
    binding = store.get(first["run_id"])
    if add_fallback:
        assert resumed["error_code"] == "runtime_changed" and len(state.calls) == 1
        assert "runtime_authorized_model_routes" not in binding.run.metadata
    else:
        assert len(state.calls) == 2 and binding.thread_id == "thread-fixture"
        expected = [state.settings.route.identity]
        assert binding.run.metadata["runtime_authorized_model_routes"] == expected
        assert binding.metadata["runtime_config"]["authorized_model_routes"] == expected


def test_every_fallback_must_qualify_before_starting_the_runtime(setup_gateway):
    state = setup_gateway
    fallback = replace(_fallback_settings(state), qualification_file=None)
    state.settings = replace(state.settings, authorized_fallbacks=(fallback,))
    denied = asyncio.run(state.invoke())
    assert denied["error_code"] == "runtime_policy_blocked"
    assert state.calls == state.servers == []


def test_staging_freezes_routes_without_qualifying_or_disclosing_credentials(setup_gateway):
    state = setup_gateway
    fallback = replace(_fallback_settings(state), qualification_file=None)
    state.settings = replace(state.settings, authorized_fallbacks=(fallback,))
    staged = asyncio.run(state.invoke(start_paused=True))
    parent = state.repository.get(staged["run_id"])
    assert staged["execution_state"] == "paused"
    assert (
        parent.metadata["runtime_authorized_model_routes"]
        == state.settings.authorized_route_identities()
    )
    assert state.calls == state.servers == []


def test_resume_rechecks_route_authority_inside_the_sql_claim(setup_gateway, monkeypatch):
    state = setup_gateway
    first = asyncio.run(state.invoke())
    original = gateway.XiaoxBindingStore.update
    changed = False

    def update(store, run_id, mutate, **kwargs):
        nonlocal changed
        if mutate.__name__ == "claim" and not changed:
            changed = True
            original(
                store,
                run_id,
                lambda run, _metadata: run.metadata.update(
                    runtime_effective_model_route="unbound-route"
                ),
            )
        return original(store, run_id, mutate, **kwargs)

    monkeypatch.setattr(gateway.XiaoxBindingStore, "update", update)
    denied = asyncio.run(
        state.invoke(
            run_id=first["run_id"], runtime_context={**state.context, "turn_id": "changed-at-claim"}
        )
    )
    assert changed and denied["error_code"] == "runtime_changed"
    assert len(state.calls) == 1
