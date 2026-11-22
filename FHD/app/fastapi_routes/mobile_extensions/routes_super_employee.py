"""SuperEmployeeRoutes: explicit collaborators for one mobile capability."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import AsyncIterator
from contextlib import nullcontext, suppress
from dataclasses import dataclass
from typing import Any

from anyio import CancelScope
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from app.application.mobile_extensions.protocols import (
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
from app.fastapi_routes.mobile_extensions.models import (
    ClaudeSuperEmployeeMobileMessageBody,
    CodexSuperEmployeeMobileMessageBody,
    CursorSuperEmployeeMobileMessageBody,
    TraeSuperEmployeeMobileMessageBody,
)
from app.utils.device_system.mobile_api import format_mobile_response
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
_StreamRead = tuple[dict[str, Any] | None, BaseException | None]
_STREAM_FAILURES: tuple[type[BaseException], ...] = (Exception, asyncio.CancelledError)


def _turn_context(
    request: Request, context: dict[str, Any], uid: int, tool: str, mode: str
) -> dict[str, Any] | None:
    """Bind modern mobile intents to the existing authenticated conversation turn."""
    turn_id = str(context.get("turn_id") or context.get("idempotency_key") or "").strip()
    if not turn_id:
        return None
    from app.fastapi_routes.domains.agent.route_support import request_runtime_context

    conversation = str(context.get("conversation_id") or "").strip()
    if (
        not conversation
        or len(turn_id) > 160
        or (
            context.get("turn_id")
            and context.get("idempotency_key")
            and context["turn_id"] != context["idempotency_key"]
        )
    ):
        raise HTTPException(status_code=400, detail="原会话及一致的 turn_id/idempotency_key 必填")
    trusted = request_runtime_context(request)
    if str(trusted.get("user_id")) != str(uid):
        raise HTTPException(status_code=403, detail="super employee actor mismatch")
    trusted.update(
        local_user_id=uid,
        conversation_id=conversation,
        session_id=conversation,
        turn_id=turn_id,
        idempotency_key=turn_id,
    )
    from app.application.ai_chat.conversation_history import _SECRET_FIELD
    from app.domain.app_pure.execution_scope import CapabilityGrant

    def safe(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: safe(child)
                for key, child in value.items()
                if not _SECRET_FIELD.search(str(key))
                and key
                not in {
                    "_execution_identity",
                    "turn_id",
                    "idempotency_key",
                    "session_id",
                    "conversation_id",
                    "workspace_root",
                    "_actor_authorization",
                    "_mod_authorization",
                    "user_id",
                    "actor_id",
                    "local_user_id",
                    "tenant_id",
                }
            }
        if isinstance(value, list):
            return [safe(child) for child in value]
        return value

    grant = CapabilityGrant.resolve(context)
    identity = [tool, mode, grant.scope.value, grant.workspace_id, safe({**context, **trusted})]
    trusted["_execution_identity"] = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    trusted["execution_tool"] = tool
    return trusted


def _turn_receipt(result: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    from app.fastapi_routes.mobile_extensions.routes_employee_chat import _employee_receipt

    dispatch = result.get("dispatch")
    dispatch = dispatch if isinstance(dispatch, dict) else {}
    assistant = result.get("assistant_message")
    assistant = assistant if isinstance(assistant, dict) else {}
    reply = result.get("response") or assistant.get("body") or ""
    projection: dict[str, Any] = {"result": result, "data": dispatch}
    # A completed local text reply has no AgentRun. Dispatch acknowledgements do.
    if (
        reply
        and not dispatch
        and not any(
            result.get(k)
            for k in (
                "run_id",
                "agent_run_id",
                "task_id",
                "execution_state",
                "agent_status",
                "status",
            )
        )
    ):
        projection["execution_state"] = "completed"
    return {
        **result,
        **_employee_receipt(projection),
        "response": reply,
        "turn_id": context["turn_id"],
        "conversation_id": context["conversation_id"],
        "execution_tool": context["execution_tool"],
        "execution_identity": context["_execution_identity"],
    }


def _settle_turn(message: str, context: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    from app.application.ai_chat.conversation_history import persist_chat_turn
    from app.application.ai_chat.dialogue_memory import settle_chat_turn
    from app.infrastructure.tenant_scope import tenant_scope

    receipt = _turn_receipt(result, context)
    with tenant_scope(context.get("tenant_id")):
        try:
            receipt["history_persistence"] = persist_chat_turn(
                str(context["local_user_id"]), message, context, receipt
            )
        except RECOVERABLE_ERRORS:
            logger.exception("super employee history persistence failed")
            receipt["history_persistence"] = {"status": "failed", "retry": "save_only"}
        settle_chat_turn(message, context, receipt, receipt["execution_state"])
    return receipt


def _unknown_turn() -> dict[str, Any]:
    return {
        "execution_state": "unknown",
        "requires_reconciliation": True,
        "retryable": False,
        "response": "原任务结果尚待核对，请读取原任务回执，勿重复提交。",
    }


def _turn_conflict(turn: dict[str, Any]) -> JSONResponse:
    return JSONResponse(
        {
            "success": False,
            "error_code": "CHAT_RECEIPT_PENDING",
            "execution_state": "blocked",
            "turn_id": turn["turn_id"],
            "message": "这个编号已属于另一执行意图，请核对原任务，未覆盖或重新派发。",
        },
        status_code=409,
    )


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
        self._turn_workers: set[asyncio.Task] = set()

        @router.get("/admin/codex-super-employee/messages", response_model=None)
        async def mobile_admin_codex_super_employee_messages(
            request: Request,
            limit: int = Query(default=80, ge=1, le=200),
            user: MobilePrincipal | None = Depends(get_user),
            conversation_id: str = "",
            turn_id: str = "",
        ) -> object:
            """移动端管理员信息页的 Codex 超级员工对话记录（仅管理端）。"""
            return self._messages(request, "codex", limit, user, conversation_id, turn_id)

        self.mobile_admin_codex_super_employee_messages = mobile_admin_codex_super_employee_messages

        @router.post("/admin/codex-super-employee/messages", response_model=None)
        async def mobile_admin_codex_super_employee_invoke(
            request: Request,
            body: CodexSuperEmployeeMobileMessageBody,
            user: MobilePrincipal | None = Depends(get_user),
        ) -> object:
            """移动端管理员信息页的软件内 Codex 调用入口（仅管理端）。"""
            return await self._invoke(request, "codex", body, user)

        self.mobile_admin_codex_super_employee_invoke = mobile_admin_codex_super_employee_invoke

        @router.get("/admin/claude-super-employee/messages", response_model=None)
        async def mobile_admin_claude_super_employee_messages(
            request: Request,
            limit: int = Query(default=80, ge=1, le=200),
            user: MobilePrincipal | None = Depends(get_user),
            conversation_id: str = "",
            turn_id: str = "",
        ) -> object:
            """移动端管理员信息页的 Claude 超级员工对话记录（仅管理端）。"""
            return self._messages(request, "claude", limit, user, conversation_id, turn_id)

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
            return await self._invoke(request, "claude", body, user)

        self.mobile_admin_claude_super_employee_invoke = mobile_admin_claude_super_employee_invoke

        @router.get("/admin/cursor-super-employee/messages", response_model=None)
        async def mobile_admin_cursor_super_employee_messages(
            request: Request,
            limit: int = Query(default=80, ge=1, le=200),
            user: MobilePrincipal | None = Depends(get_user),
            conversation_id: str = "",
            turn_id: str = "",
        ) -> object:
            """移动端管理员信息页的 Cursor 超级员工对话记录（仅管理端）。"""
            return self._messages(request, "cursor", limit, user, conversation_id, turn_id)

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
            return await self._invoke(request, "cursor", body, user)

        self.mobile_admin_cursor_super_employee_invoke = mobile_admin_cursor_super_employee_invoke

        @router.get("/admin/trae-super-employee/messages", response_model=None)
        async def mobile_admin_trae_super_employee_messages(
            request: Request,
            limit: int = Query(default=80, ge=1, le=200),
            user: MobilePrincipal | None = Depends(get_user),
            conversation_id: str = "",
            turn_id: str = "",
        ) -> object:
            """移动端管理员信息页的 Trae 超级员工对话记录（仅管理端）。"""
            return self._messages(request, "trae", limit, user, conversation_id, turn_id)

        self.mobile_admin_trae_super_employee_messages = mobile_admin_trae_super_employee_messages

        @router.post("/admin/trae-super-employee/messages", response_model=None)
        async def mobile_admin_trae_super_employee_invoke(
            request: Request,
            body: TraeSuperEmployeeMobileMessageBody,
            user: MobilePrincipal | None = Depends(get_user),
        ) -> object:
            """移动端管理员信息页的软件内 Trae 调用入口（仅管理端）。"""
            return await self._invoke(request, "trae", body, user)

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

            turn = _turn_context(request, context, uid, tool, "stream")
            if turn is not None:
                from app.application.ai_chat.dialogue_memory import prepare_chat_turn
                from app.infrastructure.tenant_scope import tenant_scope

                context.update(turn)
                with tenant_scope(turn.get("tenant_id")):
                    prepared = prepare_chat_turn(text, turn)
                if prepared is not None:
                    if prepared.get("error_code") == "TURN_INPUT_CONFLICT":
                        return _turn_conflict(turn)

                    async def replay() -> AsyncIterator[bytes]:
                        yield ports.sse_line(
                            {"type": "done", "result": _turn_receipt(prepared, turn)}
                        )

                    return StreamingResponse(replay(), media_type="text/event-stream")

            ready = asyncio.Event()
            reply: asyncio.Future[_StreamRead] = asyncio.get_running_loop().create_future()
            queue: asyncio.Queue[_StreamRead] | None = (
                asyncio.Queue(maxsize=32) if turn is not None else None
            )
            attached = False
            detached = False
            closing = False

            async def publish(value: _StreamRead) -> None:
                if queue is None:
                    if not reply.done():
                        reply.set_result(value)
                elif not detached:
                    # Admission owns execution even before HTTP starts iterating.
                    # Bound pre-delivery tokens; the final event contains the complete reply.
                    if not attached and queue.full():
                        queue.get_nowait()
                    await queue.put(value)

            async def read_stream() -> None:
                nonlocal closing
                events: AsyncIterator[dict[str, Any]] | None = None
                settled = False
                try:
                    # Factory, iteration and finalization share one task/context.
                    events = service.invoke_stream(user_id=uid, message=text, context=context)
                    iterator = aiter(events)
                    while True:
                        if queue is None:
                            await ready.wait()
                            ready.clear()
                        try:
                            event = await anext(iterator)
                        except StopAsyncIteration:
                            return
                        if turn is not None and event.get("type") == "done":
                            result = event.get("result")
                            event = {
                                **event,
                                "result": _settle_turn(
                                    text,
                                    turn,
                                    result if isinstance(result, dict) else _unknown_turn(),
                                ),
                            }
                            settled = True
                        await publish((event, None))
                except _STREAM_FAILURES as exc:
                    await publish((None, exc))
                    raise
                finally:
                    closing = True
                    with CancelScope(shield=True):
                        try:
                            try:
                                if isinstance(events, ClosableEventStream):
                                    await events.aclose()
                            finally:
                                if turn is not None and not settled:
                                    _settle_turn(text, turn, _unknown_turn())
                        finally:
                            await publish((None, None))

            async def read_owned_stream() -> None:
                from app.infrastructure.tenant_scope import tenant_scope

                with tenant_scope(turn.get("tenant_id")) if turn is not None else nullcontext():
                    await read_stream()

            reader: asyncio.Task | None = None
            if turn is not None:
                reader = asyncio.create_task(read_owned_stream(), name="mobile-super-employee-turn")
                self._turn_workers.add(reader)
                reader.add_done_callback(self._reap_turn_worker)

            async def sse_gen() -> AsyncIterator[bytes]:
                nonlocal reader, reply, attached, detached
                attached = True
                if reader is None:
                    reader = asyncio.create_task(
                        read_owned_stream(), name="mobile-super-employee-events"
                    )
                try:
                    try:
                        while True:
                            if queue is None:
                                ready.set()
                                event, error = await asyncio.shield(reply)
                            else:
                                event, error = await queue.get()
                            if error is not None:
                                raise error
                            if event is None:
                                break
                            yield ports.sse_line(event)
                            if queue is None:
                                reply = asyncio.get_running_loop().create_future()
                    finally:
                        with CancelScope(shield=True):
                            if queue is not None:
                                detached = True
                                # Release a producer blocked on a slow/disconnected consumer.
                                while not queue.empty():
                                    queue.get_nowait()
                            elif not closing:
                                reader.cancel()
                            if turn is None or reader.done():
                                with suppress(asyncio.CancelledError):
                                    await reader
                except RECOVERABLE_ERRORS as exc:
                    logger.exception("mobile_super_employee_stream failed: %s", exc)
                    yield ports.sse_line(
                        {"type": "error", "message": "原任务回执待核对，请读取原任务。"}
                    )

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
        self,
        request: Request,
        tool: str,
        limit: int,
        user: object,
        conversation_id: str = "",
        turn_id: str = "",
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
            if turn_id or conversation_id:
                from app.application.ai_chat.dialogue_memory import stored_turn_receipt
                from app.application.task_conversation_store import task_conversation_store
                from app.infrastructure.tenant_scope import tenant_scope

                turn = _turn_context(
                    request,
                    {"turn_id": turn_id, "conversation_id": conversation_id},
                    uid,
                    tool,
                    "read",
                )
                if turn is None:
                    raise HTTPException(status_code=400, detail="turn_id 必填")
                with tenant_scope(turn.get("tenant_id")):
                    stored = stored_turn_receipt(turn, turn_id)
                    history = task_conversation_store.get_history(
                        session_id=conversation_id,
                        user_id=uid,
                        mod_id=str(turn.get("mod_id") or ""),
                        turn_id=turn_id,
                    )
                view = (
                    history.get("turn_receipt")
                    or history.get("active_turn")
                    or {
                        "turn_id": turn_id,
                        "run_id": "",
                        "receipt_kind": "turn",
                        "durable": True,
                        "status": "unknown",
                        "requires_reconciliation": True,
                        "message": _unknown_turn()["response"],
                    }
                )
                if stored is not None:
                    payload = stored["payload"]
                    if not payload.get("execution_tool"):
                        return format_mobile_response(
                            data={
                                "turn_receipt": {
                                    **view,
                                    "status": "unknown",
                                    "requires_reconciliation": True,
                                    "message": _unknown_turn()["response"],
                                }
                            }
                        )
                    if payload.get("execution_tool") != tool:
                        raise HTTPException(status_code=409, detail="原任务属于另一执行工具")
                    dispatch = payload.get("dispatch")
                    if isinstance(dispatch, dict) and view["status"] not in {
                        "completed",
                        "failed",
                        "cancelled",
                        "rejected",
                    }:
                        refreshed = service.read_dispatch_receipt(
                            user_id=uid,
                            request_id=str(dispatch.get("request_id") or ""),
                            task_id=str(dispatch.get("task_id") or ""),
                        )
                        receipt = _turn_receipt(refreshed or _unknown_turn(), turn)
                        view = {
                            **view,
                            "status": receipt["execution_state"],
                            "message": receipt["response"],
                            "task_id": receipt.get("task_id") or payload.get("task_id") or "",
                            "requires_reconciliation": receipt["execution_state"] == "unknown",
                        }
                return format_mobile_response(data={"turn_receipt": view})
            messages = service.list_messages(user_id=uid, limit=limit)
            return format_mobile_response(data={"messages": messages})
        except RECOVERABLE_ERRORS:
            logger.exception("mobile_admin_%s_super_employee_messages", tool)
            return JSONResponse(
                format_mobile_response(None, "超级员工服务暂不可用", success=False, code=500),
                status_code=500,
            )

    def _reap_turn_worker(self, task: asyncio.Task) -> None:
        self._turn_workers.discard(task)
        if not task.cancelled():
            task.exception()  # Observed after an HTTP disconnect as well as normal delivery.

    async def _invoke(
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
        turn = _turn_context(request, context, uid, tool, "invoke")
        try:
            service = self._super_employee_service_for_tool(tool)
            if service is None:
                raise ValueError("unknown super employee tool")

            def execute() -> dict[str, Any]:
                from app.application.ai_chat.dialogue_memory import prepare_chat_turn
                from app.infrastructure.tenant_scope import tenant_scope

                with tenant_scope(turn.get("tenant_id")) if turn is not None else nullcontext():
                    if turn is not None:
                        context.update(turn)
                        prepared = prepare_chat_turn(text, turn)
                        if prepared is not None:
                            return _turn_receipt(prepared, turn)
                    try:
                        result = service.invoke(user_id=uid, message=text, context=context)
                    except RECOVERABLE_ERRORS:
                        if turn is None:
                            raise
                        logger.exception("super employee invocation interrupted")
                        result = _unknown_turn()
                    return _settle_turn(text, turn, result) if turn is not None else result

            result = await asyncio.to_thread(execute) if turn is not None else execute()
            if turn is not None and result.get("error_code") == "TURN_INPUT_CONFLICT":
                return _turn_conflict(turn)
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
