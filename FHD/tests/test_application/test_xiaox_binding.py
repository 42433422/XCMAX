from __future__ import annotations

import copy
import json
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.infrastructure.xiaox.binding import XiaoxBindingError, XiaoxBindingStore
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def make_binding(
    actor,
    *,
    runtime_config=None,
    goal_bound=True,
    completion_mode="auto",
    **context,
):
    repository = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    run = AgentRun(user_id=str(actor.user_id), message="查询并生成报告", status="running")
    run.metadata["runtime_context"] = {**actor.context, **context}
    from app.domain.task_lifecycle.agent_runtime_contract import build_goal_contract

    run.metadata["runtime_completion_mode"] = completion_mode
    if goal_bound:
        contract = build_goal_contract(run)
        run.metadata.update(runtime_goal_contract=contract, runtime_goal_digest=contract["digest"])
    repository.save(run)
    store = XiaoxBindingStore(repository)
    grant = store.create(run.run_id, runtime_config=runtime_config)
    store.update(run.run_id, lambda _run, metadata: metadata.update(deadline_at=time.time() + 60))
    return store, run, grant


def test_grants_survive_repository_reopen_and_separate_audiences(trusted_actor):
    actor = trusted_actor()
    store, run, grant = make_binding(actor)
    persisted = json.dumps(store.repository.get(run.run_id).to_dict())
    assert grant.mcp_token not in persisted
    assert grant.model_token not in persisted
    reopened = XiaoxBindingStore(SQLAlchemyAgentRunRepository(session_factory=actor.factory))
    assert reopened.authenticate(grant.mcp_token, "mcp").run_id == run.run_id
    assert reopened.authenticate(grant.model_token, "model").run_id == run.run_id
    with pytest.raises(XiaoxBindingError, match="调用通道"):
        reopened.authenticate(grant.model_token, "mcp")


def test_concurrent_coordinators_and_stale_cleanup_are_fenced(trusted_actor):
    store, run, grant = make_binding(trusted_actor())
    with pytest.raises(XiaoxBindingError) as error:
        store.create(run.run_id)
    assert error.value.code == "binding_conflict"
    generation = grant.binding.metadata["generation"]
    store.close(run.run_id, "finalizing", generation=generation, release_coordinator=False)
    with pytest.raises(XiaoxBindingError) as error:
        store.create(run.run_id)
    assert error.value.code == "binding_conflict"
    store.close(run.run_id, "waiting_user", generation=generation)
    replacement = store.create(run.run_id)
    store.close(run.run_id, "cancelled", generation=generation)
    assert store.authenticate(replacement.model_token, "model").run_id == run.run_id
    with pytest.raises(XiaoxBindingError):
        store.authenticate(grant.model_token, "model")


def test_expiry_revocation_and_runtime_changes_fail_closed(trusted_actor, monkeypatch):
    actor = trusted_actor()
    store, run, grant = make_binding(actor)
    from app.infrastructure.xiaox import binding as xiaox_binding

    monkeypatch.setattr(
        xiaox_binding.time, "time", lambda: grant.binding.metadata["expires_at"] + 1
    )
    with pytest.raises(XiaoxBindingError) as error:
        store.authenticate(grant.mcp_token)
    assert error.value.code == "token_expired"
    store.close(run.run_id)
    with pytest.raises(XiaoxBindingError):
        store.authenticate(grant.mcp_token)
    next_grant = store.create(run.run_id)
    store.close(run.run_id, generation=next_grant.binding.metadata["generation"])
    with pytest.raises(XiaoxBindingError) as error:
        store.create(run.run_id, runtime_config={"model": "another-model"})
    assert error.value.code == "runtime_changed"


def test_scope_rebuilt_for_each_request_and_reset_after_exception(trusted_actor):
    from app.infrastructure.aiopen.principal_context import current_screen_principal
    from app.infrastructure.tenant_scope import current_tenant_id, owned_tenant_scope
    from app.request_active_mod_ctx import (
        get_request_active_mod_id,
        reset_request_active_mod_id,
        set_request_active_mod_id,
    )

    store, _, grant = make_binding(trusted_actor(tenant_id=7))
    token = set_request_active_mod_id("ambient-other-mod")
    try:
        with owned_tenant_scope(999):
            with pytest.raises(RuntimeError):
                with store.scope(grant.mcp_token) as binding:
                    assert current_tenant_id() == 7
                    assert current_screen_principal().principal_id == binding.run.user_id
                    assert get_request_active_mod_id() == ""
                    raise RuntimeError("callback failed")
            assert current_tenant_id() == 999
        assert get_request_active_mod_id() == "ambient-other-mod"
    finally:
        reset_request_active_mod_id(token)


def test_disabled_actor_and_cleared_conversation_invalidate_grants(trusted_actor):
    from app.db.models import AIConversationSession
    from app.db.models.user import User
    from app.domain.shared_services.conversation_service import lock_conversation_session

    actor = trusted_actor()
    with actor.factory.begin() as db:
        lock_conversation_session(
            db, session_id="original-chat", user_id=actor.user_id, create=True
        )
    store, _, grant = make_binding(actor, conversation_id="original-chat", _conversation_revision=0)
    with actor.factory.begin() as db:
        db.query(AIConversationSession).filter_by(session_id="original-chat").update(
            {"revision": 1}
        )
    with pytest.raises(XiaoxBindingError) as error:
        store.authenticate(grant.mcp_token)
    assert error.value.code == "conversation_changed"
    other, _, other_grant = make_binding(actor)
    with actor.factory.begin() as db:
        db.get(User, actor.user_id).is_active = False
    with pytest.raises(XiaoxBindingError) as error:
        other.authenticate(other_grant.mcp_token)
    assert error.value.code == "owner_changed"


def test_effect_identity_is_server_owned_across_changed_model_call_ids(trusted_actor):
    store, run, grant = make_binding(
        trusted_actor(),
    )
    kwargs = {
        "tool_id": "customers",
        "action": "create",
        "params": {"unit_name": "fixture"},
        "read_only": False,
        "generation": grant.binding.metadata["generation"],
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(store.claim_call, run.run_id, call_id, **kwargs) for call_id in ("a", "b")
        ]
        first, second = [future.result() for future in futures]
    assert first[0]["child_task_id"] == second[0]["child_task_id"]
    assert sum(created for _, created in (first, second)) == 1
    with pytest.raises(XiaoxBindingError) as error:
        store.claim_call(run.run_id, "a", **{**kwargs, "params": {"unit_name": "different"}})
    assert error.value.code == "call_conflict"


@pytest.mark.parametrize(
    "changed",
    [None, [{"tool_id": "customers", "action": "create", "params": {"unit_name": "changed"}}]],
)
def test_goal_cannot_change_after_grant_even_after_repository_reopen(trusted_actor, changed):
    actor = trusted_actor()
    store, run, grant = make_binding(
        actor,
    )
    parent = store.repository.get(run.run_id)
    if changed is None:
        parent.metadata.pop("runtime_goal_contract")
    else:
        parent.message = "已被替换的原始目标"
    store.repository.save(parent)
    reopened = XiaoxBindingStore(SQLAlchemyAgentRunRepository(session_factory=actor.factory))
    for check in (
        lambda: reopened.authenticate(grant.mcp_token),
        lambda: reopened.receipt_snapshot(run.run_id),
        lambda: reopened.create(run.run_id),
    ):
        with pytest.raises(XiaoxBindingError) as error:
            check()
        assert error.value.code == "goal_changed"


def test_missing_goal_never_claims_an_effect(trusted_actor):
    store, run, grant = make_binding(trusted_actor(), goal_bound=False)
    options = {
        "tool_id": "customers",
        "action": "create",
        "params": {"unit_name": "fixture"},
        "read_only": False,
        "generation": grant.binding.metadata["generation"],
    }
    with pytest.raises(XiaoxBindingError) as error:
        store.claim_call(run.run_id, "unfrozen-effect", **options)
    assert error.value.code == "goal_required"
    assert store.get(run.run_id).metadata["calls"] == {}


@pytest.mark.parametrize("goal_mode", [None, "reply"])
def test_missing_goal_or_reply_mode_cannot_authorize_writes(trusted_actor, goal_mode):
    store, run, grant = make_binding(
        trusted_actor(), goal_bound=goal_mode is not None, completion_mode=goal_mode or "auto"
    )
    with pytest.raises(XiaoxBindingError) as error:
        store.claim_call(
            run.run_id,
            "unexpected-write",
            tool_id="customers",
            action="create",
            params={"unit_name": "fixture"},
            read_only=False,
            generation=grant.binding.metadata["generation"],
        )
    assert error.value.code == ("goal_required" if goal_mode is None else "goal_mismatch")
    assert store.get(run.run_id).metadata["calls"] == {}


def test_pending_cancel_blocks_new_actions_even_before_run_status_changes(trusted_actor):
    store, run, grant = make_binding(trusted_actor())
    store.repository.request_task_control(run.run_id, "cancel", requested_by=run.user_id)
    with pytest.raises(XiaoxBindingError) as error:
        store.authenticate(grant.mcp_token)
    assert error.value.code == "cancelled"


def test_child_budget_shares_model_reservations_and_settles_only_once(trusted_actor):
    store, run, grant = make_binding(
        trusted_actor(),
    )

    def budget(parent, metadata):
        parent.metadata["ai_cost_budget_units"] = 10
        parent.metadata["ai_cost_units_total"] = 2
        parent.metadata["reserved_cost_units"] = 3  # Concurrent model request's reservation.

    store.update(run.run_id, budget)
    options = {
        "tool_id": "customers",
        "action": "create",
        "params": {"unit_name": "fixture"},
        "read_only": False,
        "generation": grant.binding.metadata["generation"],
        "cost_units": 2,
    }
    call, created = store.claim_call(run.run_id, "a", **options)
    assert created and call["budget_units"] == call["reservation_units"] == 5
    assert store.get(run.run_id).run.metadata["reserved_cost_units"] == 8
    with pytest.raises(XiaoxBindingError) as error:
        store.claim_call(run.run_id, "other", **{**options, "params": {"unit_name": "another"}})
    assert error.value.code == "call_in_progress"
    store.record_call(run.run_id, "a", child_run_id="fixture-budget-child")
    receipt = {
        "task_id": call["child_task_id"],
        "run_id": "fixture-budget-child",
        "status": "completed",
        "ai_cost_units_total": 4,
    }
    for call_id in ("a", "a"):
        store.record_call(run.run_id, call_id, receipt=receipt)
    alias, created = store.claim_call(run.run_id, "new-model-call-id", **options)
    assert not created and alias["accounted_cost_units"] == 4
    store.record_call(run.run_id, "new-model-call-id", receipt=receipt)
    parent = store.get(run.run_id)
    assert parent.run.metadata["ai_cost_units_total"] == 6
    assert parent.run.metadata["reserved_cost_units"] == 3
    with pytest.raises(XiaoxBindingError) as error:
        store.claim_call(
            run.run_id, "over-budget", **{**options, "params": {"unit_name": "another"}}
        )
    assert error.value.code == "budget_exceeded"


def test_unknown_child_cost_stays_reserved_and_forbids_replay(trusted_actor):
    store, run, grant = make_binding(
        trusted_actor(),
    )
    store.update(
        run.run_id, lambda parent, metadata: parent.metadata.update(ai_cost_budget_units=10)
    )
    call, _ = store.claim_call(
        run.run_id,
        "a",
        tool_id="customers",
        action="create",
        params={},
        read_only=False,
        generation=grant.binding.metadata["generation"],
        cost_units=2,
    )
    store.record_call(
        run.run_id,
        "a",
        receipt={
            "task_id": call["child_task_id"],
            "run_id": "",
            "status": "unknown",
            "ai_cost_units_total": 3,
        },
    )
    parent = store.get(run.run_id)
    assert parent.run.metadata["ai_cost_units_total"] == 3
    assert parent.run.metadata["reserved_cost_units"] == 7
    with pytest.raises(XiaoxBindingError) as error:
        store.check_current(run.run_id)
    assert error.value.code == "reconciliation_required"


def test_real_model_admission_and_child_claim_share_one_budget(
    trusted_actor, monkeypatch, tmp_path
):
    from fastapi import HTTPException

    from app.infrastructure.billing.model_reservation import reserve_model_usage
    from app.infrastructure.xiaox.model_gateway import _claim, _finish
    from app.infrastructure.xiaox.policy import ModelRoute

    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "model-usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    route = ModelRoute(
        base_url="http://127.0.0.1:9901/v1",
        model="fixture-local",
        provider_id="local",
        upstream_vendor="fixture",
        context_window=1000,
        max_output_tokens=100,
    )
    store, run, grant = make_binding(
        trusted_actor(),
        runtime_config=route.runtime_identity(),
    )
    store.update(
        run.run_id, lambda parent, metadata: parent.metadata.update(ai_cost_budget_units=10)
    )
    _, amount = _claim(store, grant.model_token, route, "m1")
    assert store.get(run.run_id).run.metadata["reserved_cost_units"] == amount
    reserve_model_usage(
        usage_key="fixture-model-one",
        run_id=run.run_id,
        user_id=run.user_id,
        provider_id=route.provider_id,
        model=route.model,
        token_ceiling=route.context_window,
    )
    _finish(
        store,
        run.run_id,
        "m1",
        usage={"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
        usage_key="fixture-model-one",
    )
    spent = store.get(run.run_id).run.metadata["ai_cost_units_total"]
    child, _ = store.claim_call(
        run.run_id,
        "child",
        tool_id="customers",
        action="create",
        params={},
        read_only=False,
        generation=grant.binding.metadata["generation"],
        cost_units=2,
    )
    assert child["budget_units"] == 10 - spent
    with pytest.raises(HTTPException) as error:
        _claim(store, grant.model_token, route, "m2")
    assert error.value.status_code == 402
    store.record_call(
        run.run_id,
        "child",
        child_run_id="fixture-budget-child",
        receipt={
            "task_id": child["child_task_id"],
            "run_id": "fixture-budget-child",
            "status": "completed",
            "ai_cost_units_total": 2,
        },
    )
    _claim(store, grant.model_token, route, "m2")
    assert store.get(run.run_id).run.metadata["ai_cost_units_total"] == spent + 2
    assert store.get(run.run_id).run.metadata["reserved_cost_units"] == amount


def test_unscoped_admin_does_not_inherit_other_tenant_context(trusted_actor):
    from app.infrastructure.tenant_scope import current_tenant_id, owned_tenant_scope

    store, _, grant = make_binding(trusted_actor(tenant_id=None, role="admin", tier="admin"))
    with store.scope(grant.mcp_token):
        assert current_tenant_id() is None
    with owned_tenant_scope(999):
        with pytest.raises(XiaoxBindingError) as error:
            with store.scope(grant.mcp_token):
                pytest.fail("ambient tenant inherited")
        assert error.value.code == "scope_conflict"


@pytest.mark.parametrize("action", ["cancel", "pause"])
def test_native_ancestor_controls_revoke_child_callback_authority(trusted_actor, action):
    actor = trusted_actor()
    repository = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    parent = AgentRun(user_id=str(actor.user_id), message="native parent", status="running")
    parent.metadata["runtime_context"] = actor.context
    repository.save(parent)
    store, _, grant = make_binding(actor, parent_run_id=parent.run_id)
    repository.request_task_control(parent.run_id, action, requested_by=parent.user_id)
    with pytest.raises(XiaoxBindingError) as error:
        store.authenticate(grant.mcp_token)
    assert error.value.code == ("cancelled" if action == "cancel" else "paused")


def test_missing_ancestor_cannot_create_a_runtime_grant(trusted_actor):
    with pytest.raises(XiaoxBindingError) as error:
        make_binding(trusted_actor(), parent_run_id="missing-native-parent")
    assert error.value.code == "owner_changed"


@pytest.mark.parametrize("prefix", ["codex_", "xiaox_"])
def test_child_identity_alias_reuses_original_reservation(trusted_actor, prefix):
    store, run, grant = make_binding(trusted_actor())
    kwargs = dict(
        tool_id="customers",
        action="create",
        params={"unit_name": "legacy"},
        read_only=False,
        generation=grant.binding.metadata["generation"],
        cost_units=5,
    )
    first, created = store.claim_call(run.run_id, "a", **kwargs)
    assert created and first["child_task_id"].startswith("codex_")

    def intermediate_build(_run, metadata):
        original = metadata["calls"]["a"]
        original["child_task_id"] = prefix + first["child_task_id"].removeprefix("codex_")

    store.update(run.run_id, intermediate_build)
    snapshot = store.get(run.run_id)
    prior = snapshot.metadata["calls"]["a"]
    duplicate, created = store.claim_call(run.run_id, "b", **kwargs)
    assert not created and duplicate == prior
    assert store.get(run.run_id).run.metadata["reserved_cost_units"] == (
        snapshot.run.metadata["reserved_cost_units"]
    )


def test_split_child_identities_block_replay_without_mutation(trusted_actor):
    store, run, grant = make_binding(trusted_actor())
    kwargs = dict(
        tool_id="customers",
        action="create",
        params={"unit_name": "split"},
        read_only=False,
        generation=grant.binding.metadata["generation"],
    )
    first, _ = store.claim_call(run.run_id, "a", **kwargs)

    def split(_run, metadata):
        other = copy.deepcopy(first)
        other["child_task_id"] = "xiaox_" + first["child_task_id"].removeprefix("codex_")
        metadata["calls"]["b"] = other

    store.update(run.run_id, split)
    before = store.repository.get(run.run_id).to_dict()
    for call_id in ("a", "c"):
        with pytest.raises(XiaoxBindingError) as error:
            store.claim_call(run.run_id, call_id, **kwargs)
        assert error.value.code == "reconciliation_required"
        assert store.repository.get(run.run_id).to_dict() == before


@pytest.mark.parametrize("mixed", [False, True])
def test_unmigrated_binding_cannot_be_recreated_or_closed(trusted_actor, mixed):
    store, run, grant = make_binding(trusted_actor())
    legacy = store.repository.get(run.run_id)
    legacy.intent = "codex.runtime"
    legacy.metadata["runtime_type"] = "codex"
    legacy.metadata["codex_runtime"] = copy.deepcopy(legacy.metadata["xiaox_runtime"])
    if not mixed:
        legacy.metadata.pop("xiaox_runtime")
    store.repository.save(legacy)
    before = store.repository.get(run.run_id).to_dict()
    for operation in (
        lambda: store.get(run.run_id),
        lambda: store.authenticate(grant.mcp_token),
        lambda: store.create(run.run_id),
        lambda: store.close(run.run_id),
    ):
        with pytest.raises(XiaoxBindingError) as error:
            operation()
        assert error.value.code == "runtime_migration_required"
        assert store.repository.get(run.run_id).to_dict() == before


@pytest.mark.parametrize("version", [2, True, "1", None])
def test_unsupported_saved_binding_cannot_be_reissued_or_projected(trusted_actor, version):
    actor = trusted_actor()
    store, run, grant = make_binding(actor)
    store.update(run.run_id, lambda _run, metadata: metadata.update(version=version))
    reopened = XiaoxBindingStore(SQLAlchemyAgentRunRepository(session_factory=actor.factory))
    for check in (
        lambda: reopened.authenticate(grant.mcp_token),
        lambda: reopened.receipt_snapshot(run.run_id),
    ):
        with pytest.raises(XiaoxBindingError) as error:
            check()
        assert error.value.code == "runtime_contract_unsupported"
    # Stopping and reading original history remain available across upgrades.
    reopened.close(run.run_id, "interrupted")
    with pytest.raises(XiaoxBindingError) as error:
        reopened.create(run.run_id)
    assert error.value.code == "runtime_contract_unsupported"
    assert reopened.get(run.run_id).metadata["version"] == version


@pytest.mark.parametrize("change", ["revoke", "expire", "scope"])
def test_delegated_key_revocation_invalidates_both_runtime_audiences(
    trusted_actor, tmp_path, monkeypatch, change
):
    from app.application.aiopen import service
    from app.application.aiopen.runtime import ApiKeyRegistry, RuntimeState
    from app.domain.aiopen.principal import ScreenPrincipal

    actor = trusted_actor()
    now = [100.0]
    path = tmp_path / "keys.json"

    def registry():
        return ApiKeyRegistry(
            RuntimeState({}), lambda: "", lambda _: "fixture", lambda: now[0], lambda: path
        )

    issuer = registry()
    verifier = registry()
    monkeypatch.setattr(service, "_keys", verifier)
    issued = issuer.generate(
        principal=ScreenPrincipal.from_ids(actor.user_id, actor.context.get("tenant_id")),
        scopes=["capability.customers.list"],
        expires_at=200.0,
        execution_context=actor.context,
    )
    assert "execution_context" not in issued
    context = verifier.resolve_execution_context(issued["key"])
    assert context is not None
    assert verifier.permits_execution(context, "customers", "list")
    assert not verifier.permits_execution(context, "customers", "create")
    store, run, grant = make_binding(actor, **context)
    assert store.authenticate(grant.mcp_token, "mcp").run_id == run.run_id
    assert store.authenticate(grant.model_token, "model").run_id == run.run_id

    if change == "revoke":
        assert issuer.revoke(issued["key"])
    elif change == "expire":
        now[0] = 200.0
    else:
        entries = json.loads(path.read_text(encoding="utf-8"))
        entries[issued["key"]]["scopes"] = ["capability.customers.create"]
        path.write_text(json.dumps(entries), encoding="utf-8")

    assert not verifier.execution_context_current(context)
    for token, audience in ((grant.mcp_token, "mcp"), (grant.model_token, "model")):
        with pytest.raises(XiaoxBindingError) as error:
            store.authenticate(token, audience)
        assert error.value.code == "owner_changed"
    store.close(run.run_id, "waiting_user")
    with pytest.raises(XiaoxBindingError) as error:
        store.create(run.run_id)
    assert error.value.code == "owner_changed"
