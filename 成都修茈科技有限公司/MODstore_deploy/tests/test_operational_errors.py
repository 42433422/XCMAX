"""Regression tests: aiohttp client failures must be recoverable.

2026-10-12 production incident: Microsoft Edge TTS returned 403 during
modstore startup warm-up.  edge-tts raises ``aiohttp.WSServerHandshakeError``,
which was missing from ``RECOVERABLE_ERRORS`` so the lifespan handler let it
escape and uvicorn aborted startup for every release (blocking rollback too).
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from modstore_server import edge_tts_service as ets
from modstore_server.operational_errors import RECOVERABLE_ERRORS


def test_aiohttp_client_error_is_recoverable():
    aiohttp_client_exceptions = pytest.importorskip("aiohttp.client_exceptions")
    assert issubclass(aiohttp_client_exceptions.ClientError, RECOVERABLE_ERRORS)
    assert issubclass(
        aiohttp_client_exceptions.WSServerHandshakeError, RECOVERABLE_ERRORS
    )


def _handshake_error():
    aiohttp_client_exceptions = pytest.importorskip("aiohttp.client_exceptions")
    return aiohttp_client_exceptions.WSServerHandshakeError(
        MagicMock(),
        (),
        status=403,
        message="Invalid response status",
    )


def test_warm_defaults_swallows_aiohttp_handshake_failure():
    """A remote TTS outage must not abort application startup."""

    def _stream(*_args, **_kwargs):
        async def _gen():
            raise _handshake_error()
            yield  # pragma: no cover - makes this an async generator

        return _gen()

    fake_communicate = MagicMock()
    fake_communicate.stream = _stream
    fake_edge_tts = MagicMock()
    fake_edge_tts.Communicate.return_value = fake_communicate

    with patch.object(ets, "_EDGE_TTS", fake_edge_tts):
        with patch.object(ets, "_warmed_keys", set()):
            asyncio.run(ets.warm_defaults())
