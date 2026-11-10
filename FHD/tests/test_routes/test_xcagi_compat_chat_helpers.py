"""Tests for app.fastapi_routes.xcagi_compat_chat_helpers — pure helper functions and models."""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from app.application.ai_chat_app_service import AIChatApplicationService
from app.fastapi_routes import xcagi_compat_chat_helpers as ch
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor

EXACT_SENTENCE = "把 A 产品卖给客户B，10 个，单价 100，开票收款"


def _make_real_app_service():
    """Verify authenticated tenant scope reaches the single model planning boundary."""
    svc = AIChatApplicationService()
    captured = {}

    class TenantCapturingPlanner:
        def plan(self, *_args, **_kwargs):
            from app.infrastructure.tenant_scope import current_tenant_id

            captured["tenant_id"] = current_tenant_id()
            return None

    svc.workflow_planner = TenantCapturingPlanner()
    svc._test_planner_capture = captured
    return svc


def _sse_payloads(chunks):
    return [json.loads(c.decode("utf-8")[len("data: ") :].strip()) for c in chunks]


def test_runtime_context_uses_authenticated_session_actor(trusted_actor):
    actor = trusted_actor(user_id=17, tenant_id=7)
    context = ch._runtime_context_with_authenticated_actor(
        actor.request, {"user_id": "forged", "conversation_id": "web_pro_session", "tenant_id": 999}
    )
    assert context["local_user_id"] == 17
    assert context["actor_id"] == 17
    assert context["user_id"] == "17"
    assert context["conversation_id"] == "web_pro_session"
    assert context["tenant_id"] == 7


def test_runtime_context_discards_untrusted_tenant_when_session_has_none():
    from starlette.requests import Request

    context = ch._runtime_context_with_authenticated_actor(
        Request({"type": "http", "headers": []}), {"user_id": "forged", "tenant_id": 999}
    )
    assert "tenant_id" not in context
    assert "user_id" not in context


@pytest.mark.parametrize("session_state", ["missing", "failed", "authenticated"])
def test_runtime_context_discards_client_actor_claims(session_state, trusted_actor):
    from datetime import timedelta

    from fastapi import HTTPException
    from starlette.requests import Request

    from app.db.models.user import Session
    from app.utils.time import utc_now_naive

    actor = trusted_actor(user_id=17)
    request = (
        actor.request if session_state != "missing" else Request({"type": "http", "headers": []})
    )
    if session_state == "failed":
        with actor.factory.begin() as db:
            db.get(Session, actor.session_row_id).expires_at = utc_now_naive() - timedelta(
                seconds=1
            )
    claims = {
        "actor_id": 999,
        "local_user_id": 999,
        "authenticated_local_user_id": "victim",
        "authenticated_username": "victim",
        "authenticated_display_name": "victim",
    }
    original = {
        **claims,
        "user_id": "forged",
        "conversation_id": "web_pro_session",
        "_mod_authorization": {"mod_id": "forged-mod"},
    }
    if session_state == "failed":
        with pytest.raises(HTTPException) as denied:
            ch._runtime_context_with_authenticated_actor(request, original)
        assert denied.value.status_code == 401
    else:
        context = ch._runtime_context_with_authenticated_actor(request, original)
        expected = {"actor_id": 17, "local_user_id": 17} if session_state == "authenticated" else {}
        assert {key: context[key] for key in claims if key in context} == expected
        assert context.get("user_id") == ("17" if session_state == "authenticated" else None)
        assert context["conversation_id"] == "web_pro_session"
        assert "_mod_authorization" not in context
    assert all(original[key] == value for key, value in claims.items())


def test_runtime_context_uses_server_verified_tutorial_tenant(trusted_actor):
    actor = trusted_actor(user_id=17, tenant_id=7)
    actor.request.state.tutorial_active = True
    actor.request.state.tenant_id = 29
    context = ch._runtime_context_with_authenticated_actor(
        actor.request, {"user_id": "forged", "tenant_id": 999}
    )
    assert context["local_user_id"] == 17
    assert context["tenant_id"] == 29


def test_sales_sse_uses_authenticated_resolved_tenant_even_if_context_conflicts(trusted_actor):
    """W1-10 租户隔离：活跃 compat SSE 处理销售闭环句时，真实 process_chat 在
    current_tenant_id() == 认证解析租户 的 tenant_scope 内执行；即使请求体上下文
    携带冲突 tenant_id，也以认证解析租户为准（resolved tenant wins）。不执行审批、
    不调用 LLM。"""
    from app.infrastructure.tenant_scope import current_tenant_id

    svc = _make_real_app_service()
    captured = svc._test_planner_capture
    real_process_chat = svc.process_chat

    def _spy_process_chat(*args, **kwargs):
        captured["tenant_id"] = current_tenant_id()
        return real_process_chat(*args, **kwargs)

    svc.process_chat = _spy_process_chat

    request = trusted_actor(user_id=17, tenant_id=7).request
    body = ch.XcagiCompatChatBody(
        message=EXACT_SENTENCE,
        user_id="web_pro_session",
        source="pro",
        context={"tenant_id": 999},  # 调用方提供的冲突租户：必须被认证租户覆盖
    )

    with (
        patch("app.application.get_ai_chat_app_service", return_value=svc),
        patch.object(ch, "runtime_context_with_tier", side_effect=lambda c, _t: c),
    ):
        chunks = list(ch._xcagi_planner_stream_bytes(request, body, ai_tier="standard"))

    events = _sse_payloads(chunks)
    errors = [e for e in events if e.get("type") == "error"]
    assert not errors, errors
    assert captured["tenant_id"] == 7


@pytest.mark.parametrize(
    "message,pending,source",
    [
        ("新增产品到数据库 产品:CHATCRUD-STREAM", False, "normal"),
        ("请给 Mac验收客户-7F1B17CE 出货，必须人工审批后才能执行。", False, "normal"),
        ("2桶，客户名称仍为用户需提供，必须人工审批后执行。", False, "normal"),
        ("确认", False, "normal"),
        (" 好的！ ", False, "normal"),
        ("是的", False, "normal"),
        ("执行", False, "normal"),
        ("取消", False, "normal"),
        (" NO. ", False, "normal"),
        ("确认", True, "normal"),
        ("下一步", True, "normal"),
        ("刚才修改的测试客户，联系人现在是谁？请查询实际记录后回答。", False, "normal"),
        ("查询刚才那个客户", False, "normal"),
        ("你好，帮我写首诗", False, "pro"),
    ],
)
def test_stream_controls_and_business_writes_always_use_stateful_mainline(message, pending, source):
    service = MagicMock()
    from app.application.agent_task_context import scoped_conversation_user_id

    owner_key = scoped_conversation_user_id("web_pro_session", {"local_user_id": 17})
    service._pending_workflows = {owner_key: {"agent_run_id": "original"}} if pending else {}
    service.process_chat.return_value = {
        "success": True,
        "response": "已处理",
        "data": {"action": "clarification_required"},
    }
    request = MagicMock(headers={}, cookies={})
    body = ch.XcagiCompatChatBody(message=message, user_id="web_pro_session", source=source)
    with (
        patch("app.application.get_ai_chat_app_service", return_value=service),
        patch.object(
            ch,
            "_runtime_context_with_authenticated_actor",
            side_effect=lambda _r, c: {**dict(c or {}), "local_user_id": 17},
        ),
        patch.object(ch, "runtime_context_with_tier", side_effect=lambda c, _t: c),
        patch.object(ch, "_ensure_chat_db_read_authorized", return_value=(True, None)),
        patch.object(ch, "_message_requires_db_read_token", return_value=False),
        patch.object(ch, "planner_workflow_interrupt_reply", return_value=None),
        patch.object(ch, "_ensure_vector_index_if_needed", return_value=None),
        patch(
            "app.fastapi_routes.xcagi_compat_chat_stream._classify_and_submit_client_issue",
            return_value=None,
        ),
    ):
        events = _sse_payloads(
            list(ch._xcagi_planner_stream_bytes(request, body, ai_tier="standard"))
        )
    assert any(event.get("type") == "done" for event in events)
    service.process_chat.assert_called_once()
    assert service.process_chat.call_args.kwargs["context"]["local_user_id"] == 17


# XcagiCompatChatBody


class TestXcagiCompatChatBody:
    def test_basic_creation(self):
        body = ch.XcagiCompatChatBody(message="hello")
        assert body.message == "hello"
        assert body.context is None
        assert body.system_prompt is None
        assert body.mode is None
        assert body.db_read_token is None
        assert body.db_write_token is None

    def test_alias_message(self):
        body = ch.XcagiCompatChatBody(user_message="hi")
        assert body.message == "hi"

    def test_alias_content(self):
        body = ch.XcagiCompatChatBody(content="test")
        assert body.message == "test"

    def test_alias_text(self):
        body = ch.XcagiCompatChatBody(text="msg")
        assert body.message == "msg"

    def test_alias_query(self):
        body = ch.XcagiCompatChatBody(query="search")
        assert body.message == "search"

    def test_alias_context(self):
        body = ch.XcagiCompatChatBody(message="hi", runtime_context={"k": "v"})
        assert body.context == {"k": "v"}

    def test_alias_system_prompt(self):
        body = ch.XcagiCompatChatBody(message="hi", system="sys")
        assert body.system_prompt == "sys"

    def test_alias_instructions(self):
        body = ch.XcagiCompatChatBody(message="hi", instructions="instr")
        assert body.system_prompt == "instr"

    def test_alias_mode(self):
        body = ch.XcagiCompatChatBody(message="hi", llm_mode="online")
        assert body.mode == "online"

    def test_extra_fields_ignored(self):
        body = ch.XcagiCompatChatBody(message="hi", unknown="x")
        assert not hasattr(body, "unknown")

    def test_empty_message_fails(self):
        with pytest.raises(Exception):
            ch.XcagiCompatChatBody(message="")


# XcagiCompatChatBatchBody


class TestXcagiCompatChatBatchBody:
    def test_basic(self):
        body = ch.XcagiCompatChatBatchBody(messages=["hello", "world"])
        assert body.messages == ["hello", "world"]
        assert body.user_id is None
        assert body.source is None

    def test_default_messages(self):
        body = ch.XcagiCompatChatBatchBody()
        assert body.messages == []


# _chat_request_subject


class TestChatRequestSubject:
    def test_with_xff(self):
        request = MagicMock()
        request.headers = {"x-forwarded-for": "1.2.3.4, 5.6.7.8", "user-agent": "TestAgent/1.0"}
        result = ch._chat_request_subject(request)
        assert result.startswith("1.2.3.4|")

    def test_with_client_host(self):
        request = MagicMock()
        request.headers = {"user-agent": "TestAgent/1.0"}
        request.client = MagicMock()
        request.client.host = "10.0.0.1"
        result = ch._chat_request_subject(request)
        assert result.startswith("10.0.0.1|")

    def test_no_ip(self):
        request = MagicMock()
        request.headers = {"user-agent": "TestAgent/1.0"}
        request.client = None
        result = ch._chat_request_subject(request)
        assert result.startswith("unknown|")

    def test_no_ua(self):
        request = MagicMock()
        request.headers = {"x-forwarded-for": "1.2.3.4", "user-agent": ""}
        result = ch._chat_request_subject(request)
        assert result.endswith("|na")


# _chat_db_read_grace_seconds_left / _touch_chat_db_read_grace


class TestChatDbReadGrace:
    @pytest.fixture(autouse=True)
    def _clear_grace(self):
        ch._chat_db_read_grace_until.clear()
        yield
        ch._chat_db_read_grace_until.clear()

    def test_no_grace(self):
        request = MagicMock()
        request.headers = {"x-forwarded-for": "1.2.3.4", "user-agent": "test"}
        assert ch._chat_db_read_grace_seconds_left(request) == 0

    def test_touch_and_check(self):
        request = MagicMock()
        request.headers = {"x-forwarded-for": "1.2.3.4", "user-agent": "test"}
        ch._touch_chat_db_read_grace(request)
        assert ch._chat_db_read_grace_seconds_left(request) > 0

    def test_expired_grace(self):
        request = MagicMock()
        request.headers = {"x-forwarded-for": "1.2.3.4", "user-agent": "test"}
        ch._touch_chat_db_read_grace(request)
        # Manually expire
        subject = ch._chat_request_subject(request)
        ch._chat_db_read_grace_until[subject] = time.time() - 1
        assert ch._chat_db_read_grace_seconds_left(request) == 0


# _message_requires_db_read_token


class TestMessageRequiresDbReadToken:
    def test_empty(self):
        assert ch._message_requires_db_read_token("") is False

    def test_none(self):
        assert ch._message_requires_db_read_token(None) is False

    def test_query_db(self):
        assert ch._message_requires_db_read_token("查询数据库") is True

    def test_read_product_db(self):
        assert ch._message_requires_db_read_token("读取产品库") is False

    def test_normal_message(self):
        assert ch._message_requires_db_read_token("今天天气怎么样") is False

    def test_db_first(self):
        assert ch._message_requires_db_read_token("数据库查看") is True


# _chat_read_token_required_payload


class TestChatReadTokenRequiredPayload:
    def test_structure(self):
        result = ch._chat_read_token_required_payload("test")
        assert result["requires_token"] is True
        assert result["token_name"] == "DB_READ_TOKEN"
        assert "token_description" in result


# _ensure_chat_db_read_authorized


class TestEnsureChatDbReadAuthorized:
    @pytest.fixture(autouse=True)
    def _clear_grace(self):
        ch._chat_db_read_grace_until.clear()
        yield
        ch._chat_db_read_grace_until.clear()

    def test_no_token_configured(self):
        with patch.object(ch, "effective_db_read_token", return_value=""):
            ok, req = ch._ensure_chat_db_read_authorized(
                MagicMock(), message="查询数据库", provided_token=None
            )
            assert ok is True

    def test_message_does_not_require_token(self):
        with patch.object(ch, "effective_db_read_token", return_value="secret"):
            ok, req = ch._ensure_chat_db_read_authorized(
                MagicMock(), message="hello", provided_token=None
            )
            assert ok is True

    def test_grace_period_active(self):
        request = MagicMock()
        request.headers = {"x-forwarded-for": "1.2.3.4", "user-agent": "test"}
        with patch.object(ch, "effective_db_read_token", return_value="secret"):
            ch._touch_chat_db_read_grace(request)
            ok, req = ch._ensure_chat_db_read_authorized(
                request, message="查询数据库", provided_token=None
            )
            assert ok is True

    def test_correct_token(self):
        request = MagicMock()
        request.headers = {"x-forwarded-for": "1.2.3.4", "user-agent": "test"}
        with patch.object(ch, "effective_db_read_token", return_value="secret"):
            ok, req = ch._ensure_chat_db_read_authorized(
                request, message="查询数据库", provided_token="secret"
            )
            assert ok is True

    def test_wrong_token(self):
        request = MagicMock()
        request.headers = {"x-forwarded-for": "1.2.3.4", "user-agent": "test"}
        with (
            patch.object(ch, "effective_db_read_token", return_value="secret"),
            patch.object(ch, "_chat_db_read_grace_seconds_left", return_value=0),
        ):
            ok, req = ch._ensure_chat_db_read_authorized(
                request, message="查询数据库", provided_token="wrong"
            )
            assert ok is False
            assert req is not None


# ---------------------------------------------------------------------------
# _xcagi_chat_http_exc
# ---------------------------------------------------------------------------


class TestXcagiChatHttpExc:
    def test_timeout_error(self):
        exc = TimeoutError("timeout")
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 504

    def test_authentication_error(self):
        from openai import AuthenticationError

        exc = AuthenticationError(message="bad key", response=MagicMock(), body=None)
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 401

    def test_rate_limit_error(self):
        from openai import RateLimitError

        exc = RateLimitError(message="limited", response=MagicMock(), body=None)
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 429

    def test_api_connection_error(self):
        from openai import APIConnectionError

        exc = APIConnectionError(message="no connection", request=MagicMock())
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 503

    def test_api_error(self):
        from openai import APIError

        exc = APIError(message="api error", request=MagicMock(), body=None)
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 502

    def test_runtime_error(self):
        exc = RuntimeError("runtime fail")
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 503

    def test_value_error_insufficient_balance(self):
        exc = ValueError("余额不足")
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 402

    def test_value_error_402(self):
        exc = ValueError("error 402 payment required")
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 402

    def test_value_error_platform(self):
        exc = ValueError("平台错误 xxx")
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 502

    def test_generic_error(self):
        exc = Exception("unknown")
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 500


# ---------------------------------------------------------------------------
# _xcagi_compat_reply_payload
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _extract_excel_paths_from_message
# ---------------------------------------------------------------------------


class TestExtractExcelPathsFromMessage:
    def test_xlsx(self):
        result = ch._extract_excel_paths_from_message("请分析 @data/test.xlsx 的数据")
        assert len(result) == 1
        assert "data/test.xlsx" in result[0]

    def test_xlsm(self):
        result = ch._extract_excel_paths_from_message("打开 report.xlsm")
        assert len(result) == 1

    def test_xls(self):
        result = ch._extract_excel_paths_from_message("查看 old.xls")
        assert len(result) == 1

    def test_no_excel(self):
        result = ch._extract_excel_paths_from_message("今天天气不错")
        assert result == []

    def test_multiple(self):
        result = ch._extract_excel_paths_from_message("对比 a.xlsx 和 b.xlsx")
        assert len(result) == 2

    def test_dedup(self):
        result = ch._extract_excel_paths_from_message("a.xlsx a.xlsx")
        assert len(result) == 1

    def test_empty(self):
        result = ch._extract_excel_paths_from_message("")
        assert result == []


# ---------------------------------------------------------------------------
# _extract_excel_paths_from_context
# ---------------------------------------------------------------------------


class TestExtractExcelPathsFromContext:
    def test_excel_file_path(self):
        ctx = {"excel_file_path": "data/test.xlsx"}
        result = ch._extract_excel_paths_from_context(ctx)
        assert len(result) == 1

    def test_excel_file_paths(self):
        ctx = {"excel_file_paths": ["a.xlsx", "b.xlsx"]}
        result = ch._extract_excel_paths_from_context(ctx)
        assert len(result) == 2

    def test_excel_analysis(self):
        ctx = {"excel_analysis": {"file_path": "c.xlsx"}}
        result = ch._extract_excel_paths_from_context(ctx)
        assert len(result) == 1

    def test_excel_analysis_preview(self):
        ctx = {"excel_analysis": {"preview_data": {"file_path": "d.xlsx"}}}
        result = ch._extract_excel_paths_from_context(ctx)
        assert len(result) == 1

    def test_non_excel_skipped(self):
        ctx = {"excel_file_path": "data/test.csv"}
        result = ch._extract_excel_paths_from_context(ctx)
        assert len(result) == 0

    def test_empty(self):
        result = ch._extract_excel_paths_from_context({})
        assert result == []


# ---------------------------------------------------------------------------
# _merge_runtime_context_with_message_paths
# ---------------------------------------------------------------------------


class TestMergeRuntimeContextWithMessagePaths:
    def test_no_paths(self):
        ctx, found = ch._merge_runtime_context_with_message_paths({}, "hello")
        assert found == []
        assert "excel_file_path" not in ctx

    def test_message_path_only(self):
        ctx, found = ch._merge_runtime_context_with_message_paths({}, "分析 test.xlsx")
        assert len(found) == 1
        assert ctx["excel_file_path"] == found[0]

    def test_context_path_only(self):
        ctx, found = ch._merge_runtime_context_with_message_paths(
            {"excel_file_path": "data/test.xlsx"}, "hello"
        )
        assert len(found) == 0
        assert ctx["excel_file_paths"] == ["data/test.xlsx"]

    def test_both_sources(self):
        ctx, found = ch._merge_runtime_context_with_message_paths(
            {"excel_file_path": "data/test.xlsx"}, "分析 other.xlsx"
        )
        assert len(found) == 1
        assert len(ctx["excel_file_paths"]) == 2

    def test_same_basename_merged(self):
        ctx, found = ch._merge_runtime_context_with_message_paths(
            {"excel_file_path": "dir/test.xlsx"}, "分析 test.xlsx"
        )
        # Context path should be preferred when basename matches
        assert len(ctx["excel_file_paths"]) >= 1


# ---------------------------------------------------------------------------
# _looks_like_vector_request
# ---------------------------------------------------------------------------


class TestLooksLikeVectorRequest:
    def test_vector_keyword(self):
        assert ch._looks_like_vector_request("建立向量索引") is True

    def test_embedding_keyword(self):
        assert ch._looks_like_vector_request("embedding search") is True

    def test_semantic_search(self):
        assert ch._looks_like_vector_request("semantic search") is True

    def test_normal_message(self):
        assert ch._looks_like_vector_request("今天天气") is False

    def test_empty(self):
        assert ch._looks_like_vector_request("") is False


@pytest.mark.parametrize(
    "helper,key,value,expected",
    [
        (ch._xcagi_chat_timeout_seconds, "XCAGI_CHAT_TIMEOUT_SEC", None, 120.0),
        (ch._xcagi_chat_timeout_seconds, "XCAGI_CHAT_TIMEOUT_SEC", "60", 60.0),
        (ch._xcagi_chat_timeout_seconds, "XCAGI_CHAT_TIMEOUT_SEC", "1", 5.0),
        (ch._xcagi_chat_timeout_seconds, "XCAGI_CHAT_TIMEOUT_SEC", "9999", 600.0),
        (ch._xcagi_chat_timeout_seconds, "XCAGI_CHAT_TIMEOUT_SEC", "bad", 120.0),
        (
            ch._xcagi_stream_first_token_timeout_seconds,
            "XCAGI_CHAT_STREAM_FIRST_TOKEN_TIMEOUT_SEC",
            None,
            20.0,
        ),
        (
            ch._xcagi_stream_first_token_timeout_seconds,
            "XCAGI_CHAT_STREAM_FIRST_TOKEN_TIMEOUT_SEC",
            "30",
            30.0,
        ),
        (
            ch._xcagi_stream_first_token_timeout_seconds,
            "XCAGI_CHAT_STREAM_FIRST_TOKEN_TIMEOUT_SEC",
            "bad",
            20.0,
        ),
        (ch._xcagi_stream_idle_notice_seconds, "XCAGI_CHAT_STREAM_IDLE_NOTICE_SEC", None, 12.0),
        (ch._xcagi_stream_idle_notice_seconds, "XCAGI_CHAT_STREAM_IDLE_NOTICE_SEC", "20", 20.0),
    ],
)
def test_chat_stream_timeout_configuration(monkeypatch, helper, key, value, expected):
    if value is None:
        monkeypatch.delenv(key, raising=False)
    else:
        monkeypatch.setenv(key, value)
    assert helper() == expected


# ---------------------------------------------------------------------------
# _xcagi_chat_timeout_error_payload
# ---------------------------------------------------------------------------


class TestXcagiChatTimeoutErrorPayload:
    def test_structure(self):
        result = ch._xcagi_chat_timeout_error_payload(120.0)
        assert result["success"] is False
        assert "120" in result["message"]
        assert result["execution_outcome"] == "unknown"
        assert result["requires_reconciliation"] is True
        assert "勿重复提交" in result["message"]


# ---------------------------------------------------------------------------
# _sse_event_line
# ---------------------------------------------------------------------------


class TestSseEventLine:
    def test_basic(self):
        result = ch._sse_event_line({"type": "token", "text": "hello"})
        assert result.startswith(b"data: ")
        assert result.endswith(b"\n\n")
        assert b"hello" in result


# ---------------------------------------------------------------------------
# _thinking_steps_from_planner_stream_text
# ---------------------------------------------------------------------------


class TestThinkingStepsFromPlannerStreamText:
    def test_tool_call(self):
        text = "[正在调用工具: search] 结果 [工具已返回]"
        result = ch._thinking_steps_from_planner_stream_text(text)
        assert result is not None
        assert "正在调用工具" in result

    def test_empty(self):
        result = ch._thinking_steps_from_planner_stream_text("")
        assert result is None

    def test_none(self):
        result = ch._thinking_steps_from_planner_stream_text(None)
        assert result is None

    def test_no_tool_markers(self):
        result = ch._thinking_steps_from_planner_stream_text("普通文本")
        assert result is None

    def test_auth_required(self):
        text = "[需要授权: DB_WRITE_TOKEN]"
        result = ch._thinking_steps_from_planner_stream_text(text)
        assert result is not None
        assert "需要授权" in result

    def test_tool_failed(self):
        text = "[工具未成功: timeout]"
        result = ch._thinking_steps_from_planner_stream_text(text)
        assert result is not None
        assert "工具未成功" in result
