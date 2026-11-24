"""Management mode changes reach existing tools and every subsequent model call."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from modstore_server import agent_butler_api as butler
from modstore_server import xiaoc_life_chat as life_chat
from modstore_server import xiaoc_life_store as store

ADMIN = SimpleNamespace(id=17, is_admin=True)
CUSTOMER = SimpleNamespace(id=29, is_admin=False)


@pytest.fixture
def life_database(tmp_path, monkeypatch):
    """Give isolated route tests the same initialized tables as application startup."""
    from modstore_server.db.xiaoc_life import XiaoCLifeEvent, XiaoCLifeState

    engine = create_engine(f"sqlite:///{tmp_path / 'life.sqlite'}")
    for model in (XiaoCLifeState, XiaoCLifeEvent):
        model.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(store, "get_session_factory", lambda: factory)
    yield factory
    engine.dispose()


@pytest.fixture
def state(monkeypatch):
    state = {
        "identity_id": "xcmax:management:xiaoc",
        "level": 3,
        "paused": False,
        "status": "idle",
        "revision": 1,
        "goals": [],
        "interests": [],
    }
    monkeypatch.setattr(store, "read_state", lambda: dict(state))

    def require(minimum_level):
        if state["level"] < minimum_level:
            raise store.LifePolicyError(f"当前自主模式需要 L{minimum_level}")

    monkeypatch.setattr(store, "require_life_capability", require)
    return state


def test_shared_context_excludes_private_memory_and_reasoning(state):
    state.update(
        private_memory="another user's private note",
        reasoning="hidden model reasoning",
        goals=[
            {
                "id": "g1",
                "title": "核对交付结果",
                "private_prompt": "never share",
                "evidence_refs": ["receipt:4"],
            }
        ],
        interests=[{"topic": "可验证交付", "evidence_refs": ["receipt:4"]}],
        events=[
            {
                "id": "e1",
                "summary": "已观察到真实回执",
                "status": "observed",
                "evidence_refs": ["receipt:4"],
                "details": {"reasoning": "never share"},
            },
            {"id": "e2", "summary": "没有证据的成功故事", "evidence_refs": []},
        ],
    )
    context = life_chat.admin_life_context(ADMIN)
    assert "企业唯一小C" in context and "核对交付结果" in context
    assert "已观察到真实回执" in context and "receipt:4" in context
    assert "可验证交付" in context and "没有证据的成功故事" not in context
    assert all(value not in context for value in ("another user's", "hidden model", "never share"))
    assert life_chat.admin_life_context(SimpleNamespace(id=18, is_admin=True)) == context
    assert life_chat.admin_life_context(CUSTOMER) == ""


def test_l1_omits_tools_and_rejects_returned_tool_calls(state, monkeypatch):
    state["level"] = 1
    executor = MagicMock()
    monkeypatch.setattr(butler, "_execute_admin_readonly_tool", executor)
    assert butler._butler_tools_for_user(ADMIN) == []
    page, brief = butler._partition_butler_tool_calls(
        [{"name": "get_my_wallet", "args": {}}, {"name": "navigate", "args": {}}],
        user=ADMIN,
        db=MagicMock(),
    )
    assert page == [] and "未执行" in brief
    executor.assert_not_called()
    assert butler._butler_tools_for_user(CUSTOMER) == butler.BUTLER_TOOLS


def test_l2_allows_one_requested_tool_but_never_delegation_or_batch(state, monkeypatch):
    state["level"] = 2
    state["paused"] = True  # Pausing autonomous life does not revoke manual tasks.
    executor = MagicMock(return_value="实际钱包回执")
    monkeypatch.setattr(butler, "_execute_admin_readonly_tool", executor)
    schemas = butler._butler_tools_for_user(ADMIN)
    assert "enhance_current_page" not in {tool["function"]["name"] for tool in schemas}
    assert butler._butler_tools_for_user(ADMIN, []) == []
    assert (
        butler._butler_tools_for_user(
            ADMIN, [butler.ButlerMessageDTO(role="assistant", content="我要读钱包")]
        )
        == []
    )
    call = {"name": "get_my_wallet", "args": {}}
    assert butler._partition_butler_tool_calls([call], user=ADMIN, db=None) == ([], "实际钱包回执")
    executor.reset_mock()
    page, brief = butler._partition_butler_tool_calls([call, call], user=ADMIN, db=None)
    assert page == [] and "未执行" in brief
    executor.assert_not_called()
    page, brief = butler._partition_butler_tool_calls(
        [{"name": "enhance_current_page", "args": {"brief": "改造页面"}}], user=ADMIN, db=None
    )
    assert page == [] and "未执行" in brief


def test_admin_tool_executor_rechecks_downgrade(state):
    state["level"] = 1
    with pytest.raises(HTTPException) as error:
        butler._execute_admin_readonly_tool("get_my_wallet", {}, user=ADMIN, db=MagicMock())
    assert error.value.status_code == 409


def test_downgrade_at_tool_execution_keeps_completed_model_receipt_path(state, monkeypatch):
    original = life_chat.butler_tools_for_user

    def tools_then_downgrade(user):
        tools = original(user)
        state["level"] = 1
        return tools

    monkeypatch.setattr(life_chat, "butler_tools_for_user", tools_then_downgrade)
    db = MagicMock()
    page, brief = life_chat.partition_butler_tool_calls(
        [{"name": "get_my_wallet", "args": {}}], user=ADMIN, db=db
    )
    assert page == [] and "工具未执行" in brief
    db.query.assert_not_called()


@pytest.mark.parametrize(
    "path,body",
    [
        ("orchestrate", {"target_type": "mod", "target_id": "m1", "brief": "增加检查步骤"}),
        ("all-hands-report", {}),
        ("all-hands-report/sessions", {}),
        ("daily-digests/1/line-execute", {}),
        ("daily-digests/1/vibe-prep/sessions", {}),
    ],
)
def test_l2_cannot_start_employee_orchestration_via_direct_api(state, path, body):
    state["level"] = 2
    db = MagicMock()
    app = FastAPI()
    app.include_router(butler.router)
    app.dependency_overrides[butler._get_current_user] = lambda: ADMIN
    app.dependency_overrides[butler.get_db] = lambda: db
    with TestClient(app) as client:
        response = client.post("/api/agent/butler/" + path, json=body)
    assert response.status_code == 409, response.text
    assert "L3" in response.json()["detail"]
    db.add.assert_not_called()
    db.get.assert_not_called()


@pytest.mark.asyncio
async def test_manual_scope_reaches_created_task_and_thread_after_downgrade(state):
    ready = asyncio.Event()

    async def child():
        await ready.wait()
        await asyncio.to_thread(life_chat.require_manual_life_capability)

    with life_chat.manual_life_scope(ADMIN, 3):
        task = asyncio.create_task(child())
    assert not life_chat.manual_life_scope_active()
    state["level"] = 1
    ready.set()
    with pytest.raises(store.LifePolicyError):
        await task
    with life_chat.manual_life_scope(CUSTOMER, 3):
        life_chat.require_manual_life_capability()


@pytest.mark.asyncio
async def test_new_model_retry_stops_after_downgrade(state, monkeypatch):
    from modstore_server import llm_chat_proxy as proxy
    from modstore_server import llm_litellm_router as router

    monkeypatch.setattr(router, "chat", AsyncMock(return_value=None))
    monkeypatch.setenv("MODSTORE_LLM_PRIMARY_MAX_ATTEMPTS", "2")

    async def transient_failure(*args, **kwargs):
        state["level"] = 1
        return {"ok": False, "status": 503, "error": "temporary unavailable"}

    outbound = AsyncMock(side_effect=transient_failure)
    monkeypatch.setattr(proxy, "chat_openai_compatible", outbound)
    with life_chat.manual_life_scope(ADMIN, 3), pytest.raises(store.LifePolicyError):
        await proxy.chat_dispatch(
            "openai",
            api_key="test",
            base_url="https://example.invalid/v1",
            model="test",
            messages=[{"role": "user", "content": "repair"}],
        )
    assert outbound.await_count == 1


@pytest.mark.asyncio
async def test_stream_rechecks_before_first_outbound(state, monkeypatch):
    from modstore_server import llm_chat_proxy as proxy
    from modstore_server import llm_litellm_router as router

    outbound = MagicMock()
    monkeypatch.setattr(router, "stream_events", outbound)
    with life_chat.manual_life_scope(ADMIN, 3):
        state["level"] = 1
        stream = proxy.chat_dispatch_stream(
            "openai", api_key="test", base_url=None, model="test", messages=[]
        )
        with pytest.raises(store.LifePolicyError):
            await anext(stream)
    outbound.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["openai", "anthropic", "google"])
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("user", [ADMIN, CUSTOMER])
async def test_router_manual_scope_disables_unchecked_retries(
    state, monkeypatch, user, streaming, provider
):
    from modstore_server import llm_litellm_router as router

    calls = {}

    class FakeRouter:
        async def acompletion(self, **kwargs):
            calls["completion"] = kwargs
            if kwargs.get("stream"):

                async def chunks():
                    yield SimpleNamespace(
                        choices=[],
                        usage={},
                        model_dump=lambda **kwargs: {"choices": [], "usage": {}},
                    )

                return chunks()
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="done"))],
                usage={},
                model="test",
                _hidden_params={},
            )

    def get_router(deployments, fallback_aliases):
        calls["fallback_aliases"] = fallback_aliases
        return FakeRouter()

    monkeypatch.setattr(router, "available", lambda: True)
    monkeypatch.setattr(router, "_get_router", get_router)
    kwargs = {
        "api_key": "test",
        "base_url": None,
        "model": "test",
        "messages": [],
        "fallbacks": [{"provider": "deepseek", "model": "backup", "api_key": "test-backup"}],
    }
    with life_chat.manual_life_scope(user, 3):
        if streaming:
            iterator = router.stream_events(provider, **kwargs)
            assert iterator is not None
            assert [event async for event in iterator] == []
        else:
            result = await router.chat(provider, **kwargs)
            assert result is not None and result["ok"]
    if user.is_admin:
        assert calls["fallback_aliases"] == []
        assert calls["completion"]["num_retries"] == 0
        assert calls["completion"]["max_retries"] == 0
        assert calls["completion"]["disable_fallbacks"] is True
    else:
        assert calls["fallback_aliases"]
        assert "disable_fallbacks" not in calls["completion"]
    if provider != "openai":
        assert "client" not in calls["completion"]


@pytest.mark.asyncio
async def test_l1_chat_uses_plain_model_without_tool_request(state, monkeypatch):
    from modstore_server import xiaoc_admin_context

    state["level"] = 1
    monkeypatch.setattr(xiaoc_admin_context, "admin_context_for_chat", AsyncMock(return_value=""))
    monkeypatch.setattr(
        butler,
        "_resolve_butler_credentials",
        lambda *_: ("openai", "test", "key", "user_override", ""),
    )
    monkeypatch.setattr(
        butler, "_build_messages", lambda *a, **kw: [{"role": "user", "content": "你好"}]
    )
    monkeypatch.setattr(butler, "enforce_risk_limits", lambda *_: None)
    monkeypatch.setattr(butler, "_get_or_create_conversation", lambda *a: SimpleNamespace(id=5))
    monkeypatch.setattr(butler, "save_success_log", lambda *a, **kw: None)
    plain = AsyncMock(
        return_value={
            "ok": True,
            "content": "你好",
            "finish_reason": "stop",
            "usage": {"total_tokens": 2},
        }
    )
    monkeypatch.setattr(butler, "chat_dispatch", plain)
    result = await butler.butler_chat(
        Request({"type": "http", "headers": []}),
        butler.ButlerChatDTO(messages=[{"role": "user", "content": "你好"}]),
        db=MagicMock(),
        user=ADMIN,
    )
    assert result["text"] == "你好" and result["tool_calls"] == []
    plain.assert_awaited_once()
    assert "tools" not in plain.await_args.kwargs
