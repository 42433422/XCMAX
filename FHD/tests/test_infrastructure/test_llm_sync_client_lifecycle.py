"""Real HTTP keepalive across repeated sync bridges must not cross closed loops."""

import asyncio
import json
import threading
from contextvars import ContextVar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.infrastructure.llm import structured_output as so
from app.infrastructure.llm.providers.openai_compatible_provider import OpenAICompatibleProvider
from app.services.conversation.llm_adapter import OpenAICompatibleAdapter


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            body = json.dumps(
                {"choices": [{"message": {"content": '{"intent":"customers"}'}}]}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    adapter = OpenAICompatibleAdapter(
        provider="openai",
        api_key="test-only",
        model="test",
        base_url=f"http://127.0.0.1:{server.server_port}/v1",
    )
    clients = []
    original = adapter._get_client

    async def observe():
        client = await original()
        clients.append(client)
        return client

    adapter._get_client = observe
    yield OpenAICompatibleProvider(adapter), clients, adapter
    server.shutdown()
    server.server_close()
    worker.join(timeout=2)


def call(provider):
    return so.complete_structured_sync(
        [{"role": "user", "content": "classify"}],
        schema={"type": "object", "required": ["intent"]},
        provider=provider,
    )


def test_repeated_sync_calls_close_real_keepalive_clients_before_loop_exit(provider):
    instance, clients, adapter = provider
    for _ in range(3):
        assert call(instance).data == {"intent": "customers"}
        assert clients[-1].is_closed
    assert len({id(client) for client in clients}) == 3
    assert adapter._client is None


@pytest.mark.asyncio
async def test_sync_worker_preserves_context_and_leaves_async_pool_owned_by_caller(
    provider, monkeypatch
):
    instance, clients, adapter = provider
    owner = ContextVar("test_owner", default="missing")
    token = owner.set("account-a")
    original = instance.chat_completion
    seen = []

    async def observe(*args, **kwargs):
        seen.append(owner.get())
        return await original(*args, **kwargs)

    monkeypatch.setattr(instance, "chat_completion", observe)
    async_client = await adapter._get_client()
    try:
        for _ in range(3):
            assert call(instance).data == {"intent": "customers"}
            assert clients[-1].is_closed
        assert seen == ["account-a"] * 3
        assert not async_client.is_closed
        assert adapter._client is async_client
    finally:
        owner.reset(token)
        await adapter.close()


def test_sync_deadline_cancels_operation_and_closes_its_client(provider, monkeypatch):
    _, clients, adapter = provider
    cancelled = []

    async def stalled(*args, **kwargs):
        await adapter._get_client()
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.append(True)

    monkeypatch.setattr(so, "complete_structured", stalled)
    with pytest.raises(so.StructuredOutputError):
        so.complete_structured_sync([], schema={}, timeout_seconds=0.05)
    assert cancelled == [True]
    assert clients[0].is_closed


def test_concurrent_sync_calls_do_not_share_pools(provider):
    from concurrent.futures import ThreadPoolExecutor

    instance, clients, _ = provider
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: call(instance), range(4)))
    assert all(result.data == {"intent": "customers"} for result in results)
    assert len({id(client) for client in clients}) == 4
    assert all(client.is_closed for client in clients)


def test_pool_reused_within_bridge_and_closed_on_failure(provider, monkeypatch):
    _, clients, adapter = provider

    async def failed(*args, **kwargs):
        first = await adapter._get_client()
        assert await adapter._get_client() is first
        raise ValueError("synthetic validation failure")

    monkeypatch.setattr(so, "complete_structured", failed)
    with pytest.raises(ValueError, match="synthetic validation failure"):
        so.complete_structured_sync([], schema={})
    assert clients[0].is_closed
    assert adapter._client is None
