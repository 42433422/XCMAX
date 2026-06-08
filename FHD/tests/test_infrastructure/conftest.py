"""Shared fixtures for tests/test_infrastructure/ — coverage ramp C3.3-b.

Provides:
* `mock_external_service` — context-manager that patches multiple external
  HTTP / Redis / LLM calls so the test sees a closed network.
* `disable_real_network` — monkeypatches ``httpx.AsyncClient.send`` to fail.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import patch

import pytest


@pytest.fixture
def mock_external_service() -> Iterator[None]:
    """Disable outbound network calls across httpx, requests, urllib."""
    with (
        patch("httpx.AsyncClient.send", side_effect=ConnectionError("mocked")),
        patch("httpx.Client.send", side_effect=ConnectionError("mocked")),
        patch("urllib.request.urlopen", side_effect=ConnectionError("mocked")),
    ):
        yield


@pytest.fixture
def disable_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force ``httpx.AsyncClient.send`` to raise ``ConnectError``."""
    import httpx

    def _boom(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise httpx.ConnectError("disabled by test")

    monkeypatch.setattr(httpx.AsyncClient, "send", _boom)
