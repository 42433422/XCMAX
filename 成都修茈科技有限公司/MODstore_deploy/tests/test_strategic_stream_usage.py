"""Exercise the actual SSE parser and durable SQL budget through the public facade."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from modstore_server import llm_chat_providers, llm_chat_proxy, llm_key_resolver
from modstore_server import llm_litellm_router as router
from modstore_server import strategic_portfolio as portfolio
from modstore_server import strategic_portfolio_runtime as runtime
from modstore_server import strategic_portfolio_usage as usage


@pytest.fixture
def mandate(tmp_path, monkeypatch):
    from modstore_server import db, employee_runtime, models
    from modstore_server.db.db_base import Base
    from modstore_server.db.identity import User
    from modstore_server.integrations import vibe_adapter
    from modstore_server.strategic_layer import autonomy_boundary, decision_ledger

    engine = create_engine(f"sqlite:///{tmp_path / 'stream-budget.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    for module in (portfolio, runtime, usage, db.db_base, autonomy_boundary, decision_ledger):
        monkeypatch.setattr(module, "get_session_factory", lambda: factory)
    monkeypatch.setattr(
        vibe_adapter,
        "_tenant_workspace_root",
        lambda user_id: tmp_path / "workspaces" / str(user_id),
    )
    monkeypatch.setattr(
        employee_runtime,
        "load_employee_pack_resolved",
        lambda _session, employee_id, **_kwargs: {
            "pack_id": employee_id,
            "version": "1.0.0",
            "manifest": {
                "employee_config_v2": {
                    "workspace_policy": {
                        "scope_globs": ["docs/**"],
                        "forbidden_globs": ["**/.env"],
                    },
                    "actions": {"handlers": ["echo"]},
                }
            },
        },
    )
    with factory() as session:
        session.add(User(id=7, username="stream-owner", password_hash="unused", is_admin=True))
        session.commit()
    result = portfolio.create_portfolio_proposal(
        owner_user_id=7,
        goal="Measure an approved streamed task",
        period="stream-tests",
        idempotency_key="stream-tests",
        limits={
            "cost_cents": 100,
            "tokens": 100_000,
            "compute_seconds": 600,
            "stop_loss_cents": 100,
            "expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            "tariffs": [
                {
                    "provider": "openai",
                    "model": "approved-model",
                    "input_cents_per_million": 100,
                    "output_cents_per_million": 100,
                    "source": "approved-test-tariff",
                }
            ],
        },
        opportunities=[
            {
                "opportunity_id": "a",
                "title": "stream",
                "task": "approved task",
                "employee_id": "test-qa-runner",
                "source_refs": ["incident:stream"],
                "value_score": 10,
                "cost_cents": 50,
                "tokens": 40_000,
                "compute_seconds": 100,
            }
        ],
    )
    decision_id = result["decision"]["decision_id"]
    portfolio.authorize_portfolio(
        decision_id,
        owner_user_id=7,
        actor="admin:7",
        expected_proposal_sha256=result["decision"]["decision_payload"]["proposal_sha256"],
    )
    portfolio.plan_portfolio(decision_id)
    task = runtime._claim(decision_id, 7)
    monkeypatch.setattr(llm_key_resolver, "platform_api_key", lambda _: "platform-test-key")
    monkeypatch.setattr(llm_key_resolver, "platform_base_url", lambda _: None)
    monkeypatch.setattr(router, "available", lambda: False)
    yield decision_id, task, factory
    engine.dispose()


def _stream(**overrides):
    return llm_chat_proxy.chat_dispatch_stream(
        "openai",
        **{
            "api_key": "platform-test-key",
            "base_url": None,
            "model": "approved-model",
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 20,
            **overrides,
        },
    )


def _calls(mandate):
    state = portfolio.portfolio_status(mandate[0])
    return state, list(state["tasks"]["a"].get("calls", {}).values())


def _sse(monkeypatch, mandate, *, finish=True, meter=True, malformed=False, pause=False):
    observed = {"requests": 0, "closed": False, "waiting": asyncio.Event()}

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            frames = [{"choices": [{"delta": {"content": "actual stream"}}]}]
            if finish:
                frames.append({"choices": [{"delta": {}, "finish_reason": "stop"}]})
            if meter:
                frames.append(
                    {"usage": {"prompt_tokens": 10, "completion_tokens": -1 if malformed else 3}}
                )
            for frame in frames:
                yield ("data: " + json.dumps(frame) + "\n\n").encode()
            if pause:
                observed["waiting"].set()
                await asyncio.Event().wait()
            yield b"data: [DONE]\n\n"

        async def aclose(self):
            observed["closed"] = True

    @asynccontextmanager
    async def response(url, _key, _headers, body, **_kwargs):
        observed["requests"] += 1
        observed["body"] = body
        state, calls = _calls(mandate)
        assert not state["halted"] and len(calls) == 1
        assert calls[0]["status"] == "pending"  # durable before any outbound request
        usage.require_call_reservation()
        result = httpx.Response(200, stream=Body(), request=httpx.Request("POST", url))
        try:
            yield result
        finally:
            await result.aclose()

    monkeypatch.setattr(llm_chat_providers, "llm_http_response", response)
    return observed


@pytest.mark.asyncio
async def test_stream_reserves_before_http_and_settles_actual_usage(mandate, monkeypatch):
    observed = _sse(monkeypatch, mandate)
    with usage.portfolio_usage_scope(mandate[0], "a", mandate[1]["lease_token"]):
        events = [event async for event in _stream()]
    state, calls = _calls(mandate)
    assert events[0] == {"type": "delta", "delta": "actual stream"}
    assert observed["requests"] == 1 and observed["closed"]
    assert observed["body"]["stream_options"] == {"include_usage": True}
    assert observed["body"]["max_tokens"] == 20
    assert not state["halted"] and calls[0]["status"] == "settled"
    assert calls[0]["actual_tokens"] == 13
    assert calls[0]["accrued_cost_cents"] == 1


@pytest.mark.asyncio
async def test_many_stream_events_read_authority_without_rewriting_ledger(mandate):
    from sqlalchemy import event

    writes = []
    engine = mandate[2].kw["bind"]

    def observe_sql(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("UPDATE STRATEGIC_DECISIONS"):
            writes.append(statement)

    async def invoke(_provider, **_kwargs):
        for _ in range(25):
            yield {"type": "delta", "delta": "x"}
        yield {"type": "finish"}
        yield {"type": "usage", "usage": {"prompt_tokens": 10, "completion_tokens": 25}}

    event.listen(engine, "before_cursor_execute", observe_sql)
    try:
        with usage.portfolio_usage_scope(mandate[0], "a", mandate[1]["lease_token"]):
            events = [
                row
                async for row in usage.dispatch_budgeted_stream(
                    invoke,
                    "openai",
                    {
                        "api_key": "platform-test-key",
                        "base_url": None,
                        "model": "approved-model",
                        "messages": [{"role": "user", "content": "hello"}],
                        "max_tokens": 50,
                    },
                )
            ]
        assert len(events) == 27
        assert len(writes) == 2  # One reservation and one settlement, no writes per event.
        assert _calls(mandate)[1][0]["status"] == "settled"
    finally:
        event.remove(engine, "before_cursor_execute", observe_sql)


@pytest.mark.asyncio
@pytest.mark.parametrize("options", [{"meter": False}, {"finish": False}, {"malformed": True}])
async def test_missing_or_incomplete_usage_keeps_hold(mandate, monkeypatch, options):
    observed = _sse(monkeypatch, mandate, **options)
    with usage.portfolio_usage_scope(mandate[0], "a", mandate[1]["lease_token"]):
        _ = [event async for event in _stream()]
    state, calls = _calls(mandate)
    assert observed["closed"] and state["halted"]
    assert calls[0]["status"] == "unknown" and calls[0]["reserved_cost_cents"] > 0
    assert "accrued_cost_cents" not in calls[0]


@pytest.mark.asyncio
async def test_early_close_cancels_http_and_retains_hold(mandate, monkeypatch):
    observed = _sse(monkeypatch, mandate, pause=True)
    with usage.portfolio_usage_scope(mandate[0], "a", mandate[1]["lease_token"]):
        stream = _stream()
        assert (await anext(stream))["type"] == "delta"
        await stream.aclose()
    state, calls = _calls(mandate)
    assert observed["closed"] and state["halted"]
    assert calls[0]["status"] == "unknown"


@pytest.mark.asyncio
async def test_stream_rechecks_revocation_between_events(mandate, monkeypatch):
    observed = _sse(monkeypatch, mandate)
    with usage.portfolio_usage_scope(mandate[0], "a", mandate[1]["lease_token"]):
        stream = _stream()
        await anext(stream)
        portfolio.stop_portfolio(mandate[0], owner_user_id=7, actor="admin:7", reason="stop")
        with pytest.raises(portfolio.PortfolioError):
            await anext(stream)
        await stream.aclose()
    state, calls = _calls(mandate)
    assert observed["closed"] and state["halted"] and observed["requests"] == 1
    assert calls[0]["status"] == "unknown"


@pytest.mark.asyncio
async def test_tools_are_included_in_reservation_before_outbound(mandate, monkeypatch):
    observed = _sse(monkeypatch, mandate)
    with usage.portfolio_usage_scope(mandate[0], "a", mandate[1]["lease_token"]):
        with pytest.raises(portfolio.PortfolioError, match="token budget"):
            _ = [
                event
                async for event in _stream(
                    tools=[
                        {
                            "type": "function",
                            "function": {"name": "large", "description": "x" * 20_000},
                        }
                    ]
                )
            ]
    assert observed["requests"] == 0


@pytest.mark.asyncio
async def test_raw_stream_cannot_skip_approval_or_reuse_another_route(mandate, monkeypatch):
    observed = _sse(monkeypatch, mandate)
    with usage.portfolio_usage_scope(mandate[0], "a", mandate[1]["lease_token"]):
        with pytest.raises(portfolio.PortfolioError, match="persisted per-call"):
            _ = [
                event
                async for event in llm_chat_providers.stream_openai_compatible(
                    "https://api.openai.com/v1",
                    "platform-test-key",
                    "approved-model",
                    [],
                )
            ]
        reservation = usage.prepare_platform_call("openai", "approved-model", [], 10)
        with usage.platform_call_reservation(reservation):
            with pytest.raises(portfolio.PortfolioError, match="route mismatch"):
                _ = [
                    event
                    async for event in llm_chat_providers.stream_openai_compatible(
                        "https://api.openai.com/v1",
                        "platform-test-key",
                        "unapproved-model",
                        [],
                    )
                ]
        usage.complete_platform_call(reservation, None)
    assert observed["requests"] == 0


@pytest.mark.asyncio
async def test_native_stream_cannot_spend_one_reservation_twice(mandate, monkeypatch):
    observed = _sse(monkeypatch, mandate)

    def stream():
        return llm_chat_providers.stream_openai_compatible(
            "https://api.openai.com/v1", "platform-test-key", "approved-model", []
        )

    with usage.portfolio_usage_scope(mandate[0], "a", mandate[1]["lease_token"]):
        reservation = usage.prepare_platform_call("openai", "approved-model", [], 10)
        with usage.platform_call_reservation(reservation):
            assert [event async for event in stream()]
            with pytest.raises(portfolio.PortfolioError, match="already started"):
                _ = [event async for event in stream()]
        usage.complete_platform_call(reservation, None)
    assert observed["requests"] == 1


@pytest.mark.asyncio
async def test_cancel_during_silent_stream_closes_pending_read(mandate, monkeypatch):
    observed = _sse(monkeypatch, mandate, pause=True)

    async def consume():
        return [event async for event in _stream()]

    with usage.portfolio_usage_scope(mandate[0], "a", mandate[1]["lease_token"]):
        task = asyncio.create_task(consume())
        await asyncio.wait_for(observed["waiting"].wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    state, calls = _calls(mandate)
    assert observed["closed"] and state["halted"] and len(calls) == 1
    assert calls[0]["status"] == "unknown"


@pytest.mark.asyncio
async def test_total_deadline_includes_wait_for_terminal_usage(mandate, monkeypatch):
    observed = _sse(monkeypatch, mandate, pause=True)
    prepare = usage.prepare_platform_call

    def short_deadline(*args, **kwargs):
        return {**prepare(*args, **kwargs), "timeout_seconds": 0.1}

    monkeypatch.setattr(usage, "prepare_platform_call", short_deadline)
    with usage.portfolio_usage_scope(mandate[0], "a", mandate[1]["lease_token"]):
        with pytest.raises(TimeoutError):
            _ = [event async for event in _stream()]
    state, calls = _calls(mandate)
    assert observed["closed"] and state["halted"] and observed["requests"] == 1
    assert calls[0]["status"] == "unknown"


# LiteLLM 1.109.3 installs import-time filters that pytest restores between tests.
# Its lazy schemas/response introspection must tolerate only these known notices
# regardless of whether a preceding catalog test already imported the SDK.
ROUTER_SDK_WARNINGS = (
    r"ignore:^Items? '[^']+'(, '[^']+')* on TypedDict class '[^']+' "
    r"(is|are) using the `ReadOnly` qualifier\. Pydantic will not protect items "
    r"from any mutation on dictionary instances\.$:UserWarning:"
    r"pydantic\._internal\._generate_schema$",
    r"ignore:^Accessing the 'model_(fields|computed_fields)' attribute on the instance "
    r"is deprecated\. Instead, you should access this attribute from the model class\.$:"
    r"pydantic.warnings.PydanticDeprecatedSince211:"
    r"litellm\.litellm_core_utils\.model_response_utils$",
)


@pytest.mark.filterwarnings(*ROUTER_SDK_WARNINGS)
@pytest.mark.asyncio
@pytest.mark.parametrize("fallback", [False, True])
@pytest.mark.parametrize("receipt", ["reported", "absent", "partial"])
async def test_real_router_requires_original_usage_and_one_reserved_attempt(
    mandate, monkeypatch, fallback, receipt
):
    # Exercise the complete Router -> SDK -> HTTP -> provider wrapper -> router
    # wrapper chain. Returning a bare CustomStreamWrapper misses router prefetch.
    import importlib

    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    import litellm
    from openai import DefaultAsyncHttpxClient

    transport_api = importlib.import_module(
        DefaultAsyncHttpxClient.__mro__[1].__module__.split(".")[0]
    )
    wire_requests, router_requests, clients = [], [], []
    events = [
        {"choices": [{"index": 0, "delta": {"content": "routed"}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]
    if receipt != "absent":
        events.append(
            {
                "choices": [],
                "usage": {
                    "prompt_tokens": 4 if receipt == "reported" else None,
                    "completion_tokens": 2,
                    "total_tokens": 6 if receipt == "reported" else None,
                },
            }
        )
    wire = (
        "".join(
            "data: "
            + json.dumps(
                {
                    "id": "metered-stream",
                    "created": 0,
                    "model": "approved-model",
                    "object": "chat.completion.chunk",
                    **event,
                }
            )
            + "\n\n"
            for event in events
        )
        + "data: [DONE]\n\n"
    )

    def respond(request):
        wire_requests.append(json.loads(request.content))
        assert _calls(mandate)[1][0]["status"] == "pending"
        return transport_api.Response(200, text=wire, headers={"content-type": "text/event-stream"})

    original_client = router._budgeted_stream_client

    def metered_client(*args):
        client = original_client(
            *args,
            http_client=DefaultAsyncHttpxClient(
                transport=transport_api.MockTransport(respond),
                trust_env=False,
            ),
        )
        clients.append(client)
        return client

    def actual_router(deployments, fallbacks):
        actual = litellm.Router(model_list=deployments, num_retries=3)

        class Proxy:
            async def acompletion(self, **kwargs):
                router_requests.append(kwargs)
                response = await actual.acompletion(**kwargs)
                assert type(response).__name__ == "FallbackStreamWrapper"
                return response

        return Proxy()

    monkeypatch.setattr(router, "available", lambda: True)
    monkeypatch.setattr(router, "_get_router", actual_router)
    monkeypatch.setattr(router, "_budgeted_stream_client", metered_client)
    monkeypatch.setattr(router, "_fallback_meta", lambda _: {"fallback_used": fallback})
    with usage.portfolio_usage_scope(mandate[0], "a", mandate[1]["lease_token"]):
        received = [
            event
            async for event in _stream(
                fallbacks=[
                    {"provider": "unapproved", "model": "other", "api_key": "unapproved-key"}
                ],
            )
        ]
    state, calls = _calls(mandate)
    assert len(wire_requests) == len(router_requests) == len(calls) == 1, received
    assert router_requests[0]["num_retries"] == router_requests[0]["max_retries"] == 0
    assert router_requests[0]["disable_fallbacks"] is True
    assert router_requests[0]["enable_mid_stream_fallback_continuation"] is False
    assert wire_requests[0]["stream_options"] == {"include_usage": True}
    assert wire_requests[0]["model"] == "approved-model"
    assert all(client.is_closed() for client in clients)
    unknown = fallback or receipt != "reported"
    assert state["halted"] is unknown, received
    assert calls[0]["status"] == ("unknown" if unknown else "settled"), received
