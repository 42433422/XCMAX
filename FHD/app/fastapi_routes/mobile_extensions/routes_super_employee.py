"""SuperEmployeeRoutes: explicit collaborators for one mobile capability."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from anyio import CancelScope
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from app.fastapi_routes.mobile_extensions.models import (
    ClaudeSuperEmployeeMobileMessageBody,
    CodexSuperEmployeeMobileMessageBody,
    CursorSuperEmployeeMobileMessageBody,
    TraeSuperEmployeeMobileMessageBody,
)
from app.fastapi_routes.mobile_extensions.ports import (
    ClaudeSuperEmployeeServiceFactory,
    ClosableEventStream,
    CodexSuperEmployeeServiceFactory,
    CursorSuperEmployeeServiceFactory,
    FactoryContextCall,
    MobilePrincipal,
    MobileRequestUserIdCall,
    MobileSessionMetaCall,
    RequireMobileAdminCall,
    SseLineCall,
    StreamSuperEmployeeInvokeCall,
    SuperEmployeePort,
    TraeSuperEmployeeServiceFactory,
    UserDependency,
)
from app.utils.device_system.mobile_api import format_mobile_response
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
_StreamRead = tuple[dict[str, Any] | None, BaseException | None]


@dataclass(frozen=True)
class SuperEmployeeRoutesPorts:
    mobile_request_user_id: MobileRequestUserIdCall
    require_mobile_admin: RequireMobileAdminCall
    codex_super_employee_service: CodexSuperEmployeeServiceFactory
    mobile_session_meta: MobileSessionMetaCall
    factory_context: FactoryContextCall
    claude_super_employee_service: ClaudeSuperEmployeeServiceFactory
    cursor_super_employee_service: CursorSuperEmployeeServiceFactory
    trae_super_employee_service: TraeSuperEmployeeServiceFactory
    stream_super_employee_invoke: StreamSuperEmployeeInvokeCall
    sse_line: SseLineCall


class SuperEmployeeRoutes:
    def __init__(self, ports: SuperEmployeeRoutesPorts, get_user: UserDependency) -> None:
        self.ports = ports
        self.router = router = APIRouter()

        @router.get("/admin/codex-super-employee/messages", response_model=None)
        async def mobile_admin_codex_super_employee_messages(
            request: Request,
            limit: int = Query(default=80, ge=1, le=200),
            user: MobilePrincipal | None = Depends(get_user),
        ) -> object:
            """移动端管理员信息页的 Codex 超级员工对话记录（仅管理端）。"""
            return self._messages(request, "codex", limit, user)

        self.mobile_admin_codex_super_employee_messages = mobile_admin_codex_super_employee_messages

        @router.post("/admin/codex-super-employee/messages", response_model=None)
        async def mobile_admin_codex_super_employee_invoke(
            request: Request,
            body: CodexSuperEmployeeMobileMessageBody,
            user: MobilePrincipal | None = Depends(get_user),
        ) -> object:
            """移动端管理员信息页的软件内 Codex 调用入口（仅管理端）。"""
            return self._invoke(request, "codex", body, user)

        self.mobile_admin_codex_super_employee_invoke = mobile_admin_codex_super_employee_invoke

        @router.get("/admin/claude-super-employee/messages", response_model=None)
        async def mobile_admin_claude_super_employee_messages(
            request: Request,
            limit: int = Query(default=80, ge=1, le=200),
            user: MobilePrincipal | None = Depends(get_user),
        ) -> object:
            """移动端管理员信息页的 Claude 超级员工对话记录（仅管理端）。"""
            return self._messages(request, "claude", limit, user)

        self.mobile_admin_claude_super_employee_messages = (
            mobile_admin_claude_super_employee_messages
        )

        @router.post("/admin/claude-super-employee/messages", response_model=None)
        async def mobile_admin_claude_super_employee_invoke(
            request: Request,
            body: ClaudeSuperEmployeeMobileMessageBody,
            user: MobilePrincipal | None = Depends(get_user),
        ) -> object:
            """移动端管理员信息页的软件内 Claude 调用入口（仅管理端）。"""
            return self._invoke(request, "claude", body, user)

        self.mobile_admin_claude_super_employee_invoke = mobile_admin_claude_super_employee_invoke

        @router.get("/admin/cursor-super-employee/messages", response_model=None)
        async def mobile_admin_cursor_super_employee_messages(
            request: Request,
            limit: int = Query(default=80, ge=1, le=200),
            user: MobilePrincipal | None = Depends(get_user),
        ) -> object:
            """移动端管理员信息页的 Cursor 超级员工对话记录（仅管理端）。"""
            return self._messages(request, "cursor", limit, user)

        self.mobile_admin_cursor_super_employee_messages = (
            mobile_admin_cursor_super_employee_messages
        )

        @router.post("/admin/cursor-super-employee/messages", response_model=None)
        async def mobile_admin_cursor_super_employee_invoke(
            request: Request,
            body: CursorSuperEmployeeMobileMessageBody,
            user: MobilePrincipal | None = Depends(get_user),
        ) -> object:
            """移动端管理员信息页的软件内 Cursor 调用入口（仅管理端）。"""
            return self._invoke(request, "cursor", body, user)

        self.mobile_admin_cursor_super_employee_invoke = mobile_admin_cursor_super_employee_invoke

        @router.get("/admin/trae-super-employee/messages", response_model=None)
        async def mobile_admin_trae_super_employee_messages(
            request: Request,
            limit: int = Query(default=80, ge=1, le=200),
            user: MobilePrincipal | None = Depends(get_user),
        ) -> object:
            """移动端管理员信息页的 Trae 超级员工对话记录（仅管理端）。"""
            return self._messages(request, "trae", limit, user)

        self.mobile_admin_trae_super_employee_messages = mobile_admin_trae_super_employee_messages

        @router.post("/admin/trae-super-employee/messages", response_model=None)
        async def mobile_admin_trae_super_employee_invoke(
            request: Request,
            body: TraeSuperEmployeeMobileMessageBody,
            user: MobilePrincipal | None = Depends(get_user),
        ) -> object:
            """移动端管理员信息页的软件内 Trae 调用入口（仅管理端）。"""
            return self._invoke(request, "trae", body, user)

        self.mobile_admin_trae_super_employee_invoke = mobile_admin_trae_super_employee_invoke

        @router.post("/admin/codex-super-employee/messages/stream", response_model=None)
        async def mobile_admin_codex_super_employee_stream(
            request: Request, body: dict[str, Any], user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            """移动端 Codex 超级员工 LAN SSE 流式直答。"""
            return await ports.stream_super_employee_invoke(request, "codex", body, user)

        self.mobile_admin_codex_super_employee_stream = mobile_admin_codex_super_employee_stream

        @router.post("/admin/claude-super-employee/messages/stream", response_model=None)
        async def mobile_admin_claude_super_employee_stream(
            request: Request, body: dict[str, Any], user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            """移动端 Claude 超级员工 LAN SSE 流式直答。"""
            return await ports.stream_super_employee_invoke(request, "claude", body, user)

        self.mobile_admin_claude_super_employee_stream = mobile_admin_claude_super_employee_stream

        @router.post("/admin/cursor-super-employee/messages/stream", response_model=None)
        async def mobile_admin_cursor_super_employee_stream(
            request: Request, body: dict[str, Any], user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            """移动端 Cursor 超级员工 LAN SSE 流式直答。"""
            return await ports.stream_super_employee_invoke(request, "cursor", body, user)

        self.mobile_admin_cursor_super_employee_stream = mobile_admin_cursor_super_employee_stream

        @router.post("/admin/trae-super-employee/messages/stream", response_model=None)
        async def mobile_admin_trae_super_employee_stream(
            request: Request, body: dict[str, Any], user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            """移动端 Trae 超级员工 LAN SSE 流式直答。"""
            return await ports.stream_super_employee_invoke(request, "trae", body, user)

        self.mobile_admin_trae_super_employee_stream = mobile_admin_trae_super_employee_stream

        def _super_employee_service_for_tool(tool: str) -> SuperEmployeePort | None:
            """根据工具名返回对应的 SuperEmployeeService 实例。"""
            tool_lower = (tool or "").strip().lower()
            if tool_lower == "codex":
                return ports.codex_super_employee_service()
            if tool_lower == "claude":
                return ports.claude_super_employee_service()
            if tool_lower == "cursor":
                return ports.cursor_super_employee_service()
            if tool_lower == "trae":
                return ports.trae_super_employee_service()
            return None

        self._super_employee_service_for_tool = _super_employee_service_for_tool

        async def _stream_super_employee_invoke(
            request: Request, tool: str, body: dict[str, Any], user: object
        ) -> Response:
            """超级员工 SSE 流式直答的共享实现。"""
            _, err = ports.require_mobile_admin(request, user)
            if err is not None:
                return err
            uid = ports.mobile_request_user_id(request, user)
            if uid <= 0:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401),
                    status_code=401,
                )
            service = _super_employee_service_for_tool(tool)
            if service is None:
                return JSONResponse(
                    format_mobile_response(
                        None, f"未知超级员工工具：{tool}", success=False, code=400
                    ),
                    status_code=400,
                )
            text = str((body or {}).get("message") or (body or {}).get("body") or "").strip()
            if not text:
                return JSONResponse(
                    format_mobile_response(None, "message 必填", success=False, code=400),
                    status_code=400,
                )
            context = dict((body or {}).get("context") or {})
            context.setdefault("source", "mobile_im")
            context.setdefault("client_surface", "mobile")
            context.setdefault("target_devices", ["all"])
            if (
                str((ports.mobile_session_meta(request) or {}).get("account_kind") or "")
                .strip()
                .lower()
                == "admin"
            ):
                _wsid = str(
                    (body or {}).get("workspace_id") or context.get("workspace_id") or "xcmax"
                )
                context = ports.factory_context(workspace_id=_wsid, base=context)

            async def sse_gen() -> AsyncIterator[bytes]:
                ready = asyncio.Event()
                reply: asyncio.Future[_StreamRead] = asyncio.get_running_loop().create_future()
                closing = False

                async def read_stream() -> None:
                    nonlocal closing
                    events: AsyncIterator[dict[str, Any]] | None = None
                    try:
                        # Factory, iteration and finalization share one task/context.
                        events = service.invoke_stream(user_id=uid, message=text, context=context)
                        iterator = aiter(events)
                        while True:
                            await ready.wait()
                            ready.clear()
                            try:
                                event = await anext(iterator)
                            except StopAsyncIteration:
                                reply.set_result((None, None))
                                return
                            reply.set_result((event, None))
                    except BaseException as exc:
                        # Transfer failures as values so a disconnected consumer cannot
                        # leave an unobserved Future exception. The owner awaits this task.
                        if not reply.done():
                            reply.set_result((None, exc))
                        raise
                    finally:
                        closing = True
                        if isinstance(events, ClosableEventStream):
                            await events.aclose()

                reader = asyncio.create_task(read_stream(), name="mobile-super-employee-events")
                try:
                    try:
                        while True:
                            # Exactly one read per consumer request; there is no prefetch.
                            ready.set()
                            event, error = await asyncio.shield(reply)
                            if error is not None:
                                raise error
                            if event is None:
                                break
                            yield ports.sse_line(event)
                            reply = asyncio.get_running_loop().create_future()
                    finally:
                        # Cancel a live reader once. Repeated AnyIO disconnect cancellation
                        # cannot interrupt its cleanup, and a finishing reader is awaited.
                        with CancelScope(shield=True):
                            if not closing:
                                reader.cancel()
                            with suppress(asyncio.CancelledError):
                                await reader
                except RECOVERABLE_ERRORS as exc:  # noqa: BLE001
                    logger.exception("mobile_super_employee_stream failed: %s", exc)
                    yield ports.sse_line({"type": "error", "message": "流式调用失败，请稍后重试"})

            return StreamingResponse(
                sse_gen(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        self._stream_super_employee_invoke = _stream_super_employee_invoke

    def _messages(
        self, request: Request, tool: str, limit: int, user: object
    ) -> dict[str, Any] | Response:
        _, error = self.ports.require_mobile_admin(request, user)
        if error is not None:
            return error
        uid = self.ports.mobile_request_user_id(request, user)
        if uid <= 0:
            return JSONResponse(
                format_mobile_response(None, "未授权", success=False, code=401), status_code=401
            )
        try:
            service = self._super_employee_service_for_tool(tool)
            if service is None:
                raise ValueError("unknown super employee tool")
            messages = service.list_messages(user_id=uid, limit=limit)
            return format_mobile_response(data={"messages": messages})
        except RECOVERABLE_ERRORS:
            logger.exception("mobile_admin_%s_super_employee_messages", tool)
            return JSONResponse(
                format_mobile_response(None, "超级员工服务暂不可用", success=False, code=500),
                status_code=500,
            )

    def _invoke(
        self,
        request: Request,
        tool: str,
        body: CodexSuperEmployeeMobileMessageBody
        | ClaudeSuperEmployeeMobileMessageBody
        | CursorSuperEmployeeMobileMessageBody
        | TraeSuperEmployeeMobileMessageBody,
        user: object,
    ) -> dict[str, Any] | Response:
        _, error = self.ports.require_mobile_admin(request, user)
        if error is not None:
            return error
        uid = self.ports.mobile_request_user_id(request, user)
        if uid <= 0:
            return JSONResponse(
                format_mobile_response(None, "未授权", success=False, code=401), status_code=401
            )
        text = (body.message or body.body or "").strip()
        if tool == "codex" and not text:
            return JSONResponse(
                format_mobile_response(None, "message 不能为空", success=False, code=400),
                status_code=400,
            )
        context = dict(body.context or {})
        context.setdefault("source", "mobile_im")
        context.setdefault("client_surface", "mobile")
        context.setdefault("target_devices", ["all"])
        if tool == "trae":
            context.setdefault("device_scope", "all_devices")
        # Cursor keeps its existing enterprise execution context. The other tools
        # receive factory scope only from the already-validated admin session.
        if (
            tool != "cursor"
            and str((self.ports.mobile_session_meta(request) or {}).get("account_kind") or "")
            .strip()
            .lower()
            == "admin"
        ):
            workspace_id = str(
                getattr(body, "workspace_id", "") or context.get("workspace_id") or "xcmax"
            )
            context = self.ports.factory_context(workspace_id=workspace_id, base=context)
        try:
            service = self._super_employee_service_for_tool(tool)
            if service is None:
                raise ValueError("unknown super employee tool")
            result = service.invoke(user_id=uid, message=text, context=context)
            return format_mobile_response(data=result)
        except ValueError:
            return JSONResponse(
                format_mobile_response(None, "超级员工请求无效", success=False, code=400),
                status_code=400,
            )
        except RECOVERABLE_ERRORS:
            logger.exception("mobile_admin_%s_super_employee_invoke", tool)
            return JSONResponse(
                format_mobile_response(None, "超级员工服务暂不可用", success=False, code=500),
                status_code=500,
            )
