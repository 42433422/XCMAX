"""
Branch-coverage tests for app/services/conversation/modstore_adapter.py.

Targets MISSING_BRANCHES identified by coverage tooling.
Each test is focused on a single uncovered branch path.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any, Dict, Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.conversation.modstore_adapter import (
    ModstoreOpenAICompatibleClient,
    ModstorePlatformAdapter,
    _ModstoreOpenAICompletions,
    _platform_stream_payload_to_openai_chunk,
)

# ---------------------------------------------------------------------------
# Helper: build a minimal adapter without external I/O
# ---------------------------------------------------------------------------

def _make_adapter(platform_url="http://test.local", auth_token="tok", user_id=None):
    with patch.dict(os.environ, {}, clear=False):
        return ModstorePlatformAdapter(
            platform_url=platform_url,
            auth_token=auth_token,
            user_id=user_id,
        )


# ===========================================================================
# L96 → L108: dict with no "choices", no "type"=="error", no content/delta
# → _platform_stream_payload_to_openai_chunk returns None
# ===========================================================================

class TestPlatformStreamPayloadBranches:
    """Targets lines 84-108 (_platform_stream_payload_to_openai_chunk)."""

    def test_dict_with_choices_returns_normalised(self):
        """L84 True path: dict has 'choices'."""
        data = '{"choices": [{"delta": {"content": "hi"}, "finish_reason": null}]}'
        result = _platform_stream_payload_to_openai_chunk(data)
        assert result is not None
        assert "choices" in result

    def test_dict_without_choices_no_content_returns_none(self):
        """L96→L108 fall-through: plain dict with no choices, content, or tool_calls."""
        data = '{"some_other_key": "value"}'
        result = _platform_stream_payload_to_openai_chunk(data)
        assert result is None

    def test_dict_with_finish_reason_only_returns_chunk(self):
        """L96 branch: dict has finish_reason but no content → delta is empty but finish_reason is set."""
        data = '{"finish_reason": "stop"}'
        result = _platform_stream_payload_to_openai_chunk(data)
        assert result is not None
        assert result["choices"][0]["finish_reason"] == "stop"

    def test_dict_with_tool_calls_covered(self):
        """L101-103: dict has tool_calls field."""
        data = '{"tool_calls": [{"id": "tc1"}]}'
        result = _platform_stream_payload_to_openai_chunk(data)
        assert result is not None
        assert result["choices"][0]["delta"]["tool_calls"][0]["id"] == "tc1"


# ===========================================================================
# L244: effective_session_id falsy → skip session token lookup
# ===========================================================================

class TestFromSessionBranches:
    """Targets from_session() missing branches L244, L258, L260."""

    def test_no_session_id_no_request_no_auth_skips_session_lookup(self):
        """No session, no request: goes straight to cls() at L268."""
        with patch(
            "app.services.conversation.modstore_adapter.os.environ.get",
            side_effect=lambda k, d="": {
                "XCAGI_MARKET_BASE_URL": "",
                "MODSTORE_PLATFORM_URL": "http://demo.local",
                "MODSTORE_AUTH_TOKEN": "",
                "LLM_PROVIDER": "xiaomi",
                "LLM_MODEL": "mimo",
                "MODSTORE_USER_ID": "",
            }.get(k, d),
        ):
            adapter = ModstorePlatformAdapter.from_session(session_id=None, request=None)
            assert adapter is not None

    def test_session_id_but_no_token_falls_back_to_latest(self):
        """L244=True, L258=True (no token yet), L260=True: latest_token found."""
        mock_mods = MagicMock()
        mock_mods.session_id_from_request.return_value = "sess123"
        mock_mods.session_market_token.return_value = ""   # nothing for session
        mock_mods.latest_session_market_token.return_value = "latest_tok"

        with patch.dict(os.environ, {
            "MODSTORE_AUTH_TOKEN": "",
            "XCAGI_MARKET_BASE_URL": "http://market.local",
        }, clear=False):
            with patch.dict(
                "sys.modules",
                {"app.fastapi_routes.market_account": mock_mods},
            ):
                adapter = ModstorePlatformAdapter.from_session(session_id="sess123")
        assert adapter.auth_token == "latest_tok"

    def test_session_id_token_already_found_skips_latest(self):
        """L258=False: auth_token already set from session_market_token → no latest lookup."""
        mock_mods = MagicMock()
        mock_mods.session_market_token.return_value = "session_tok"
        mock_mods.latest_session_market_token.return_value = "should_not_use"
        mock_mods.session_id_from_request.return_value = "sess456"

        with patch.dict(os.environ, {
            "MODSTORE_AUTH_TOKEN": "",
            "XCAGI_MARKET_BASE_URL": "http://market.local",
        }, clear=False):
            with patch.dict(
                "sys.modules",
                {"app.fastapi_routes.market_account": mock_mods},
            ):
                adapter = ModstorePlatformAdapter.from_session(session_id="sess456")
        assert adapter.auth_token == "session_tok"
        mock_mods.latest_session_market_token.assert_not_called()

    def test_empty_effective_session_id_logs_warning(self):
        """L244=False (no effective session): skips token lookup, still calls latest."""
        mock_mods = MagicMock()
        mock_mods.session_id_from_request.return_value = ""
        mock_mods.latest_session_market_token.return_value = ""
        mock_mods.session_market_token.return_value = ""

        with patch.dict(os.environ, {
            "MODSTORE_AUTH_TOKEN": "",
            "XCAGI_MARKET_BASE_URL": "http://market.local",
        }, clear=False):
            # Pass a dummy request so auth_token still triggers the try block
            fake_request = MagicMock()
            fake_request.headers.get.return_value = ""
            with patch.dict(
                "sys.modules",
                {"app.fastapi_routes.market_account": mock_mods},
            ):
                adapter = ModstorePlatformAdapter.from_session(request=fake_request)
        # effective_session_id was empty → no session_market_token call
        mock_mods.session_market_token.assert_not_called()

    def test_latest_token_none_no_assign(self):
        """L260=False: latest_session_market_token returns '' (falsy) → auth_token stays ''."""
        mock_mods = MagicMock()
        mock_mods.session_market_token.return_value = ""
        mock_mods.latest_session_market_token.return_value = ""   # falsy
        mock_mods.session_id_from_request.return_value = "sess789"

        with patch.dict(os.environ, {
            "MODSTORE_AUTH_TOKEN": "",
            "XCAGI_MARKET_BASE_URL": "http://market.local",
        }, clear=False):
            with patch.dict(
                "sys.modules",
                {"app.fastapi_routes.market_account": mock_mods},
            ):
                adapter = ModstorePlatformAdapter.from_session(session_id="sess789")
        assert adapter.auth_token == ""


# ===========================================================================
# L360: _get_client when client is already open (False branch)
# ===========================================================================

class TestGetClientAlreadyOpen:
    """L360 False branch: self._client is not None and not closed."""

    @pytest.mark.asyncio
    async def test_get_client_reuses_existing_open_client(self):
        adapter = _make_adapter()
        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        adapter._client = mock_client

        returned = await adapter._get_client()
        assert returned is mock_client


# ===========================================================================
# L517: stream_chat_completion raises when platform_url falsy
# ===========================================================================

class TestStreamChatCompletionNoPlatform:
    """L517 True branch: no platform_url → ValueError."""

    @pytest.mark.asyncio
    async def test_stream_raises_without_platform_url(self):
        adapter = _make_adapter(platform_url="")
        # Force platform_url to be empty (the rstrip might set it anyway)
        adapter.platform_url = ""

        with pytest.raises(ValueError, match="URL未配置"):
            # consume the async generator to trigger the raise
            async for _ in adapter.stream_chat_completion([{"role": "user", "content": "hi"}]):
                pass


# ===========================================================================
# L534-L535 / L534-L537: stream_chat_completion user_id branches
# ===========================================================================

class TestStreamChatCompletionUserIdBranch:
    """L534 True/False: user_id in payload."""

    @pytest.mark.asyncio
    async def test_stream_with_user_id_adds_to_payload(self):
        """L534→L535: user_id is set, so it's added to the payload."""
        adapter = _make_adapter(user_id=42)

        captured_payload: Dict[str, Any] = {}

        async def _aiter_lines():
            return
            yield  # type: ignore[misc]

        mock_resp = AsyncMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.aiter_lines = _aiter_lines

        class _Ctx:
            async def __aenter__(self_inner):
                return mock_resp

            async def __aexit__(self_inner, *a):
                pass

        def fake_stream_sync(*args, **kwargs):
            captured_payload.update(kwargs.get("json") or {})
            return _Ctx()

        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.stream = fake_stream_sync
        adapter._client = mock_client

        async for _ in adapter.stream_chat_completion(
            [{"role": "user", "content": "test"}]
        ):
            break

        assert captured_payload.get("user_id") == 42

    @pytest.mark.asyncio
    async def test_stream_without_user_id_no_payload_key(self):
        """L534→L537: user_id is None, so 'user_id' not added to payload."""
        adapter = _make_adapter(user_id=None)

        captured_payload: Dict[str, Any] = {}

        async def _aiter_lines():
            return
            yield  # type: ignore[misc]

        mock_resp = AsyncMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.aiter_lines = _aiter_lines

        class _Ctx:
            async def __aenter__(self_inner):
                return mock_resp

            async def __aexit__(self_inner, *a):
                pass

        def fake_stream_sync(*args, **kwargs):
            captured_payload.update(kwargs.get("json") or {})
            return _Ctx()

        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.stream = fake_stream_sync
        adapter._client = mock_client

        async for _ in adapter.stream_chat_completion(
            [{"role": "user", "content": "test"}]
        ):
            break

        assert "user_id" not in captured_payload


# ===========================================================================
# L542/L543: async for line + if line.startswith("data:") branches
# ===========================================================================

class TestStreamChatCompletionSSELines:
    """L542/L543: lines iteration; startswith('data:') True and False."""

    @pytest.mark.asyncio
    async def test_data_lines_are_yielded(self):
        """L543=True: lines starting with 'data: ' are yielded."""
        adapter = _make_adapter()

        async def _aiter_lines():
            yield "data: chunk1"
            yield "event: ping"  # should NOT be yielded
            yield "data: chunk2"

        mock_resp = AsyncMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.aiter_lines = _aiter_lines

        class _Ctx:
            async def __aenter__(self):
                return mock_resp

            async def __aexit__(self, *a):
                pass

        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.stream = MagicMock(return_value=_Ctx())
        adapter._client = mock_client

        collected = []
        async for chunk in adapter.stream_chat_completion(
            [{"role": "user", "content": "hi"}]
        ):
            collected.append(chunk)

        assert collected == ["chunk1", "chunk2"]

    @pytest.mark.asyncio
    async def test_non_data_lines_not_yielded(self):
        """L543=False: lines NOT starting with 'data: ' are skipped."""
        adapter = _make_adapter()

        async def _aiter_lines():
            yield "event: ping"
            yield "comment line"
            yield ""

        mock_resp = AsyncMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.aiter_lines = _aiter_lines

        class _Ctx:
            async def __aenter__(self):
                return mock_resp

            async def __aexit__(self, *a):
                pass

        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.stream = MagicMock(return_value=_Ctx())
        adapter._client = mock_client

        collected = []
        async for chunk in adapter.stream_chat_completion(
            [{"role": "user", "content": "hi"}]
        ):
            collected.append(chunk)

        assert collected == []


# ===========================================================================
# L563: chat_completion_sync demo-token check (True branch raises)
# ===========================================================================

class TestChatCompletionSyncDemoTokenBranch:
    """L563 True branch: demo token + non-local base URL → ValueError."""

    def test_demo_token_with_remote_url_raises(self):
        adapter = _make_adapter(auth_token="demo_token_xyz", platform_url="https://api.remote.com")

        mock_surface = MagicMock()
        mock_surface.is_local_demo_market_token.return_value = True
        mock_account = MagicMock()
        mock_account._is_local_market_base.return_value = False  # NOT local → raise

        with patch.dict(
            "sys.modules",
            {
                "app.application.surface_audit_demo_account": mock_surface,
                "app.fastapi_routes.market_account": mock_account,
            },
        ):
            with pytest.raises(ValueError, match="本地演示令牌"):
                adapter.chat_completion_sync([{"role": "user", "content": "hi"}])

    def test_demo_token_with_local_url_does_not_raise(self):
        """L563 False branch: demo token + local base → no raise."""
        adapter = _make_adapter(auth_token="demo_token_xyz", platform_url="http://127.0.0.1:8765")

        mock_surface = MagicMock()
        mock_surface.is_local_demo_market_token.return_value = True
        mock_account = MagicMock()
        mock_account._is_local_market_base.return_value = True  # local → OK

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"content": "ok", "success": True}

        with patch.dict(
            "sys.modules",
            {
                "app.application.surface_audit_demo_account": mock_surface,
                "app.fastapi_routes.market_account": mock_account,
                "app.neuro_bus.application_neuro_bridge": MagicMock(),
            },
        ):
            with patch("httpx.Client") as mock_httpx_client:
                cm = MagicMock()
                cm.__enter__ = MagicMock(return_value=cm)
                cm.__exit__ = MagicMock(return_value=False)
                cm.post.return_value = mock_response
                mock_httpx_client.return_value = cm

                result = adapter.chat_completion_sync([{"role": "user", "content": "hi"}])
        assert "choices" in result


# ===========================================================================
# L583/L584: chat_completion_sync user_id branches
# ===========================================================================

class TestChatCompletionSyncUserIdBranch:
    """L583 True/False: user_id in payload for sync call."""

    def _mock_httpx_client(self, response_json):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = response_json
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=cm)
        cm.__exit__ = MagicMock(return_value=False)
        cm.post.return_value = mock_response
        return cm

    def test_with_user_id_adds_to_payload(self):
        """L583→L584 (True): user_id is set."""
        adapter = _make_adapter(user_id=99)
        cm = self._mock_httpx_client({"content": "ok"})
        with patch.dict(
            "sys.modules",
            {
                "app.application.surface_audit_demo_account": MagicMock(
                    is_local_demo_market_token=MagicMock(return_value=False)
                ),
                "app.fastapi_routes.market_account": MagicMock(
                    _is_local_market_base=MagicMock(return_value=True)
                ),
                "app.neuro_bus.application_neuro_bridge": MagicMock(),
            },
        ):
            with patch("httpx.Client") as mock_cls:
                mock_cls.return_value = cm
                result = adapter.chat_completion_sync([{"role": "user", "content": "hi"}])

        # Check user_id was included in the POST payload
        called_json = cm.post.call_args.kwargs.get("json") or cm.post.call_args[1].get("json") or {}
        assert called_json.get("user_id") == 99

    def test_without_user_id_no_payload_key(self):
        """L583→next (False): user_id is None."""
        adapter = _make_adapter(user_id=None)
        cm = self._mock_httpx_client({"content": "ok"})
        with patch.dict(
            "sys.modules",
            {
                "app.application.surface_audit_demo_account": MagicMock(
                    is_local_demo_market_token=MagicMock(return_value=False)
                ),
                "app.fastapi_routes.market_account": MagicMock(
                    _is_local_market_base=MagicMock(return_value=True)
                ),
                "app.neuro_bus.application_neuro_bridge": MagicMock(),
            },
        ):
            with patch("httpx.Client") as mock_cls:
                mock_cls.return_value = cm
                result = adapter.chat_completion_sync([{"role": "user", "content": "hi"}])

        called_json = cm.post.call_args.kwargs.get("json") or cm.post.call_args[1].get("json") or {}
        assert "user_id" not in called_json


# ===========================================================================
# L630/L631: stream_chat_completion_sync no platform_url raises
# ===========================================================================

class TestStreamChatCompletionSyncBranches:
    """L630/L631/L633 and L644-L674 SSE loop branches."""

    def test_no_platform_url_raises(self):
        """L630→L631 True: raises ValueError."""
        adapter = _make_adapter()
        adapter.platform_url = ""
        with pytest.raises(ValueError):
            list(adapter.stream_chat_completion_sync([{"role": "user", "content": "hi"}]))

    def _make_sync_stream_adapter_with_lines(self, lines, user_id=None, status_code=200):
        adapter = _make_adapter(user_id=user_id)
        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_response.iter_lines.return_value = iter(lines)
        mock_response.read.return_value = b"error body"

        inner_cm = MagicMock()
        inner_cm.__enter__ = MagicMock(return_value=mock_response)
        inner_cm.__exit__ = MagicMock(return_value=False)

        outer_cm = MagicMock()
        outer_cm.__enter__ = MagicMock(return_value=outer_cm)
        outer_cm.__exit__ = MagicMock(return_value=False)
        outer_cm.stream = MagicMock(return_value=inner_cm)

        patcher = patch("httpx.Client", return_value=outer_cm)
        return adapter, patcher

    def test_with_user_id_adds_to_payload(self):
        """L644 True: user_id goes into payload."""
        adapter, patcher = self._make_sync_stream_adapter_with_lines([], user_id=7)
        with patcher as mock_cls:
            outer_cm = mock_cls.return_value
            list(adapter.stream_chat_completion_sync([{"role": "user", "content": "x"}]))
            called_json = outer_cm.stream.call_args.kwargs.get("json") or {}
            assert called_json.get("user_id") == 7

    def test_without_user_id_no_payload_key(self):
        """L644 False: user_id not in payload."""
        adapter, patcher = self._make_sync_stream_adapter_with_lines([], user_id=None)
        with patcher as mock_cls:
            outer_cm = mock_cls.return_value
            list(adapter.stream_chat_completion_sync([{"role": "user", "content": "x"}]))
            called_json = outer_cm.stream.call_args.kwargs.get("json") or {}
            assert "user_id" not in called_json

    def test_event_line_sets_current_event(self):
        """L665: event: line sets current_event."""
        lines = ["event: ping", "data: hello"]
        adapter, patcher = self._make_sync_stream_adapter_with_lines(lines)
        with patcher:
            results = list(adapter.stream_chat_completion_sync([{"role": "user", "content": "x"}]))
        # "ping" is not meta/done so "hello" should be yielded
        assert "hello" in results

    def test_data_line_stripped(self):
        """L668: data: prefix is stripped."""
        lines = ["data: my_payload"]
        adapter, patcher = self._make_sync_stream_adapter_with_lines(lines)
        with patcher:
            results = list(adapter.stream_chat_completion_sync([{"role": "user", "content": "x"}]))
        assert "my_payload" in results

    def test_done_line_breaks(self):
        """L670: [DONE] breaks iteration."""
        lines = ["data: first", "[DONE]", "data: never"]
        adapter, patcher = self._make_sync_stream_adapter_with_lines(lines)
        with patcher:
            results = list(adapter.stream_chat_completion_sync([{"role": "user", "content": "x"}]))
        assert results == ["first"]

    def test_meta_event_skips_data(self):
        """L672: event is 'meta' → all subsequent data lines are skipped (current_event stays 'meta')."""
        lines = ["event: meta", "data: skip_me", "data: also_skip"]
        adapter, patcher = self._make_sync_stream_adapter_with_lines(lines)
        with patcher:
            results = list(adapter.stream_chat_completion_sync([{"role": "user", "content": "x"}]))
        assert "skip_me" not in results
        assert "also_skip" not in results
        assert results == []

    def test_done_event_skips_data(self):
        """L672: event is 'done' → data line is skipped."""
        lines = ["event: done", "data: skip_this"]
        adapter, patcher = self._make_sync_stream_adapter_with_lines(lines)
        with patcher:
            results = list(adapter.stream_chat_completion_sync([{"role": "user", "content": "x"}]))
        assert results == []

    def test_empty_lines_skipped(self):
        """L663: empty/blank text → continue."""
        lines = ["", "  ", "data: real"]
        adapter, patcher = self._make_sync_stream_adapter_with_lines(lines)
        with patcher:
            results = list(adapter.stream_chat_completion_sync([{"role": "user", "content": "x"}]))
        assert results == ["real"]

    def test_http_error_raises(self):
        """L654: status_code >= 400 raises ValueError."""
        adapter, patcher = self._make_sync_stream_adapter_with_lines([], status_code=500)
        with patcher:
            with pytest.raises(ValueError, match="平台错误"):
                list(adapter.stream_chat_completion_sync([{"role": "user", "content": "x"}]))


# ===========================================================================
# L914/L946/L928/L930/L953-L955: _stream in _ModstoreOpenAICompletions
# ===========================================================================

class TestModstoreOpenAICompletionsStream:
    """L914/L946/L928/L930/L953-L955: _stream use_native_stream True/False branches."""

    def _make_completions(self, user_id=None):
        adapter = _make_adapter(user_id=user_id)
        return _ModstoreOpenAICompletions(adapter)

    def test_use_native_stream_false_with_content(self):
        """L914=False path: use_native_stream off, message has content → delta has content."""
        completions = self._make_completions()

        sync_result = {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "hello"},
                    "index": 0,
                    "finish_reason": "stop",
                }
            ],
            "model": "provider/model",
        }
        completions._adapter.chat_completion_sync = MagicMock(return_value=sync_result)

        with patch.dict(os.environ, {"XCAGI_MODSTORE_USE_NATIVE_STREAM": "false"}):
            chunks = list(completions._stream(messages=[{"role": "user", "content": "hi"}]))

        assert len(chunks) == 1
        assert chunks[0].choices[0].delta.content == "hello"

    def test_use_native_stream_false_with_tool_calls(self):
        """L930=True: message has tool_calls → delta includes tool_calls."""
        completions = self._make_completions()

        tc = [{"id": "tc1", "function": {"name": "fn"}}]
        sync_result = {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "", "tool_calls": tc},
                    "index": 0,
                    "finish_reason": "tool_calls",
                }
            ],
            "model": "provider/model",
        }
        completions._adapter.chat_completion_sync = MagicMock(return_value=sync_result)

        with patch.dict(os.environ, {"XCAGI_MODSTORE_USE_NATIVE_STREAM": "0"}):
            chunks = list(completions._stream(messages=[{"role": "user", "content": "hi"}]))

        assert len(chunks) == 1
        delta = chunks[0].choices[0].delta
        assert hasattr(delta, "tool_calls") and delta.tool_calls is not None

    def test_use_native_stream_false_no_content_no_tool_calls(self):
        """L928=False & L930=False: message has no content, no tool_calls → empty delta."""
        completions = self._make_completions()

        sync_result = {
            "choices": [
                {
                    "message": {"role": "assistant", "content": ""},
                    "index": 0,
                    "finish_reason": "stop",
                }
            ],
            "model": "p/m",
        }
        completions._adapter.chat_completion_sync = MagicMock(return_value=sync_result)

        with patch.dict(os.environ, {"XCAGI_MODSTORE_USE_NATIVE_STREAM": "no"}):
            chunks = list(completions._stream(messages=[{"role": "user", "content": "hi"}]))

        assert len(chunks) == 1

    def test_use_native_stream_true_yields_chunks(self):
        """L946=True path: native stream yields multiple chunks."""
        completions = self._make_completions()

        def fake_sync_stream(*args, **kwargs):
            yield '{"choices": [{"delta": {"content": "part1"}, "finish_reason": null}]}'
            yield '{"choices": [{"delta": {"content": "part2"}, "finish_reason": "stop"}]}'

        completions._adapter.stream_chat_completion_sync = MagicMock(
            side_effect=fake_sync_stream
        )

        with patch.dict(os.environ, {"XCAGI_MODSTORE_USE_NATIVE_STREAM": "1"}):
            chunks = list(completions._stream(messages=[{"role": "user", "content": "hi"}]))

        assert len(chunks) == 2

    def test_use_native_stream_true_none_chunk_filtered(self):
        """L954=False (chunk is None): filtered out → not yielded."""
        completions = self._make_completions()

        def fake_sync_stream(*args, **kwargs):
            yield "[DONE]"  # _platform_stream_payload_to_openai_chunk returns None for [DONE]
            yield '{"choices": [{"delta": {"content": "ok"}, "finish_reason": null}]}'

        completions._adapter.stream_chat_completion_sync = MagicMock(
            side_effect=fake_sync_stream
        )

        with patch.dict(os.environ, {"XCAGI_MODSTORE_USE_NATIVE_STREAM": "true"}):
            chunks = list(completions._stream(messages=[{"role": "user", "content": "hi"}]))

        # Only the second payload (non-None) should be yielded
        assert len(chunks) == 1


# ===========================================================================
# L630 / L633: stream_chat_completion_sync user_id True/False already covered
# above in TestStreamChatCompletionSyncBranches — extra alias test
# ===========================================================================

class TestStreamChatCompletionSyncNoPlatformAlias:
    """Confirm L630 False (platform_url present) does NOT raise."""

    def test_platform_url_present_runs(self):
        adapter = _make_adapter()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = iter(["data: ok"])

        inner_cm = MagicMock()
        inner_cm.__enter__ = MagicMock(return_value=mock_response)
        inner_cm.__exit__ = MagicMock(return_value=False)

        outer_cm = MagicMock()
        outer_cm.__enter__ = MagicMock(return_value=outer_cm)
        outer_cm.__exit__ = MagicMock(return_value=False)
        outer_cm.stream = MagicMock(return_value=inner_cm)

        with patch("httpx.Client", return_value=outer_cm):
            results = list(
                adapter.stream_chat_completion_sync([{"role": "user", "content": "hi"}])
            )
        assert results == ["ok"]
