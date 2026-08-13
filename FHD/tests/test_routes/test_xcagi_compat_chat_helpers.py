"""Tests for app.fastapi_routes.xcagi_compat_chat_helpers — pure helper functions and models."""

from __future__ import annotations

import json
import os
import time
from unittest.mock import MagicMock, patch

import pytest

from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.ai_chat_app_service import AIChatApplicationService
from app.application.normal_chat_dispatch import route_normal_mode_message
from app.application.workflow.checkpointer import WorkflowCheckpointer
from app.application.workflow.engine import WorkflowEngine
from app.application.workflow.planner import LLMWorkflowPlanner
from app.fastapi_routes import xcagi_compat_chat_helpers as ch

# 精确验收句（与 W1-10 生产销售写路由一致）
EXACT_SENTENCE = "把 A 产品卖给客户B，10 个，单价 100，开票收款"


class _LLMBomb:
    """Planner model/completion 网关炸弹：任何属性访问或调用即抛错。"""

    def __getattr__(self, _name):  # noqa: ANN001
        raise AssertionError("planner model/completion 网关不得被触达")

    def __call__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("planner model/completion 网关不得被触达")


def _make_real_app_service():
    """真实 AIChatApplicationService：真实 planner / risk gate / approval service /
    AgentOrchestrator，真实 WorkflowEngine(分发器炸弹) + 真实 WorkflowCheckpointer。

    仅隔离已确立的审计/运行/审批持久化边界，绝不替换 route、planner、risk gate、
    approval-required-node 决策或应用服务逻辑：
    - langgraph 运行时/检查点 → 真实 WorkflowEngine(dispatch bomb) / WorkflowCheckpointer；
    - 遗留对话 LLM 服务 → 空壳；
    - AgentRun 仓库 → 内存实现；
    - 审批 DB 持久化（persist_request_to_db / persist_agent_run_link）→ no-op/in-memory。
    """
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.workflow.approval_service import ApprovalService

    def _dispatch_bomb(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("workflow 分发器不得在获批前被调用")

    real_engine = WorkflowEngine(tool_dispatcher=_dispatch_bomb)
    real_checkpointer = WorkflowCheckpointer()

    with (
        patch("app.services.get_ai_conversation_service", return_value=MagicMock()),
        patch(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            return_value=InMemoryAgentRunRepository(),
        ),
        patch(
            "app.application.workflow.approval_persistence.persist_agent_run_link",
            return_value=None,
        ),
    ):
        svc = AIChatApplicationService(
            workflow_runtime=real_engine,
            workflow_checkpointer=real_checkpointer,
        )
    # 使用独立的真实审批服务，避免其它测试对进程级单例安装的 mock 污染审批判定。
    svc.approval_service = ApprovalService()
    svc.approval_service._persist_request_to_db = lambda req, **k: {  # noqa: ARG005
        "request_no": req.request_id
    }
    # 计划落库为尽力而为的持久化边界 → no-op，保持测试隔离。
    svc._persist_plan_state = lambda *a, **k: None
    # planner 实例 model/completion 网关 → 炸弹（确定性 bypass 不触达）。
    svc.workflow_planner._ai_service = _LLMBomb()
    return svc


def _sse_payloads(chunks):
    return [json.loads(c.decode("utf-8")[len("data: ") :].strip()) for c in chunks]


def test_runtime_context_uses_authenticated_session_actor():
    request = MagicMock()
    user = MagicMock(id=17)
    with (
        patch("app.infrastructure.auth.dependencies.resolve_session_user", return_value=user),
        patch(
            "app.infrastructure.auth.tenant_context.resolve_tenant_id",
            return_value=7,
        ),
    ):
        context = ch._runtime_context_with_authenticated_actor(
            request, {"user_id": "web_pro_session", "tenant_id": 999}
        )
    assert context["local_user_id"] == 17
    assert context["actor_id"] == 17
    assert context["user_id"] == "web_pro_session"
    # 认证解析出的租户覆盖调用方上下文里的冲突租户（resolved tenant wins）。
    assert context["tenant_id"] == 7


def test_runtime_context_discards_untrusted_tenant_when_session_has_none():
    request = MagicMock()
    with (
        patch(
            "app.infrastructure.auth.dependencies.resolve_session_user",
            return_value=None,
        ),
        patch(
            "app.infrastructure.auth.tenant_context.resolve_tenant_id",
            return_value=None,
        ),
    ):
        context = ch._runtime_context_with_authenticated_actor(
            request, {"user_id": "web_pro_session", "tenant_id": 999}
        )

    assert "tenant_id" not in context


def test_runtime_context_uses_server_verified_tutorial_tenant():
    request = MagicMock()
    request.state.tutorial_active = True
    request.state.tenant_id = 29
    user = MagicMock(id=17)
    with (
        patch("app.infrastructure.auth.dependencies.resolve_session_user", return_value=user),
        patch(
            "app.infrastructure.auth.tenant_context.resolve_tenant_id",
            return_value=7,
        ) as session_tenant,
    ):
        context = ch._runtime_context_with_authenticated_actor(
            request, {"user_id": "web_pro_session", "tenant_id": 999}
        )

    assert context["local_user_id"] == 17
    assert context["tenant_id"] == 29
    session_tenant.assert_not_called()


def test_sales_sse_uses_authenticated_resolved_tenant_even_if_context_conflicts():
    """W1-10 租户隔离：活跃 compat SSE 处理销售闭环句时，真实 process_chat 在
    current_tenant_id() == 认证解析租户 的 tenant_scope 内执行；即使请求体上下文
    携带冲突 tenant_id，也以认证解析租户为准（resolved tenant wins）。不执行审批、
    不调用 LLM。"""
    from app.infrastructure.tenant_scope import current_tenant_id

    svc = _make_real_app_service()
    captured: dict[str, int | None] = {}
    real_process_chat = svc.process_chat

    def _spy_process_chat(*args, **kwargs):  # noqa: ANN002, ANN003
        captured["tenant_id"] = current_tenant_id()
        return real_process_chat(*args, **kwargs)

    svc.process_chat = _spy_process_chat

    request = MagicMock()
    request.headers = {}
    request.cookies = {}
    body = ch.XcagiCompatChatBody(
        message=EXACT_SENTENCE,
        user_id="web_pro_session",
        source="pro",
        context={"tenant_id": 999},  # 调用方提供的冲突租户：必须被认证租户覆盖
    )

    with (
        patch("app.application.get_ai_chat_app_service", return_value=svc),
        patch(
            "app.infrastructure.auth.tenant_context.resolve_tenant_id",
            return_value=7,
        ),
        patch.object(ch, "runtime_context_with_tier", side_effect=lambda c, _t: c),
    ):
        chunks = list(ch._xcagi_planner_stream_bytes(request, body, ai_tier="standard"))

    events = _sse_payloads(chunks)
    errors = [e for e in events if e.get("type") == "error"]
    assert not errors, errors
    # 真实 process_chat 已在认证租户作用域内执行（resolved tenant wins）。
    assert captured["tenant_id"] == 7


def test_stream_business_db_write_uses_stateful_approval_mainline():
    request = MagicMock()
    request.headers = {}
    request.cookies = {}
    service = MagicMock()
    service._pending_workflows = {}
    service.process_chat.return_value = {
        "success": True,
        "response": "请确认写入预览",
        "data": {"action": "workflow_confirmation_required"},
    }
    body = ch.XcagiCompatChatBody(
        message="新增产品到数据库 产品:CHATCRUD-STREAM",
        user_id="web_pro_session",
        source="pro",
    )
    with (
        patch("app.application.get_ai_chat_app_service", return_value=service),
        patch.object(
            ch,
            "_runtime_context_with_authenticated_actor",
            side_effect=lambda _request, context: {**dict(context or {}), "local_user_id": 17},
        ),
        patch.object(ch, "runtime_context_with_tier", side_effect=lambda context, _tier: context),
    ):
        chunks = list(ch._xcagi_planner_stream_bytes(request, body, ai_tier="standard"))

    assert len(chunks) == 2
    service.process_chat.assert_called_once()
    assert service.process_chat.call_args.kwargs["context"]["local_user_id"] == 17


def test_sales_sentence_routes_to_app_service_no_llm_then_approval_pending():
    """W1-10 精确验收句经活跃 compat SSE 直接进入真实应用服务，绝不创建 LLM 客户端、
    不触碰 legacy planner stream，产出一个正常 done 事件（action=workflow_confirmation_required，
    而非 error 事件），随后「确认」返回 approval_pending。

    ``create_modstore_openai_client_from_request``（LLM 客户端创建）、
    ``_xcagi_guarded_planner_stream_events``（legacy planner stream）、
    ``AgentToolExecutor.execute``（业务工具执行）以及 planner 的
    ``_plan_with_react_multiagent`` / ``request_planner_completion`` /
    ``_get_planner_http_client`` 均安装炸弹：一旦被调用即抛错，测试失败。
    """
    svc = _make_real_app_service()
    request = MagicMock()
    request.headers = {}
    request.cookies = {}
    body = ch.XcagiCompatChatBody(message=EXACT_SENTENCE, user_id="web_pro_session", source="pro")

    def _bomb(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("LLM 客户端 / legacy planner / 工具执行路径不得被触达")

    with (
        patch("app.application.get_ai_chat_app_service", return_value=svc),
        patch.object(
            ch,
            "create_modstore_openai_client_from_request",
            side_effect=_bomb,
        ),
        patch.object(
            ch,
            "_xcagi_guarded_planner_stream_events",
            side_effect=_bomb,
        ),
        patch.object(ch, "runtime_context_with_tier", side_effect=lambda c, _t: c),
        patch.object(AgentToolExecutor, "execute", side_effect=_bomb),
        patch.object(
            LLMWorkflowPlanner,
            "_plan_with_react_multiagent",
            side_effect=_bomb,
        ),
        patch(
            "app.application.workflow.planner.request_planner_completion",
            side_effect=_bomb,
        ),
        patch(
            "app.application.workflow.planner._get_planner_http_client",
            side_effect=_bomb,
        ),
    ):
        chunks = list(ch._xcagi_planner_stream_bytes(request, body, ai_tier="standard"))
        # 首响应后审批已挂起（获批前不分发业务）。
        assert svc._pending_workflows["web_pro_session"]["approval_required"] is True
        # 同一服务实例在全部炸弹仍生效时驱动确认 → approval_pending（确认期间也不得执行工具）。
        resp2 = svc.process_chat(
            user_id="web_pro_session", message="确认", context={}, source="pro"
        )

    events = _sse_payloads(chunks)
    errors = [e for e in events if e.get("type") == "error"]
    assert not errors, errors
    done = [e for e in events if e.get("type") == "done"]
    assert len(done) == 1

    done_payload = done[0]["result"]
    assert done_payload["data"]["action"] == "workflow_confirmation_required"
    # 首响应即进入待确认：恰好一个审批节点 sales.execute_closed_loop，获批前绝不分发业务。
    inner = done_payload["data"]["data"]
    assert inner["approval_required"] is True
    assert inner["approval_nodes"] == [
        {
            "node_id": "sales_execute_closed_loop",
            "tool_id": "sales",
            "action": "execute_closed_loop",
        }
    ]

    # 同一服务实例驱动确认 → approval_pending
    assert resp2["data"]["action"] == "approval_pending"
    inner = resp2["data"]["data"]
    assert inner["approval_required"] is True
    assert inner["approval_path"] == "/mod/xcagi-approval-bridge/approval-hub/workspace"
    request_ids = inner["approval_request_ids"]
    assert isinstance(request_ids, list) and len(request_ids) == 1
    assert str(request_ids[0]).strip()
    # approval_pending 响应带完整 params：高风险/幂等生产图载荷原样保留。
    nodes = inner["approval_nodes"]
    assert len(nodes) == 1
    node = nodes[0]
    assert node["node_id"] == "sales_execute_closed_loop"
    assert node["tool_id"] == "sales"
    assert node["action"] == "execute_closed_loop"
    payload = route_normal_mode_message(EXACT_SENTENCE)["payload"]
    assert node["params"]["payload"] == payload


def test_casual_chat_not_diverted_to_app_service():
    """非销售/闲聊回归：活跃 compat SSE 仅在精确闭环写意图时直达应用服务；
    闲聊仍走 legacy 路径，绝不把普通消息广泛分流到 ``process_chat``。"""
    service = MagicMock()
    service._pending_workflows = {}
    service.process_chat.side_effect = AssertionError("闲聊不得分流到应用服务")
    request = MagicMock()
    request.headers = {}
    request.cookies = {}
    body = ch.XcagiCompatChatBody(message="你好，帮我写首诗", user_id="web_casual", source="pro")

    casual_done = {"type": "done", "result": {"success": True, "data": {"action": "casual"}}}
    with (
        patch("app.application.get_ai_chat_app_service", return_value=service),
        patch.object(
            ch,
            "create_modstore_openai_client_from_request",
            return_value=MagicMock(),
        ),
        patch.object(
            ch,
            "_xcagi_guarded_planner_stream_events",
            return_value=iter([{"type": "token", "text": "你好"}, casual_done]),
        ),
        patch.object(ch, "runtime_context_with_tier", side_effect=lambda c, _t: c),
    ):
        chunks = list(ch._xcagi_planner_stream_bytes(request, body, ai_tier="standard"))

    events = _sse_payloads(chunks)
    service.process_chat.assert_not_called()
    # 闲聊走 legacy 路径：产出 token + done，未被打包到应用服务。
    assert any(e.get("type") == "done" for e in events)


# ---------------------------------------------------------------------------
# XcagiCompatChatBody
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# XcagiCompatChatBatchBody
# ---------------------------------------------------------------------------


class TestXcagiCompatChatBatchBody:
    def test_basic(self):
        body = ch.XcagiCompatChatBatchBody(messages=["hello", "world"])
        assert body.messages == ["hello", "world"]
        assert body.user_id is None
        assert body.source is None

    def test_default_messages(self):
        body = ch.XcagiCompatChatBatchBody()
        assert body.messages == []


# ---------------------------------------------------------------------------
# _chat_request_subject
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# _chat_db_read_grace_seconds_left / _touch_chat_db_read_grace
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# _message_requires_db_read_token
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# _chat_read_token_required_payload
# ---------------------------------------------------------------------------


class TestChatReadTokenRequiredPayload:
    def test_structure(self):
        result = ch._chat_read_token_required_payload("test")
        assert result["requires_token"] is True
        assert result["token_name"] == "DB_READ_TOKEN"
        assert "token_description" in result


# ---------------------------------------------------------------------------
# _ensure_chat_db_read_authorized
# ---------------------------------------------------------------------------


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


class TestXcagiCompatReplyPayload:
    def test_string_reply(self):
        with patch(
            "app.legacy.chat.legacy_chat_adapter.get_last_tool_result",
            return_value=None,
            create=True,
        ):
            result = ch._xcagi_compat_reply_payload("hello")
            assert result["success"] is True
            assert result["response"] == "hello"

    def test_dict_reply(self):
        with patch(
            "app.legacy.chat.legacy_chat_adapter.get_last_tool_result",
            return_value=None,
            create=True,
        ):
            result = ch._xcagi_compat_reply_payload(
                {"response": "world", "thinking_steps": "step1"}
            )
            assert result["response"] == "world"
            assert result["data"]["thinking_steps"] == "step1"

    def test_dict_reply_text_key(self):
        with patch(
            "app.legacy.chat.legacy_chat_adapter.get_last_tool_result",
            return_value=None,
            create=True,
        ):
            result = ch._xcagi_compat_reply_payload({"text": "msg"})
            assert result["response"] == "msg"

    def test_with_runtime_context(self):
        with patch(
            "app.legacy.chat.legacy_chat_adapter.get_last_tool_result",
            return_value=None,
            create=True,
        ):
            result = ch._xcagi_compat_reply_payload("hello", runtime_context_update={"k": "v"})
            assert result["data"]["runtime_context"] == {"k": "v"}

    def test_with_kitten_attachments(self):
        with patch(
            "app.legacy.chat.legacy_chat_adapter.get_last_tool_result",
            return_value=None,
            create=True,
        ):
            result = ch._xcagi_compat_reply_payload("hello", kitten_attachments={"chart": "data"})
            assert result["data"]["chart"] == "data"

    def test_kitten_attachments_none_skipped(self):
        with patch(
            "app.legacy.chat.legacy_chat_adapter.get_last_tool_result",
            return_value=None,
            create=True,
        ):
            result = ch._xcagi_compat_reply_payload("hello", kitten_attachments={"chart": None})
            assert "chart" not in result["data"]


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


# ---------------------------------------------------------------------------
# _xcagi_chat_timeout_seconds
# ---------------------------------------------------------------------------


class TestXcagiChatTimeoutSeconds:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("XCAGI_CHAT_TIMEOUT_SEC", raising=False)
        assert ch._xcagi_chat_timeout_seconds() == 120.0

    def test_custom(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_TIMEOUT_SEC", "60")
        assert ch._xcagi_chat_timeout_seconds() == 60.0

    def test_clamped_min(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_TIMEOUT_SEC", "1")
        assert ch._xcagi_chat_timeout_seconds() == 5.0

    def test_clamped_max(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_TIMEOUT_SEC", "9999")
        assert ch._xcagi_chat_timeout_seconds() == 600.0

    def test_invalid(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_TIMEOUT_SEC", "bad")
        assert ch._xcagi_chat_timeout_seconds() == 120.0


# ---------------------------------------------------------------------------
# _xcagi_stream_first_token_timeout_seconds
# ---------------------------------------------------------------------------


class TestXcagiStreamFirstTokenTimeoutSeconds:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("XCAGI_CHAT_STREAM_FIRST_TOKEN_TIMEOUT_SEC", raising=False)
        assert ch._xcagi_stream_first_token_timeout_seconds() == 20.0

    def test_custom(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_STREAM_FIRST_TOKEN_TIMEOUT_SEC", "30")
        assert ch._xcagi_stream_first_token_timeout_seconds() == 30.0

    def test_invalid(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_STREAM_FIRST_TOKEN_TIMEOUT_SEC", "bad")
        assert ch._xcagi_stream_first_token_timeout_seconds() == 20.0


# ---------------------------------------------------------------------------
# _xcagi_stream_idle_notice_seconds
# ---------------------------------------------------------------------------


class TestXcagiStreamIdleNoticeSeconds:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("XCAGI_CHAT_STREAM_IDLE_NOTICE_SEC", raising=False)
        assert ch._xcagi_stream_idle_notice_seconds() == 12.0

    def test_custom(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_STREAM_IDLE_NOTICE_SEC", "20")
        assert ch._xcagi_stream_idle_notice_seconds() == 20.0


# ---------------------------------------------------------------------------
# _xcagi_chat_timeout_error_payload
# ---------------------------------------------------------------------------


class TestXcagiChatTimeoutErrorPayload:
    def test_structure(self):
        result = ch._xcagi_chat_timeout_error_payload(120.0)
        assert result["success"] is False
        assert "120" in result["message"]
        assert "XCAGI_CHAT_TIMEOUT_SEC" in result["message"]


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
