"""Own HTTP pools for a short-lived sync bridge, closing them before its loop exits."""

from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from contextvars import ContextVar

import httpx

Scope = tuple[dict[tuple[object, str], httpx.AsyncClient], AsyncExitStack]
_scope: ContextVar[Scope | None] = ContextVar("llm_http_client_scope", default=None)


@asynccontextmanager
async def isolated_http_clients() -> AsyncIterator[None]:
    async with AsyncExitStack() as stack:
        token = _scope.set(({}, stack))
        try:
            yield
        finally:
            _scope.reset(token)


def scoped_http_client(
    owner: object, kind: str, factory: Callable[[], httpx.AsyncClient]
) -> httpx.AsyncClient | None:
    scope = _scope.get()
    if scope is None:
        return None
    clients, stack = scope
    key = (owner, kind)
    client = clients.get(key)
    if client is None or client.is_closed:
        client = factory()
        clients[key] = client
        stack.push_async_callback(client.aclose)
    return client
