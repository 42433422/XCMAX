from __future__ import annotations

import pytest

from modstore_server.infrastructure import http_clients


class _AsyncClient:
    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error
        self.close_calls = 0

    async def aclose(self) -> None:
        self.close_calls += 1
        if self.error is not None:
            raise self.error


class _SyncClient:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


@pytest.mark.asyncio
async def test_close_all_ignores_closed_event_loop_and_detaches_all_clients(
    monkeypatch,
):
    java_client = _AsyncClient(RuntimeError("Event loop is closed"))
    external_client = _AsyncClient()
    sync_client = _SyncClient()
    monkeypatch.setattr(http_clients, "_java_async_client", java_client)
    monkeypatch.setattr(http_clients, "_external_async_client", external_client)
    monkeypatch.setattr(http_clients, "_java_sync_client", sync_client)

    await http_clients.close_all()

    assert java_client.close_calls == 1
    assert external_client.close_calls == 1
    assert sync_client.close_calls == 1
    assert http_clients._java_async_client is None
    assert http_clients._external_async_client is None
    assert http_clients._java_sync_client is None


@pytest.mark.asyncio
async def test_close_all_keeps_unexpected_async_close_errors_observable(monkeypatch):
    client = _AsyncClient(RuntimeError("unexpected client shutdown failure"))
    monkeypatch.setattr(http_clients, "_java_async_client", client)

    with pytest.raises(RuntimeError, match="unexpected client shutdown failure"):
        await http_clients.close_all()

    assert client.close_calls == 1
    assert http_clients._java_async_client is None
