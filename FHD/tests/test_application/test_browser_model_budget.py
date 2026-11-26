"""Browser actions share Xiaox's durable model budget and conversation authority."""

from __future__ import annotations

import json
import secrets
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import run_repository
from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.db.models import AIConversationSession
from app.domain.shared_services.conversation_service import lock_conversation_session
from app.domain.task_lifecycle.agent_runtime_contract import build_goal_contract
from app.infrastructure.billing import model_usage as ledger
from app.infrastructure.xiaox.binding import XiaoxBindingError, XiaoxBindingStore
from app.infrastructure.xiaox.model_gateway import MODEL_PATH, router
from app.infrastructure.xiaox.policy import ModelRoute
from app.infrastructure.xiaox.tools import XiaoxToolBridge
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def browser_model(trusted_actor, monkeypatch, tmp_path, request):
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    monkeypatch.setenv("XCAGI_REQUIRE_REDIS_RATE_LIMIT", "0")
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "model-usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "local")
    monkeypatch.setenv("MODEL_USAGE_WALLET_REQUIRED", "1")
    monkeypatch.setenv("XCAGI_BROWSER_ALLOWED_ORIGINS", '{"7": ["https://example.com"]}')
    monkeypatch.setattr(
        "app.application.agent_orchestrator.artifact_files.get_app_data_dir", lambda: str(tmp_path)
    )
    monkeypatch.setattr("app.utils.path_io.path_utils.get_app_data_dir", lambda: str(tmp_path))
    actor = trusted_actor(user_id=71, permissions=["tool.browser.observe"])
    context = actor.context
    credential = None
    if getattr(request, "param", None):
        from app.application.aiopen import service
        from app.application.aiopen.runtime import ApiKeyRegistry, RuntimeState
        from app.domain.aiopen.principal import ScreenPrincipal

        clock = [time.time()]
        key_path = tmp_path / "api-keys.json"
        keys = ApiKeyRegistry(
            RuntimeState({}),
            lambda: "",
            secrets.token_hex,
            lambda: clock[0],
            storage=lambda: key_path,
        )
        monkeypatch.setattr(service, "_keys", keys)
        issued = keys.generate(
            principal=ScreenPrincipal(str(actor.user_id), str(actor.tenant_id)),
            scopes=["capability.browser.observe"],
            expires_at=clock[0] + 60,
            execution_context=actor.context,
        )
        context = keys.resolve_execution_context(issued["key"])
        assert context is not None
        credential = SimpleNamespace(
            registry=keys, key=issued["key"], clock=clock, path=key_path, condition=request.param
        )
    with actor.factory.begin() as db:
        lock_conversation_session(
            db, session_id="browser-budget-chat", user_id=actor.user_id, create=True
        )
    parent = AgentRun(str(actor.user_id), "读取页面结果", status="running")
    parent.metadata.update(
        runtime_type="xiaox",
        runtime_context={
            **context,
            "conversation_id": "browser-budget-chat",
            "_conversation_revision": 0,
        },
        ai_cost_budget_units=100,
    )
    contract = build_goal_contract(parent)
    parent.metadata.update(runtime_goal_contract=contract, runtime_goal_digest=contract["digest"])
    repository = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    repository.save(parent)
    monkeypatch.setattr(run_repository, "_agent_run_repository", repository)
    route = ModelRoute(
        base_url="http://127.0.0.1:9876/v1",
        model="browser-model",
        provider_id="enterprise",
        upstream_vendor="fixture",
        context_window=32000,
        max_output_tokens=2048,
    )
    store = XiaoxBindingStore(repository)
    grant = store.create(parent.run_id, runtime_config=route.runtime_identity())
    store.update(
        parent.run_id, lambda _run, metadata: metadata.update(deadline_at=time.time() + 60)
    )
    ledger.set_model_wallet_balance(parent.user_id, 100)
    state = SimpleNamespace(
        actor=actor,
        parent=parent,
        repository=repository,
        store=store,
        grant=grant,
        route=route,
        credential=credential,
        model_requests=[],
        browser_requests=[],
        on_model=None,
        response={
            "id": "browser-response",
            "model": route.response_model,
            "status": "completed",
            "output": [],
            "usage": {"input_tokens": 1500, "output_tokens": 500, "total_tokens": 2000},
        },
    )

    def model(request):
        # Observe the real wallet debit before the first byte reaches the provider.
        assert ledger.get_model_wallet(parent.user_id)["balance_units"] == state.expected_balance
        state.model_requests.append(request)
        if state.on_model:
            state.on_model()
        return httpx.Response(200, json=state.response)

    async def browser(plan, *, before_action, **options):
        assert plan["observe"] is True
        assert options["allowed_origins"] == frozenset({"https://example.com"})
        before_action()
        state.browser_requests.append(plan)
        return {"success": True, "outcome": "succeeded", "snapshot": "页面已加载", "artifacts": []}

    # Only external I/O is synthetic; principal, schema, SQL claims and billing are real.
    monkeypatch.setattr("app.infrastructure.browser.runtime.execute_browser_plan", browser)
    bridge = XiaoxToolBridge(
        store,
        AgentOrchestrator(
            repository=repository,
            tool_executor=SimpleNamespace(execute=AgentToolExecutor().execute),
        ),
    )
    capability = bridge.invoke(
        grant.mcp_token, "capability_describe", {"tool_id": "browser", "action": "observe"}
    )["capability"]

    def observe(call_id="read-original-browser-page"):
        return bridge.invoke(
            grant.mcp_token,
            "execute_action",
            {
                "tool_id": "browser",
                "action": "observe",
                "params": {"url": "https://example.com/"},
                "call_id": call_id,
                "schema_digest": capability["schema_digest"],
            },
        )

    app = FastAPI()
    app.state.xiaox_binding_store = store
    app.state.xiaox_model_route = route
    app.state.xiaox_run_id = parent.run_id
    app.state.xiaox_http_client_factory = lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(model), **kwargs
    )
    app.include_router(router)
    state.observe = observe
    with TestClient(app) as client:

        def post(**body):
            state.expected_balance = ledger.get_model_wallet(parent.user_id)["balance_units"] - 32
            return client.post(
                MODEL_PATH,
                headers={"authorization": f"Bearer {grant.model_token}"},
                json={"model": route.model, "input": "页面快照：页面已加载", **body},
            )

        state.post = post
        yield state


@pytest.mark.parametrize("maximum", [None, 1024, 2048])
def test_browser_model_uses_qualified_output_capacity_and_actual_usage(browser_model, maximum):
    state = browser_model
    response = state.post(**({} if maximum is None else {"max_output_tokens": maximum}))
    assert response.status_code == 200, response.text
    assert len(state.model_requests) == 1
    body = json.loads(state.model_requests[0].content)
    assert body["max_output_tokens"] == (2048 if maximum is None else maximum)
    saved = state.repository.get(state.parent.run_id)
    assert saved.llm_calls[0].total_tokens == 2000
    assert saved.metadata["ai_cost_units_total"] == 2
    assert saved.metadata["reserved_cost_units"] == 0
    assert ledger.get_model_wallet(saved.user_id)["balance_units"] == 98


def test_browser_rejects_output_above_qualified_capacity_before_reserving(browser_model):
    state = browser_model
    assert state.post(max_output_tokens=4096).status_code == 400
    assert state.model_requests == state.browser_requests == []
    assert ledger.get_model_wallet(state.parent.user_id)["balance_units"] == 100
    assert state.store.get(state.parent.run_id).metadata.get("model_requests", {}) == {}


@pytest.mark.parametrize("insufficient", ["task", "wallet"])
def test_browser_model_budget_denies_before_provider_or_browser_io(browser_model, insufficient):
    state = browser_model
    if insufficient == "task":
        state.store.update(
            state.parent.run_id,
            lambda run, _metadata: run.metadata.update(ai_cost_budget_units=1),
        )
    else:
        ledger.set_model_wallet_balance(state.parent.user_id, 1)
    assert state.post().status_code == 402
    assert state.model_requests == state.browser_requests == []
    assert ledger.get_model_wallet(state.parent.user_id)["balance_units"] == (
        100 if insufficient == "task" else 1
    )
    assert [run.run_id for run in state.repository.list_recent()] == [state.parent.run_id]


def test_browser_single_action_receives_budget_after_actual_model_settlement(browser_model):
    state = browser_model
    assert state.post().status_code == 200
    receipt = state.observe()
    assert len(state.browser_requests) == 1, receipt
    assert receipt["verified"] is True, receipt
    call = state.store.get(state.parent.run_id).metadata["calls"]["read-original-browser-page"]
    assert call["budget_units"] == 98
    child = state.repository.get(call["child_run_id"])
    assert child.metadata["ai_cost_budget_units"] == 98
    assert len(child.steps) == 1 and child.steps[0].tool_id == "browser"
    assert child.steps[0].action == "observe"


def test_unknown_model_usage_keeps_reservation_and_blocks_browser_continuation(browser_model):
    state = browser_model
    state.response.pop("usage")
    assert state.post().status_code == 502
    saved = state.store.get(state.parent.run_id)
    assert saved.metadata["model_reconciliation_required"] is True
    assert {row["state"] for row in saved.metadata["model_requests"].values()} == {"unknown"}
    assert saved.run.metadata["reserved_cost_units"] == 32 and saved.run.llm_calls == []
    assert ledger.get_model_wallet(saved.run.user_id)["balance_units"] == 68
    assert state.post().status_code == 409
    assert len(state.model_requests) == 1
    with pytest.raises(XiaoxBindingError) as error:
        state.observe()
    assert error.value.code == "reconciliation_required"
    assert state.browser_requests == []
    assert state.store.get(state.parent.run_id).metadata["calls"] == {}
    state.store.close(state.parent.run_id, "waiting_user")
    with pytest.raises(XiaoxBindingError) as error:
        state.store.create(state.parent.run_id, runtime_config=state.route.runtime_identity())
    assert error.value.code == "reconciliation_required"


def test_inflight_model_request_blocks_new_browser_action_until_usage_settles(browser_model):
    state = browser_model

    def try_while_reserved():
        with pytest.raises(XiaoxBindingError) as error:
            state.observe()
        assert error.value.code == "call_in_progress"
        assert state.browser_requests == []
        assert state.store.get(state.parent.run_id).metadata["calls"] == {}

    state.on_model = try_while_reserved
    assert state.post().status_code == 200
    receipt = state.observe()
    assert receipt["verified"] is True and len(state.browser_requests) == 1, receipt


def test_unknown_model_usage_still_allows_original_browser_receipt_without_replay(browser_model):
    state = browser_model
    original = state.observe()
    assert original["verified"] is True, original
    state.response.pop("usage")
    before = ledger.get_model_wallet(state.parent.user_id)["balance_units"]
    assert state.post().status_code == 502
    held = state.store.get(state.parent.run_id).run.metadata["reserved_cost_units"]
    repeated = state.observe()
    assert repeated["run_id"] == original["run_id"]
    assert repeated["tool_calls"] == original["tool_calls"]
    assert repeated["verified"] is True and len(state.browser_requests) == 1
    with pytest.raises(XiaoxBindingError) as error:
        state.observe("new-browser-action")
    assert error.value.code == "reconciliation_required"
    assert state.store.get(state.parent.run_id).run.metadata["reserved_cost_units"] == held == 32
    assert ledger.get_model_wallet(state.parent.user_id)["balance_units"] == before - 32


@pytest.mark.parametrize("during", ["before_request", "completion"])
def test_browser_rejects_conversation_revision_changed_across_model_io(browser_model, during):
    state = browser_model

    def revise():
        with state.actor.factory.begin() as db:
            db.query(AIConversationSession).filter_by(session_id="browser-budget-chat").update(
                {"revision": 1}
            )

    if during == "before_request":
        revise()
    else:
        state.on_model = revise
    response = state.post()
    assert response.status_code == (403 if during == "before_request" else 409)
    assert len(state.model_requests) == (during == "completion")
    assert ledger.get_model_wallet(state.parent.user_id)["balance_units"] == (
        100 if during == "before_request" else 98
    )
    with pytest.raises(XiaoxBindingError) as error:
        state.observe()
    assert error.value.code == "conversation_changed"
    assert state.browser_requests == []
    assert state.store.get(state.parent.run_id).metadata["calls"] == {}


@pytest.mark.parametrize("prefix", ["browser_driver_failure", "browser_model_budget_exceeded"])
def test_browser_model_gateway_errors_do_not_expose_private_details(browser_model, prefix):
    state = browser_model
    detail = f"{prefix}: private-credential in /internal/browser/session"

    def fail():
        raise httpx.ReadError(detail)

    state.on_model = fail
    response = state.post()
    assert response.status_code == 502
    assert response.json() == {"detail": "Qualified model gateway is unavailable"}
    assert detail not in response.text
    assert state.browser_requests == []
    assert len(state.model_requests) == 1
    assert state.store.get(state.parent.run_id).metadata["model_reconciliation_required"] is True
    assert ledger.get_model_wallet(state.parent.user_id)["balance_units"] == 68


@pytest.mark.parametrize(
    "browser_model", ["current", "revoked", "expired", "scope_changed"], indirect=True
)
def test_model_callback_rechecks_original_api_key_before_reservation(browser_model):
    state = browser_model
    credential = state.credential
    if credential.condition == "revoked":
        assert credential.registry.revoke(credential.key)
    elif credential.condition == "expired":
        credential.clock[0] += 61
    elif credential.condition == "scope_changed":
        # Simulate an operator update from another worker. Admission must reload
        # the authoritative shared registry instead of trusting the frozen scope.
        entries = json.loads(credential.path.read_text())
        entries[credential.key]["scopes"] = ["capability.business_db.read"]
        credential.path.write_text(json.dumps(entries))

    response = state.post()
    if credential.condition == "current":
        assert response.status_code == 200, response.text
        assert len(state.model_requests) == 1
        assert ledger.get_model_wallet(state.parent.user_id)["balance_units"] == 98
        original = state.observe()
        repeated = state.observe()
        assert original["verified"] is True and repeated["run_id"] == original["run_id"]
        assert len(state.browser_requests) == 1
    else:
        assert response.status_code == 403, response.text
        assert state.model_requests == state.browser_requests == []
        assert ledger.get_model_wallet(state.parent.user_id)["balance_units"] == 100
        saved = state.store.get(state.parent.run_id)
        assert saved.metadata.get("model_requests", {}) == {}
        assert saved.run.metadata.get("reserved_cost_units", 0) == 0
        assert saved.run.llm_calls == []
