from __future__ import annotations

import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Request
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.application.planner_compat_service import (
    _bind_chat_request_identity,
    _execute_ai_chat_mainline,
)
from app.fastapi_routes.domains.conversation.helpers import (
    XcagiCompatChatBody as RouteChatBody,
)
from app.fastapi_routes.xcagi_compat_chat_helpers import XcagiCompatChatBody
from app.services.tools_workflow_registered import (
    _registered_router_dataset_rag,
    _registered_router_employee,
    _registered_router_memory_v2,
    _registered_router_ocr,
)


def _request(*, authorization: str = "", session_id: str = "") -> Request:
    headers = []
    if authorization:
        headers.append((b"authorization", authorization.encode("utf-8")))
    if session_id:
        headers.append((b"x-session-id", session_id.encode("utf-8")))
    return Request(
        {
            "type": "http",
            "headers": headers,
            "method": "POST",
            "path": "/api/ai/chat",
            "client": ("127.0.0.1", 12345),
        }
    )


@pytest.mark.parametrize("body_type", [RouteChatBody, XcagiCompatChatBody])
def test_chat_contract_keeps_meeting_session_id(body_type) -> None:
    body = body_type.model_validate(
        {
            "message": "整理会议纪要",
            "session_id": "meeting-minutes-123",
        }
    )

    assert body.session_id == "meeting-minutes-123"


@pytest.mark.asyncio
async def test_session_identity_overrides_spoofed_ids_and_scopes_meeting_session() -> None:
    request = _request()
    authenticated_user = SimpleNamespace(
        id=42,
        tenant_id=9,
        tier="enterprise",
        role="enterprise",
        is_active=True,
    )
    body = XcagiCompatChatBody(
        message="整理会议纪要",
        user_id="999",
        session_id="meeting-minutes-123",
        context={"user_id": "999", "tenant_id": "999", "source": "mobile_meeting_minutes"},
    )

    with patch(
        "app.infrastructure.auth.dependencies.resolve_session_user",
        return_value=authenticated_user,
    ):
        bound = await _bind_chat_request_identity(request, body)

    assert bound.user_id == "42"
    assert bound.context["user_id"] == "tenant:9:account:enterprise:user:42"
    assert bound.context["subject_user_id"] == 42
    assert bound.context["tenant_id"] == 9
    assert bound.context["account_kind"] == "enterprise"
    assert bound.context["source"] == "mobile_meeting_minutes"
    assert bound.context["dataset_access_context"] == {
        "actor_id": bound.context["user_id"],
        "tenant_id": "9",
        "permissions": [],
        "is_admin": False,
    }
    assert bound.context["dataset_admin"] is False
    assert bound.session_id.startswith("chat_")
    assert "tenant" not in bound.session_id
    assert bound.context["session_id"] == bound.session_id
    assert "meeting-minutes-123" not in bound.session_id


@pytest.mark.asyncio
async def test_mobile_jwt_identity_is_verified_and_rebound_to_current_user() -> None:
    request = _request(authorization="Bearer signed-mobile-token")
    mobile_user = SimpleNamespace(
        id=73,
        tenant_id=12,
        tier="enterprise",
        role="enterprise",
        is_active=True,
    )
    body = XcagiCompatChatBody(
        message="整理会议纪要",
        user_id="404",
        session_id="meeting-minutes-456",
    )

    with (
        patch(
            "app.infrastructure.auth.dependencies.resolve_session_user",
            return_value=None,
        ),
        patch(
            "app.security.mobile_jwt.verify_mobile_jwt",
            return_value={
                "typ": "access",
                "user_id": 73,
                "account_kind": "enterprise",
                "token_scope": "enterprise_pairing",
            },
        ) as verify_token,
        patch(
            "app.fastapi_routes.mobile_api.get_mobile_user",
            new_callable=AsyncMock,
            return_value=mobile_user,
        ) as get_mobile_user,
    ):
        bound = await _bind_chat_request_identity(request, body)

    verify_token.assert_called_once_with("signed-mobile-token")
    get_mobile_user.assert_awaited_once_with(
        request,
        authorization="Bearer signed-mobile-token",
    )
    assert bound.user_id == "73"
    assert bound.context["user_id"] == "tenant:12:account:enterprise:user:73"
    assert bound.session_id.startswith("chat_")


@pytest.mark.asyncio
async def test_same_numeric_user_in_different_tenants_gets_distinct_chat_identity() -> None:
    body = XcagiCompatChatBody(
        message="整理会议纪要",
        session_id="meeting-minutes-shared",
    )

    async def bind_for_tenant(tenant_id: int):
        user = SimpleNamespace(
            id=7,
            tenant_id=tenant_id,
            tier="enterprise",
            role="enterprise",
            is_active=True,
        )
        with patch(
            "app.infrastructure.auth.dependencies.resolve_session_user",
            return_value=user,
        ):
            return await _bind_chat_request_identity(_request(), body)

    tenant_11 = await bind_for_tenant(11)
    tenant_12 = await bind_for_tenant(12)

    assert tenant_11.user_id == tenant_12.user_id == "7"
    assert tenant_11.context["user_id"] == "tenant:11:account:enterprise:user:7"
    assert tenant_12.context["user_id"] == "tenant:12:account:enterprise:user:7"
    assert tenant_11.session_id != tenant_12.session_id


@pytest.mark.asyncio
async def test_conflicting_session_and_mobile_jwt_account_kinds_fail_closed() -> None:
    request = _request(authorization="Bearer signed-mobile-token")
    session_user = SimpleNamespace(
        id=42,
        tenant_id=9,
        tier="admin",
        role="admin",
        is_active=True,
    )
    mobile_user = SimpleNamespace(
        id=42,
        tenant_id=9,
        tier="enterprise",
        role="enterprise",
        is_active=True,
    )
    body = XcagiCompatChatBody(
        message="整理会议纪要",
        user_id="42",
        session_id="meeting-minutes-conflict",
    )

    with (
        patch(
            "app.infrastructure.auth.dependencies.resolve_session_user",
            return_value=session_user,
        ),
        patch(
            "app.security.mobile_jwt.verify_mobile_jwt",
            return_value={
                "typ": "access",
                "user_id": 42,
                "account_kind": "enterprise",
            },
        ),
        patch(
            "app.fastapi_routes.mobile_api.get_mobile_user",
            new_callable=AsyncMock,
            return_value=mobile_user,
        ),
    ):
        with pytest.raises(HTTPException) as raised:
            await _bind_chat_request_identity(request, body)

    assert raised.value.status_code == 401
    assert raised.value.detail == "chat authentication subjects conflict"


@pytest.mark.asyncio
async def test_matching_session_and_mobile_jwt_subjects_share_one_scope() -> None:
    request = _request(authorization="Bearer signed-mobile-token")
    user = SimpleNamespace(
        id=42,
        tenant_id=9,
        tier="enterprise",
        role="enterprise",
        is_active=True,
    )
    body = XcagiCompatChatBody(
        message="整理会议纪要",
        session_id="meeting-minutes-matching",
    )

    with (
        patch(
            "app.infrastructure.auth.dependencies.resolve_session_user",
            return_value=user,
        ),
        patch(
            "app.security.mobile_jwt.verify_mobile_jwt",
            return_value={
                "typ": "access",
                "user_id": 42,
                "account_kind": "enterprise",
            },
        ),
        patch(
            "app.fastapi_routes.mobile_api.get_mobile_user",
            new_callable=AsyncMock,
            return_value=user,
        ),
    ):
        bound = await _bind_chat_request_identity(request, body)

    assert bound.user_id == "42"
    assert bound.context["user_id"] == "tenant:9:account:enterprise:user:42"
    assert bound.context["subject_user_id"] == 42


@pytest.mark.asyncio
async def test_invalid_bearer_never_downgrades_to_anonymous_chat() -> None:
    request = _request(authorization="Bearer invalid-mobile-token")
    body = XcagiCompatChatBody(
        message="旧桌面对话",
        user_id="legacy-local-user",
        session_id="legacy-local-session",
        context={"source": "desktop"},
    )

    with (
        patch(
            "app.infrastructure.auth.dependencies.resolve_session_user",
            return_value=None,
        ),
        patch("app.security.mobile_jwt.verify_mobile_jwt", return_value=None),
    ):
        with pytest.raises(HTTPException) as raised:
            await _bind_chat_request_identity(request, body)

    assert raised.value.status_code == 401
    assert raised.value.detail == "chat access token invalid"


@pytest.mark.asyncio
async def test_invalid_supplied_session_never_downgrades_to_anonymous_chat() -> None:
    request = _request(session_id="expired-session")
    body = XcagiCompatChatBody(message="整理会议纪要")

    with patch(
        "app.infrastructure.auth.dependencies.resolve_session_user",
        return_value=None,
    ):
        with pytest.raises(HTTPException) as raised:
            await _bind_chat_request_identity(request, body)

    assert raised.value.status_code == 401
    assert raised.value.detail == "chat session invalid"


@pytest.mark.asyncio
async def test_anonymous_desktop_fallback_stays_separate_from_authenticated_binding() -> None:
    request = _request()
    body = XcagiCompatChatBody(
        message="旧桌面对话",
        user_id="legacy-local-user",
        session_id="legacy-local-session",
        context={"source": "desktop"},
    )

    with patch(
        "app.infrastructure.auth.dependencies.resolve_session_user",
        return_value=None,
    ):
        bound = await _bind_chat_request_identity(request, body)

    assert bound is body
    assert bound.user_id == "legacy-local-user"
    assert bound.session_id == "legacy-local-session"
    assert bound.context == {"source": "desktop"}


@pytest.mark.asyncio
async def test_authenticated_chat_rebuilds_authorization_context_from_server_truth() -> None:
    request = _request()
    user = SimpleNamespace(
        id=7,
        tenant_id=11,
        tier="enterprise",
        role="enterprise",
        is_active=True,
    )
    body = XcagiCompatChatBody(
        message="整理会议纪要",
        context={
            "source": "mobile_meeting_minutes",
            "dataset_access_context": {
                "tenant_id": "999",
                "permissions": ["*"],
                "is_admin": True,
            },
            "dataset_permissions": ["dataset.admin"],
            "dataset_admin": True,
            "tenantId": 999,
            "workspace_root": "/private/other-tenant",
        },
    )

    with patch(
        "app.infrastructure.auth.dependencies.resolve_session_user",
        return_value=user,
    ):
        bound = await _bind_chat_request_identity(request, body)

    assert bound.context["source"] == "mobile_meeting_minutes"
    assert bound.context["tenant_id"] == 11
    assert bound.context["dataset_tenant_id"] == "11"
    assert bound.context["dataset_permissions"] == []
    assert bound.context["dataset_admin"] is False
    assert bound.context["dataset_access_context"] == {
        "actor_id": "tenant:11:account:enterprise:user:7",
        "tenant_id": "11",
        "permissions": [],
        "is_admin": False,
    }
    assert "tenantId" not in bound.context
    assert "workspace_root" not in bound.context


@pytest.mark.asyncio
async def test_server_bound_dataset_context_ignores_tool_parameter_escalation() -> None:
    request = _request()
    user = SimpleNamespace(
        id=7,
        tenant_id=11,
        tier="enterprise",
        role="enterprise",
        is_active=True,
    )
    body = XcagiCompatChatBody(message="查询知识库")
    with patch(
        "app.infrastructure.auth.dependencies.resolve_session_user",
        return_value=user,
    ):
        bound = await _bind_chat_request_identity(request, body)

    service = SimpleNamespace(query=MagicMock(return_value={"success": False}))
    with patch(
        "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
        return_value=service,
    ):
        _registered_router_dataset_rag(
            "query",
            {
                "dataset_id": "tenant-11-handbook",
                "query": "休假规则",
                "tenant_id": "11",
                "include_answer": False,
                "access_context": {
                    "tenant_id": "999",
                    "permissions": ["*"],
                    "is_admin": True,
                },
                "permissions": ["dataset.admin"],
                "dataset_admin": True,
            },
            bound.context,
            "default",
            "查询知识库",
        )

    access = service.query.call_args.kwargs["access_context"]
    assert access.actor_id == bound.context["user_id"]
    assert access.tenant_id == "11"
    assert access.permissions == frozenset()
    assert access.is_admin is False


def test_server_bound_tools_ignore_model_supplied_identity_and_workspace() -> None:
    runtime_context = {
        "_server_bound_chat_identity": True,
        "user_id": "tenant:11:account:enterprise:user:7",
        "subject_user_id": 7,
        "session_id": "chat_safe",
    }

    memory_service = SimpleNamespace(
        delete_memory=MagicMock(return_value={"success": True}),
    )
    with patch(
        "app.services.user_memory_service.get_user_memory_service",
        return_value=memory_service,
    ):
        _registered_router_memory_v2(
            "delete",
            {"user_id": "victim", "memory_id": "m-1"},
            runtime_context,
            "default",
            "",
        )
    assert memory_service.delete_memory.call_args.args[:2] == (
        "tenant:11:account:enterprise:user:7",
        "m-1",
    )

    execute_employee = MagicMock(return_value={"success": True})
    with (
        patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status",
            return_value={"employee_pack_tools": [], "registered_tool_count": 0},
        ),
        patch(
            "app.application.employee_runtime.executor.execute_employee_task_local",
            execute_employee,
        ),
    ):
        _registered_router_employee(
            "execute",
            {
                "employee_id": "reporter",
                "task": "整理报告",
                "user_id": 999,
                "workspace_root": "/private/victim",
            },
            runtime_context,
            "default",
            "",
        )
    assert execute_employee.call_args.kwargs["user_id"] == 7
    assert execute_employee.call_args.kwargs["workspace_root"] is None

    ocr_domain = SimpleNamespace(emit_ocr_requested=MagicMock(return_value=True))
    with (
        patch("app.fastapi_routes.ocr._get_ocr_service", return_value=SimpleNamespace()),
        patch("app.neuro_bus.domains.ocr_domain.get_ocr_domain", return_value=ocr_domain),
    ):
        result = _registered_router_ocr(
            "request",
            {
                "request_id": "ocr-1",
                "image_url": "https://example.invalid/image.png",
                "user_id": "victim",
            },
            runtime_context,
            "default",
            "",
        )
    assert result["user_id"] == "7"
    assert ocr_domain.emit_ocr_requested.call_args.kwargs["user_id"] == "7"


@pytest.mark.asyncio
async def test_ai_mainline_uses_scoped_identity_while_body_keeps_numeric_owner() -> None:
    body = XcagiCompatChatBody(message="整理会议纪要", user_id="7")
    process_chat = MagicMock(return_value={"success": True, "response": "完成"})
    service = SimpleNamespace(process_chat=process_chat)
    with patch(
        "app.application.ai_chat_app_service.AIChatApplicationService",
        return_value=service,
    ):
        await _execute_ai_chat_mainline(
            body,
            {
                "_server_bound_chat_identity": True,
                "user_id": "tenant:11:account:enterprise:user:7",
                "subject_user_id": 7,
            },
        )

    assert process_chat.call_args.kwargs["user_id"] == "tenant:11:account:enterprise:user:7"


def test_server_bound_chat_persists_numeric_conversation_owner() -> None:
    from app.application.ai_chat_app_service import AIChatApplicationService
    from app.db.base import Base
    from app.db.models import AIConversation, AIConversationSession, User
    from app.services.conversation_service import ConversationService

    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[User.__table__, AIConversationSession.__table__, AIConversation.__table__],
    )
    test_session = sessionmaker(bind=engine, expire_on_commit=False)

    @contextmanager
    def _test_db():
        db = test_session()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    with _test_db() as db:
        db.add(
            User(
                id=7,
                username="meeting-owner",
                password="not-used",
                display_name="Meeting Owner",
                email="",
                role="user",
                is_active=True,
                tier="enterprise",
                industry_id="通用",
            )
        )

    session_id = f"chat_owner_{uuid.uuid4().hex}"
    conversations = ConversationService()
    with (
        patch("app.services.conversation_service.get_db", _test_db),
        patch("app.services.conversation_service.notify_user"),
        patch("app.services.get_conversation_service", return_value=conversations),
    ):
        service = AIChatApplicationService()
        service._persist_chat_turn(
            "tenant:11:account:enterprise:user:7",
            "整理会议纪要",
            {
                "_server_bound_chat_identity": True,
                "user_id": "tenant:11:account:enterprise:user:7",
                "subject_user_id": 7,
                "session_id": session_id,
            },
            {"success": True, "response": "整理完成", "data": {}},
        )

        assert conversations.get_session_ownership(session_id) == (True, 7)
        conversations.delete_session(session_id)
