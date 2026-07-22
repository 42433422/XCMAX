"""app/middleware/neuro_http_trace 单测：HTTP Neuro trace 中间件覆盖。

直接驱动 async 函数（fake request + fake call_next），不起真实 ASGI（铁律4）。
覆盖：redact 敏感头/普通头/截断/异常 / 禁用短路 / 正常完成 / call_next 异常 / publish 异常容错（铁律3）。
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from app.middleware.neuro_http_trace import _redact_headers, neuro_http_trace_middleware


def _make_request(
    method: str = "GET",
    path: str = "/api/health",
    query: str = "",
    headers: dict[str, str] | None = None,
    client_host: str | None = "127.0.0.1",
) -> MagicMock:
    """构造 MagicMock Request，覆盖 middleware 访问的所有属性。"""
    request = MagicMock()
    request.method = method
    request.url.path = path
    request.url.query = query
    request.headers = headers if headers is not None else {}
    if client_host is None:
        request.client = None
    else:
        request.client.host = client_host
    return request


@pytest.fixture
def neuro_enabled(monkeypatch) -> MagicMock:
    """Patch neuro_bus 依赖为 enabled + sampling；返回 publish_neuro_event mock。"""
    monkeypatch.setattr(
        "app.neuro_bus.integrations.intent_integration.is_neuro_stack_enabled",
        MagicMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.neuro_bus.neuro_trace_config.should_sample_http",
        MagicMock(return_value=True),
    )
    publish_mock = MagicMock(return_value=True)
    monkeypatch.setattr(
        "app.neuro_bus.application_neuro_bridge.publish_neuro_event",
        publish_mock,
    )
    return publish_mock


class TestRedactHeaders:
    """_redact_headers 纯函数测试。"""

    def test_sensitive_headers_are_redacted(self):
        headers = {
            "Authorization": "Bearer secret-token",
            "Cookie": "session=abc123",
            "Set-Cookie": "token=xyz",
            "X-API-Key": "key123",
            "X-Auth-Token": "auth-tok",
        }
        result = _redact_headers(headers)
        assert result["Authorization"] == "<redacted>"
        assert result["Cookie"] == "<redacted>"
        assert result["Set-Cookie"] == "<redacted>"
        assert result["X-API-Key"] == "<redacted>"
        assert result["X-Auth-Token"] == "<redacted>"

    def test_sensitive_headers_case_insensitive(self):
        result = _redact_headers(
            {"AUTHORIZATION": "Bearer secret", "Cookie": "s", "x-api-key": "k"}
        )
        assert result["AUTHORIZATION"] == "<redacted>"
        assert result["Cookie"] == "<redacted>"
        assert result["x-api-key"] == "<redacted>"

    def test_normal_headers_preserved(self):
        result = _redact_headers({"Content-Type": "application/json", "X-Request-ID": "abc"})
        assert result["Content-Type"] == "application/json"
        assert result["X-Request-ID"] == "abc"

    def test_long_header_value_truncated_to_200_chars(self):
        result = _redact_headers({"X-Long": "x" * 500})
        assert len(result["X-Long"]) == 200
        assert result["X-Long"] == "x" * 200

    def test_empty_headers_dict(self):
        assert _redact_headers({}) == {}

    def test_non_string_values_converted_to_str(self):
        result = _redact_headers({"X-Count": 42, "X-Flag": True, "X-None": None})
        assert result["X-Count"] == "42"
        assert result["X-Flag"] == "True"
        assert result["X-None"] == "None"

    def test_exception_during_items_returns_empty_dict(self):
        class _BrokenHeaders:
            def items(self):
                raise ValueError("boom")

        assert _redact_headers(_BrokenHeaders()) == {}

    def test_partial_iteration_exception_returns_partial_dict(self):
        class _PartialHeaders:
            def items(self):
                yield "X-Ok", "ok"
                raise ValueError("boom mid-iter")

        assert _redact_headers(_PartialHeaders()) == {"X-Ok": "ok"}


class TestNeuroHttpTraceMiddleware:
    """neuro_http_trace_middleware 异步中间件测试。"""

    async def test_disabled_stack_short_circuits_to_call_next(self, monkeypatch):
        """is_neuro_stack_enabled() == False 时短路，不发布事件。"""
        monkeypatch.setattr(
            "app.neuro_bus.integrations.intent_integration.is_neuro_stack_enabled",
            MagicMock(return_value=False),
        )
        sample_mock = MagicMock(return_value=True)
        monkeypatch.setattr(
            "app.neuro_bus.neuro_trace_config.should_sample_http",
            sample_mock,
        )
        publish_mock = MagicMock()
        monkeypatch.setattr(
            "app.neuro_bus.application_neuro_bridge.publish_neuro_event",
            publish_mock,
        )

        request = _make_request()
        response = MagicMock(status_code=200)

        async def call_next(_req):
            return response

        result = await neuro_http_trace_middleware(request, call_next)

        assert result is response
        sample_mock.assert_not_called()  # 短路求值
        publish_mock.assert_not_called()

    async def test_disabled_sampling_short_circuits_to_call_next(self, monkeypatch):
        """should_sample_http() == False 时短路，不发布事件。"""
        monkeypatch.setattr(
            "app.neuro_bus.integrations.intent_integration.is_neuro_stack_enabled",
            MagicMock(return_value=True),
        )
        monkeypatch.setattr(
            "app.neuro_bus.neuro_trace_config.should_sample_http",
            MagicMock(return_value=False),
        )
        publish_mock = MagicMock()
        monkeypatch.setattr(
            "app.neuro_bus.application_neuro_bridge.publish_neuro_event",
            publish_mock,
        )

        request = _make_request()
        response = MagicMock(status_code=200)

        async def call_next(_req):
            return response

        result = await neuro_http_trace_middleware(request, call_next)

        assert result is response
        publish_mock.assert_not_called()

    async def test_import_failure_short_circuits_to_call_next(self, monkeypatch):
        """is_neuro_stack_enabled 抛 ImportError 时短路，不发布事件。"""
        monkeypatch.setattr(
            "app.neuro_bus.integrations.intent_integration.is_neuro_stack_enabled",
            MagicMock(side_effect=ImportError("missing dep")),
        )
        publish_mock = MagicMock()
        monkeypatch.setattr(
            "app.neuro_bus.application_neuro_bridge.publish_neuro_event",
            publish_mock,
        )

        request = _make_request()
        response = MagicMock(status_code=200)

        async def call_next(_req):
            return response

        result = await neuro_http_trace_middleware(request, call_next)

        assert result is response
        publish_mock.assert_not_called()

    async def test_normal_request_publishes_started_and_completed(self, neuro_enabled):
        """正常请求：发布 started + completed 事件。"""
        request = _make_request(
            method="POST",
            path="/api/orders",
            query="limit=10",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer secret",
            },
            client_host="10.0.0.1",
        )
        response = MagicMock(status_code=201)

        async def call_next(_req):
            return response

        result = await neuro_http_trace_middleware(request, call_next)

        assert result is response
        assert neuro_enabled.call_count == 2

        started_call = neuro_enabled.call_args_list[0]
        assert started_call.args[0] == "http.request.started"
        assert started_call.kwargs["domain"] == "global"
        started = started_call.args[1]
        assert started["method"] == "POST"
        assert started["path"] == "/api/orders"
        assert started["query"] == "limit=10"
        assert started["client"] == "10.0.0.1"
        uuid.UUID(started["request_id"])  # 合法 UUID
        assert started["headers"]["Authorization"] == "<redacted>"
        assert started["headers"]["Content-Type"] == "application/json"

        completed_call = neuro_enabled.call_args_list[1]
        assert completed_call.args[0] == "http.request.completed"
        completed = completed_call.args[1]
        assert completed["status_code"] == 201
        assert completed["request_id"] == started["request_id"]
        assert completed["method"] == "POST"
        assert isinstance(completed["latency_ms"], float)

    async def test_call_next_raises_publishes_failed_and_reraises(self, neuro_enabled):
        """call_next 抛 ValueError 时发布 failed 事件并重新抛出。"""
        request = _make_request(method="GET", path="/api/broken")

        async def call_next(_req):
            raise ValueError("downstream failed")

        with pytest.raises(ValueError, match="downstream failed"):
            await neuro_http_trace_middleware(request, call_next)

        assert neuro_enabled.call_count == 2
        assert neuro_enabled.call_args_list[0].args[0] == "http.request.started"

        failed_call = neuro_enabled.call_args_list[1]
        assert failed_call.args[0] == "http.request.failed"
        failed = failed_call.args[1]
        assert failed["error"] == "downstream failed"
        assert failed["method"] == "GET"
        assert failed["path"] == "/api/broken"
        assert isinstance(failed["latency_ms"], float)

    async def test_publish_started_failure_is_swallowed(self, neuro_enabled):
        """started publish 抛 RuntimeError 时被吞掉，仍走 call_next 与 completed。"""

        def _flaky(event_type, payload, domain="global"):
            if event_type == "http.request.started":
                raise RuntimeError("publish down")
            return True

        neuro_enabled.side_effect = _flaky

        request = _make_request()
        response = MagicMock(status_code=200)

        async def call_next(_req):
            return response

        result = await neuro_http_trace_middleware(request, call_next)

        assert result is response
        assert neuro_enabled.call_count == 2  # started(抛错) + completed

    async def test_publish_completed_failure_is_swallowed(self, neuro_enabled):
        """completed publish 抛 ValueError 时被吞掉，response 正常返回。"""

        def _flaky(event_type, payload, domain="global"):
            if event_type == "http.request.completed":
                raise ValueError("completed publish failed")
            return True

        neuro_enabled.side_effect = _flaky

        request = _make_request()
        response = MagicMock(status_code=200)

        async def call_next(_req):
            return response

        result = await neuro_http_trace_middleware(request, call_next)

        assert result is response

    async def test_publish_failed_failure_swallowed_and_original_reraised(self, neuro_enabled):
        """call_next 抛错且 failed publish 也抛错时，原错误仍正确传播。"""

        def _flaky(event_type, payload, domain="global"):
            if event_type == "http.request.failed":
                raise RuntimeError("failed publish also broken")
            return True

        neuro_enabled.side_effect = _flaky

        request = _make_request()

        async def call_next(_req):
            raise ValueError("original downstream")

        with pytest.raises(ValueError, match="original downstream"):
            await neuro_http_trace_middleware(request, call_next)

    async def test_client_none_yields_empty_string(self, neuro_enabled):
        """request.client 为 None 时 started payload 的 client 字段为空串。"""
        request = _make_request(client_host=None)
        response = MagicMock(status_code=200)

        async def call_next(_req):
            return response

        await neuro_http_trace_middleware(request, call_next)

        started = neuro_enabled.call_args_list[0].args[1]
        assert started["client"] == ""

    async def test_long_path_and_query_are_truncated(self, neuro_enabled):
        """path > 800 与 query > 500 字符在所有 payload 中被截断。"""
        long_path = "/x" + "a" * 1000
        long_query = "q=" + "b" * 600
        request = _make_request(path=long_path, query=long_query)
        response = MagicMock(status_code=200)

        async def call_next(_req):
            return response

        await neuro_http_trace_middleware(request, call_next)

        started = neuro_enabled.call_args_list[0].args[1]
        assert len(started["path"]) == 800
        assert len(started["query"]) == 500

        completed = neuro_enabled.call_args_list[1].args[1]
        assert len(completed["path"]) == 800

    async def test_request_id_is_uuid_and_shared_across_events(self, neuro_enabled):
        """started 与 completed 共享同一个合法 UUID request_id。"""
        request = _make_request()
        response = MagicMock(status_code=200)

        async def call_next(_req):
            return response

        await neuro_http_trace_middleware(request, call_next)

        started = neuro_enabled.call_args_list[0].args[1]
        completed = neuro_enabled.call_args_list[1].args[1]
        uuid.UUID(started["request_id"])  # 不抛即为合法 UUID
        assert started["request_id"] == completed["request_id"]
