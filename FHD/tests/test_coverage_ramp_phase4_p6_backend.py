"""COVERAGE_RAMP Phase 4 round 6: xcagi_compat_chat_helpers comprehensive (15.7%→).

Targets pure helpers + small generators with mocked deps; no real LLM/network.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
from starlette.requests import Request

import app.fastapi_routes.xcagi_compat_chat_helpers as mod
from app.fastapi_routes.xcagi_compat_chat_helpers import (
    XcagiCompatChatBatchBody,
    XcagiCompatChatBody,
    _chat_db_read_grace_seconds_left,
    _chat_read_token_required_payload,
    _chat_request_subject,
    _ensure_chat_db_read_authorized,
    _ensure_vector_index_if_needed,
    _extract_excel_paths_from_context,
    _extract_excel_paths_from_message,
    _looks_like_vector_request,
    _merge_runtime_context_with_message_paths,
    _message_requires_db_read_token,
    _sse_event_line,
    _thinking_steps_from_planner_stream_text,
    _touch_chat_db_read_grace,
    _xcagi_chat_http_exc,
    _xcagi_chat_timeout_error_payload,
    _xcagi_chat_timeout_seconds,
    _xcagi_compat_reply_payload,
    _xcagi_guarded_planner_stream_events,
    _xcagi_stream_first_token_timeout_seconds,
    _xcagi_stream_idle_notice_seconds,
)


def _req(**headers: str) -> Request:
    hdrs = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "path": "/chat",
        "headers": hdrs,
        "query_string": b"",
        "client": ("10.0.0.9", 9000),
    }
    return Request(scope)


# ---------------------------------------------------------------------------
# request subject / grace
# ---------------------------------------------------------------------------


def test_chat_request_subject_xff_priority() -> None:
    req = _req(**{"x-forwarded-for": "203.0.113.5, 10.0.0.1", "user-agent": "UA/1"})
    s = _chat_request_subject(req)
    assert s.startswith("203.0.113.5|")


def test_chat_request_subject_no_ua() -> None:
    req = _req()
    s = _chat_request_subject(req)
    assert "|na" in s


def test_chat_db_read_grace_seconds_expired() -> None:
    mod._chat_db_read_grace_until.clear()
    req = _req()
    subj = _chat_request_subject(req)
    mod._chat_db_read_grace_until[subj] = 1.0  # long past
    assert _chat_db_read_grace_seconds_left(req) == 0
    assert subj not in mod._chat_db_read_grace_until


def test_touch_chat_db_read_grace_returns_window() -> None:
    mod._chat_db_read_grace_until.clear()
    req = _req()
    out = _touch_chat_db_read_grace(req)
    assert out == mod._CHAT_DB_READ_GRACE_SEC
    assert _chat_db_read_grace_seconds_left(req) > 0


# ---------------------------------------------------------------------------
# db read token gating
# ---------------------------------------------------------------------------


def test_message_requires_db_read_token_variants() -> None:
    assert _message_requires_db_read_token("查询产品库的数据") is True
    assert _message_requires_db_read_token("数据库查看一下") is True
    assert _message_requires_db_read_token("") is False
    assert _message_requires_db_read_token("帮我写封邮件") is False


def test_chat_read_token_required_payload() -> None:
    p = _chat_read_token_required_payload("查看数据库")
    assert p["requires_token"] is True
    assert p["token_name"] == "DB_READ_TOKEN"


@patch.object(mod, "effective_db_read_token", return_value="")
def test_ensure_authorized_no_expected_token(_m: MagicMock) -> None:
    ok, payload = _ensure_chat_db_read_authorized(_req(), message="查看数据库", provided_token=None)
    assert ok is True and payload is None


@patch.object(mod, "effective_db_read_token", return_value="secret")
def test_ensure_authorized_message_not_protected(_m: MagicMock) -> None:
    ok, payload = _ensure_chat_db_read_authorized(_req(), message="你好啊", provided_token=None)
    assert ok is True and payload is None


@patch.object(mod, "effective_db_read_token", return_value="secret")
def test_ensure_authorized_correct_token_sets_grace(_m: MagicMock) -> None:
    mod._chat_db_read_grace_until.clear()
    req = _req()
    ok, payload = _ensure_chat_db_read_authorized(
        req, message="查询数据库产品库", provided_token="secret"
    )
    assert ok is True and payload is None
    # grace now active → second protected call passes without token
    ok2, _ = _ensure_chat_db_read_authorized(req, message="查询数据库产品库", provided_token=None)
    assert ok2 is True


@patch.object(mod, "effective_db_read_token", return_value="secret")
def test_ensure_authorized_wrong_token(_m: MagicMock) -> None:
    mod._chat_db_read_grace_until.clear()
    ok, payload = _ensure_chat_db_read_authorized(
        _req(), message="查询数据库产品库", provided_token="nope"
    )
    assert ok is False
    assert payload is not None and payload["requires_token"] is True


# ---------------------------------------------------------------------------
# pydantic bodies / alias choices
# ---------------------------------------------------------------------------


def test_chat_body_alias_content_and_context() -> None:
    b = XcagiCompatChatBody.model_validate({"content": "你好", "runtime_context": {"a": 1}})
    assert b.message == "你好"
    assert b.context == {"a": 1}


def test_chat_body_alias_query_and_system() -> None:
    b = XcagiCompatChatBody.model_validate({"query": "查产品", "instructions": "be brief"})
    assert b.message == "查产品"
    assert b.system_prompt == "be brief"


def test_chat_batch_body_defaults() -> None:
    b = XcagiCompatChatBatchBody.model_validate({"messages": ["a", "b"], "user_id": "u1"})
    assert b.messages == ["a", "b"]
    assert b.user_id == "u1"
    assert b.context is None


# ---------------------------------------------------------------------------
# _xcagi_chat_http_exc branches
# ---------------------------------------------------------------------------


def test_http_exc_timeout() -> None:
    assert _xcagi_chat_http_exc(TimeoutError("slow")).status_code == 504


def test_http_exc_connect_error() -> None:
    exc = httpx.ConnectError("refused")
    assert _xcagi_chat_http_exc(exc).status_code == 503


def test_http_exc_httpx_http_error() -> None:
    req = httpx.Request("POST", "http://x")
    exc = httpx.HTTPStatusError("boom", request=req, response=httpx.Response(500, request=req))
    assert _xcagi_chat_http_exc(exc).status_code == 502


def test_http_exc_authentication_error() -> None:
    from openai import AuthenticationError

    req = httpx.Request("POST", "http://x")
    resp = httpx.Response(401, request=req)
    exc = AuthenticationError("bad key", response=resp, body=None)
    assert _xcagi_chat_http_exc(exc).status_code == 401


def test_http_exc_rate_limit_error() -> None:
    from openai import RateLimitError

    req = httpx.Request("POST", "http://x")
    resp = httpx.Response(429, request=req)
    exc = RateLimitError("too many", response=resp, body=None)
    assert _xcagi_chat_http_exc(exc).status_code == 429


def test_http_exc_api_connection_error() -> None:
    from openai import APIConnectionError

    req = httpx.Request("POST", "http://x")
    exc = APIConnectionError(request=req)
    assert _xcagi_chat_http_exc(exc).status_code == 503


def test_http_exc_api_error() -> None:
    from openai import APIError

    req = httpx.Request("POST", "http://x")
    exc = APIError("api boom", request=req, body=None)
    assert _xcagi_chat_http_exc(exc).status_code == 502


def test_http_exc_runtime_error() -> None:
    assert _xcagi_chat_http_exc(RuntimeError("down")).status_code == 503


def test_http_exc_value_error_balance() -> None:
    assert _xcagi_chat_http_exc(ValueError("余额不足，请充值")).status_code == 402
    assert _xcagi_chat_http_exc(ValueError("402 insufficient")).status_code == 402


def test_http_exc_value_error_platform() -> None:
    assert _xcagi_chat_http_exc(ValueError("平台错误：xxx")).status_code == 502


def test_http_exc_generic_fallback() -> None:
    assert _xcagi_chat_http_exc(KeyError("weird")).status_code == 500


# ---------------------------------------------------------------------------
# reply payload
# ---------------------------------------------------------------------------


def test_reply_payload_from_string() -> None:
    out = _xcagi_compat_reply_payload("简单回复")
    assert out["success"] is True
    assert out["response"] == "简单回复"
    assert out["data"]["text"] == "简单回复"


def test_reply_payload_from_dict_with_thinking() -> None:
    out = _xcagi_compat_reply_payload(
        {"response": "答复", "thinking_steps": "步骤1"},
        runtime_context_update={"k": "v"},
        kitten_attachments={"chart": {"x": 1}},
    )
    assert out["data"]["thinking_steps"] == "步骤1"
    assert out["data"]["runtime_context"] == {"k": "v"}
    assert out["data"]["chart"] == {"x": 1}


# ---------------------------------------------------------------------------
# excel path extraction
# ---------------------------------------------------------------------------


def test_extract_excel_paths_from_message() -> None:
    paths = _extract_excel_paths_from_message("请分析 @424/报价.xlsx 和 data.xls")
    assert any("报价.xlsx" in p for p in paths)
    assert any(p.endswith("data.xls") for p in paths)


def test_extract_excel_paths_from_context_all_sources() -> None:
    ctx = {
        "excel_file_path": "a.xlsx",
        "excel_file_paths": ["b.xls", "ignored.txt"],
        "excel_analysis": {"file_path": "c.xlsm", "preview_data": {"file_path": "d.xlsx"}},
    }
    paths = _extract_excel_paths_from_context(ctx)
    assert "a.xlsx" in paths
    assert "b.xls" in paths
    assert "c.xlsm" in paths
    assert "d.xlsx" in paths
    assert "ignored.txt" not in paths


def test_merge_runtime_context_with_message_paths_none() -> None:
    ctx, found = _merge_runtime_context_with_message_paths({}, "no paths here")
    assert ctx == {}
    assert found == []


def test_merge_runtime_context_with_message_paths_dedup() -> None:
    ctx = {"excel_file_paths": ["/abs/报价.xlsx"]}
    merged, found = _merge_runtime_context_with_message_paths(ctx, "看 @报价.xlsx")
    assert merged["excel_file_path"]
    assert "报价.xlsx" in merged["excel_file_path"]
    assert found


# ---------------------------------------------------------------------------
# vector request
# ---------------------------------------------------------------------------


def test_looks_like_vector_request() -> None:
    assert _looks_like_vector_request("做个向量索引") is True
    assert _looks_like_vector_request("semantic search please") is True
    assert _looks_like_vector_request("普通对话") is False


def test_ensure_vector_index_not_requested() -> None:
    assert _ensure_vector_index_if_needed("普通问题", {}) is None


def test_ensure_vector_index_missing_path() -> None:
    hint = _ensure_vector_index_if_needed("建立向量索引", {})
    assert hint is not None
    assert "Excel" in hint or "路径" in hint


def test_ensure_vector_index_success() -> None:
    executor = MagicMock(return_value='{"success": true}')
    with patch(
        "app.mod_sdk.planner_tools.resolve_planner_tool_executor",
        return_value=executor,
    ):
        out = _ensure_vector_index_if_needed("向量索引", {"excel_file_path": "/tmp/x.xlsx"})
    assert out is None


def test_ensure_vector_index_tool_error() -> None:
    executor = MagicMock(return_value='{"error": "no_sheet", "message": "找不到工作表"}')
    with patch(
        "app.mod_sdk.planner_tools.resolve_planner_tool_executor",
        return_value=executor,
    ):
        out = _ensure_vector_index_if_needed("向量索引", {"excel_file_path": "/tmp/x.xlsx"})
    assert out is not None
    assert "失败" in out


# ---------------------------------------------------------------------------
# timeout env helpers
# ---------------------------------------------------------------------------


def test_chat_timeout_seconds_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XCAGI_CHAT_TIMEOUT_SEC", raising=False)
    assert _xcagi_chat_timeout_seconds() == 120.0


def test_chat_timeout_seconds_clamp_high(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_CHAT_TIMEOUT_SEC", "9999")
    assert _xcagi_chat_timeout_seconds() == 600.0


def test_chat_timeout_seconds_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_CHAT_TIMEOUT_SEC", "abc")
    assert _xcagi_chat_timeout_seconds() == 120.0


def test_stream_first_token_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_CHAT_STREAM_FIRST_TOKEN_TIMEOUT_SEC", "1")
    assert _xcagi_stream_first_token_timeout_seconds() == 3.0  # clamped to min 3
    monkeypatch.setenv("XCAGI_CHAT_STREAM_FIRST_TOKEN_TIMEOUT_SEC", "bad")
    assert _xcagi_stream_first_token_timeout_seconds() == 20.0


def test_stream_idle_notice(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_CHAT_STREAM_IDLE_NOTICE_SEC", "999")
    assert _xcagi_stream_idle_notice_seconds() == 60.0  # clamp max
    monkeypatch.setenv("XCAGI_CHAT_STREAM_IDLE_NOTICE_SEC", "bad")
    assert _xcagi_stream_idle_notice_seconds() == 12.0


def test_chat_timeout_error_payload() -> None:
    p = _xcagi_chat_timeout_error_payload(30.0)
    assert p["success"] is False
    assert "30" in p["message"]


# ---------------------------------------------------------------------------
# sse / thinking steps
# ---------------------------------------------------------------------------


def test_sse_event_line() -> None:
    out = _sse_event_line({"type": "token", "text": "中文"})
    assert out.startswith(b"data: ")
    assert out.endswith(b"\n\n")
    assert "中文".encode() in out


def test_thinking_steps_empty() -> None:
    assert _thinking_steps_from_planner_stream_text("") is None
    assert _thinking_steps_from_planner_stream_text("no markers here") is None


def test_thinking_steps_with_markers() -> None:
    merged = "前言 [正在调用工具: products.query] 中段 [工具已返回 3 条] [需要授权: db_read] 收尾"
    out = _thinking_steps_from_planner_stream_text(merged)
    assert out is not None
    assert "正在调用工具" in out
    assert "工具已返回" in out
    assert "需要授权" in out


# ---------------------------------------------------------------------------
# guarded planner stream generator
# ---------------------------------------------------------------------------


def test_guarded_planner_stream_yields_events() -> None:
    body = XcagiCompatChatBody.model_validate({"message": "hi"})

    def _fake_stream(*a, **k):
        yield {"type": "token", "text": "A"}
        yield {"type": "token", "text": "B"}

    with patch.object(mod, "chat_stream_sse_events", _fake_stream):
        events = list(
            _xcagi_guarded_planner_stream_events(
                body, runtime_context=None, workspace_root="/tmp", client=None
            )
        )
    texts = [e.get("text") for e in events if isinstance(e, dict)]
    assert "A" in texts and "B" in texts


def test_guarded_planner_stream_error_event() -> None:
    body = XcagiCompatChatBody.model_validate({"message": "hi"})

    def _fail_stream(*a, **k):
        raise RuntimeError("stream blew up")
        yield  # pragma: no cover

    with patch.object(mod, "chat_stream_sse_events", _fail_stream):
        events = list(
            _xcagi_guarded_planner_stream_events(
                body, runtime_context=None, workspace_root="/tmp", client=None
            )
        )
    assert any(isinstance(e, dict) and e.get("type") == "error" for e in events)
