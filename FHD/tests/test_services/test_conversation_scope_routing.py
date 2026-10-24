"""Isolation regressions for cached follow-ups and nested model calls."""

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.agent_task_context import scoped_conversation_user_id
from app.services.conversation.api import ApiMixin
from app.services.conversation.context import ConversationContext
from app.services.conversation.prompts import PromptsMixin


@pytest.mark.parametrize("action", ["新增", "修改", "更新", "删除"])
def test_describing_a_previous_write_does_not_request_another_write(action):
    from app.domain.services.conversation.chat_tool_intent import looks_like_business_db_write

    assert not looks_like_business_db_write(f"刚才{action}的客户，联系人现在是谁？请查询实际记录。")
    assert looks_like_business_db_write(f"把刚才{action}的客户，联系人改为测试员")


def test_state_scope_binds_owner_tenant_mod_and_conversation():
    base = {"local_user_id": 1, "tenant_id": 1, "mod_id": "a", "conversation_id": "same"}
    key = scoped_conversation_user_id("caller", base)
    assert scoped_conversation_user_id("different-body-user", base) == key
    for field, value in [
        ("local_user_id", 2),
        ("tenant_id", 2),
        ("mod_id", "b"),
        ("conversation_id", "other"),
    ]:
        assert scoped_conversation_user_id("caller", {**base, field: value}) != key


def test_follow_up_cannot_replace_a_pending_write_plan():
    from app.application.ai_chat_app_service import AIChatApplicationService
    from app.application.workflow.types import PlanGraph

    service = AIChatApplicationService.__new__(AIChatApplicationService)
    pending = {
        "plan": PlanGraph(plan_id="original-write", intent="business_db_write"),
        "runtime_context": {"session_id": "conversation-a"},
        "agent_run_id": "run-original",
    }
    service._pending_workflows = {"owner-a": pending}
    handled, reply = service._resume_pending_dynamic_workflow(
        "owner-a",
        "刚才的客户呢",
        "刚才的客户呢",
        {"session_id": "conversation-a"},
    )
    assert handled and service._pending_workflows["owner-a"] is pending
    assert reply["data"]["data"]["plan_id"] == "original-write"
    assert reply["data"]["data"]["run_id"] == "run-original"


def test_provider_registry_does_not_retain_previous_users_adapter(monkeypatch):
    from app.infrastructure.llm.providers import registry

    monkeypatch.setattr(registry, "_routing_order", lambda: ("modstore",))
    providers = registry.LLMProviderRegistry()
    assert providers.resolve(conversation_service=SimpleNamespace(modstore_adapter=object()))
    assert providers.resolve(conversation_service=SimpleNamespace(modstore_adapter=None)) is None


def test_planner_and_agent_share_each_threads_model_without_environment_key(monkeypatch):
    from app.application.employee_runtime.agent_loop import run_employee_agent_loop
    from app.application.employee_runtime.agent_runner import _chat_completion, _run_async
    from app.application.workflow.planner_llm_gateway import request_planner_completion
    from app.infrastructure.llm import client as routing

    monkeypatch.setattr(routing, "_first_api_key", lambda: ("", None))

    def run(model):
        payload = {"model": model, "choices": [{"message": {"content": model}}]}
        reply = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=model, tool_calls=[]))],
            model_dump=lambda: payload,
        )
        client = MagicMock()
        client.chat.completions.create.return_value = reply
        with routing.llm_client_scope(client, model):
            plan = request_planner_completion(
                ai_service=SimpleNamespace(),
                context={},
                messages=[{"role": "user", "content": "test"}],
                http_client_factory=lambda: pytest.fail("separate planner HTTP route"),
            )
            agent = run_employee_agent_loop(
                employee_id="test", system_prompt="test", task="test", tools=[]
            )
            cognition = _run_async(_chat_completion([{"role": "user", "content": "test"}]))
        assert plan["model"] == model
        assert agent["ok"] is True
        assert cognition["model"] == model
        assert {call.kwargs["model"] for call in client.chat.completions.create.call_args_list} == {
            model
        }

    with ThreadPoolExecutor(max_workers=2) as workers:
        list(workers.map(run, ["owner-a/model", "owner-b/model"]))
    with pytest.raises(RuntimeError):
        routing.require_api_key()


@pytest.mark.asyncio
async def test_follow_up_cache_separates_owners_history_and_models(monkeypatch):
    from app.infrastructure.llm.client import llm_client_scope
    from app.services.conversation import api

    cache = {}
    monkeypatch.setattr(
        api, "_ai_response_cache", SimpleNamespace(get=cache.get, set=cache.__setitem__)
    )

    class Conversation(ApiMixin, PromptsMixin):
        model = "test"
        modstore_adapter = llm_adapter = persona_service = None
        add_to_history = MagicMock()
        _build_context_prompt = MagicMock(return_value="")

    service = Conversation()
    service.call_llm_api = AsyncMock(
        side_effect=[
            {"choices": [{"message": {"content": answer}}]}
            for answer in ["a", "b", "updated", "new-model"]
        ]
    )
    first = ConversationContext(user_id="a")
    second = ConversationContext(user_id="b")
    assert (await service._call_ai("刚才的客户呢", first, {}))["text"] == "a"
    assert (await service._call_ai("刚才的客户呢", second, {}))["text"] == "b"
    first.conversation_history.append({"role": "user", "content": "修改客户"})
    assert (await service._call_ai("刚才的客户呢", first, {}))["text"] == "updated"
    with llm_client_scope(object(), "different-model"):
        assert (await service._call_ai("刚才的客户呢", first, {}))["text"] == "new-model"
    assert service.call_llm_api.await_count == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", ["", "_batch"])
async def test_json_chat_routes_bind_request_credentials_lazily(monkeypatch, suffix):
    import asyncio

    from app.application import planner_compat_service as service
    from app.infrastructure.llm.client import get_llm_client

    request, body, client = object(), object(), object()
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(service, "create_modstore_openai_client_from_request", factory)

    async def execute(actual_request, actual_body):
        assert (actual_request, actual_body) == (request, body)
        factory.assert_not_called()
        assert await asyncio.to_thread(get_llm_client) is client
        return {"success": True}

    monkeypatch.setattr(service, f"_execute_compat_chat{suffix}_impl", execute)
    assert await getattr(service, f"execute_compat_chat{suffix}")(request, body) == {
        "success": True
    }
    factory.assert_called_once_with(request)


def test_platform_worker_scope_keeps_model_and_credentials_out_of_environment(monkeypatch):
    from app.infrastructure.llm import client as routing
    from app.services.conversation.modstore_adapter import (
        ModstoreOpenAICompatibleClient,
        ModstorePlatformAdapter,
    )

    adapter = ModstorePlatformAdapter(auth_token="fake-owner-a")
    with routing.llm_client_scope(ModstoreOpenAICompatibleClient(adapter), "owner-a/model"):
        snapshot = routing.capture_worker_llm_scope()
    monkeypatch.setenv("MODSTORE_AUTH_TOKEN", "fake-owner-b")
    monkeypatch.setenv("LLM_MODEL", "owner-b/model")
    with routing.llm_client_factory_scope(lambda: routing.restore_worker_llm_client(snapshot)):
        assert routing.get_llm_client().adapter.auth_token == "fake-owner-a"
        assert routing.resolve_chat_model() == "owner-a/model"
    with routing.llm_client_factory_scope(
        lambda: routing.restore_worker_llm_client({"kind": "unavailable"})
    ):
        with pytest.raises(RuntimeError, match="不能回退"):
            routing.get_llm_client()


def test_resumed_worker_resolves_only_the_authenticated_tasks_account(monkeypatch):
    from app.fastapi_routes import market_account
    from app.infrastructure.llm import client as routing

    reader = MagicMock(return_value="fake-task-owner")
    monkeypatch.setattr(market_account, "latest_session_market_token", reader)
    snapshot = routing.capture_worker_llm_scope({"local_user_id": 17})
    assert snapshot == {"kind": "account", "owner": 17}
    assert routing.restore_worker_llm_client(snapshot)[0].adapter.auth_token == "fake-task-owner"
    reader.assert_called_once_with(user_id=17)
    reader.return_value = ""
    with pytest.raises(RuntimeError, match="重新登录"):
        routing.restore_worker_llm_client(snapshot)
