"""EmployeeChatRoutes: explicit collaborators for one mobile capability."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.application.mobile_extensions.protocols import (
    ChunkEmployeeReplyCall,
    ExecuteEmployeeCall,
    ExtractEmployeeFailureTextCall,
    ExtractEmployeeReplyTextCall,
    MobilePrincipal,
    SseLineCall,
    UserDependency,
)
from app.domain.task_lifecycle.results import (
    execution_result_envelopes,
    execution_result_pending_state,
    execution_result_states,
)
from app.utils.device_system.mobile_api import format_mobile_response
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _employee_receipt(result: dict[str, Any]) -> dict[str, Any]:
    """Project existing result envelopes without treating delivery as task completion."""
    from app.application.agent_orchestrator.trace_payloads import _payload_status

    envelopes = list(execution_result_envelopes(result))
    state = execution_result_pending_state(result) or _payload_status(result)
    state = {"processing": "running", "pending": "queued", "accepted": "queued"}.get(state, state)
    if state == "completed" and not any(
        item.get("success") is True
        or item.get("ok") is True
        or "completed" in execution_result_states(item)
        for item in envelopes
    ):
        state = "unknown"
    receipt = {
        key: next(item[key] for item in envelopes if item.get(key) is not None)
        for key in (
            "run_id",
            "agent_run_id",
            "task_id",
            "plan_id",
            "approval_request_id",
            "pending_approval",
            "requires_token",
            "needs_user_input",
            "approval_card",
        )
        if any(item.get(key) is not None for item in envelopes)
    }
    return {
        **receipt,
        "success": state == "completed",
        "execution_state": state,
        "execution_accepted": state not in {"completed", "failed", "cancelled", "rejected"},
        **({"requires_reconciliation": True, "retryable": False} if state == "unknown" else {}),
    }


@dataclass(frozen=True)
class EmployeeChatRoutesPorts:
    extract_employee_failure_text: ExtractEmployeeFailureTextCall
    chunk_employee_reply: ChunkEmployeeReplyCall
    extract_employee_reply_text: ExtractEmployeeReplyTextCall
    sse_line: SseLineCall
    execute_employee: ExecuteEmployeeCall


class EmployeeChatRoutes:
    def __init__(self, ports: EmployeeChatRoutesPorts, get_user: UserDependency) -> None:
        self.ports = ports
        self.router = router = APIRouter()

        def _sse_line(payload: dict) -> bytes:
            """构造 SSE event line：data: {json}\\n\\n"""
            return ("data: " + json.dumps(payload, ensure_ascii=False) + "\n\n").encode("utf-8")

        self._sse_line = _sse_line

        def _chunk_employee_reply(text: str) -> list[str]:
            """把员工完整回复切成 SSE chunk（按句号/换行，每块 <= 120 字）。"""
            if not text:
                return []
            parts = re.split("(?<=[。！？!?\\n])", text)
            chunks: list[str] = []
            buf = ""
            for p in parts:
                p = p.strip()
                if not p:
                    continue
                if len(buf) + len(p) > 120:
                    if buf:
                        chunks.append(buf)
                    if len(p) > 120:
                        chunks.append(p)
                        buf = ""
                    else:
                        buf = p
                else:
                    buf += p
            if buf:
                chunks.append(buf)
            return chunks or [text]

        self._chunk_employee_reply = _chunk_employee_reply

        def _extract_employee_failure_text(result: dict) -> str:
            for key in ("message", "error"):
                value = result.get(key)
                if value:
                    return str(value)
            payload = result.get("result")
            if not isinstance(payload, dict):
                return ""
            for key in ("message", "error", "summary", "cognition_error"):
                value = payload.get(key)
                if value:
                    return str(value)
            outputs = payload.get("outputs")
            if isinstance(outputs, list):
                for out in outputs:
                    if not isinstance(out, dict):
                        continue
                    for key in ("error", "summary", "message", "text"):
                        value = out.get(key)
                        if value:
                            return str(value)
                    nested = out.get("output")
                    if isinstance(nested, dict):
                        for key in ("error", "summary", "message", "text"):
                            value = nested.get(key)
                            if value:
                                return str(value)
                    elif nested:
                        return str(nested)
            return ""

        self._extract_employee_failure_text = _extract_employee_failure_text

        def _extract_employee_reply_text(result: dict) -> str:
            """从 execute_employee_task_local 返回值里提取回复文本。

            返回结构（参考 executor.py 范式）：{success: bool, result: {outputs: [...]}}
            """
            if not isinstance(result, dict):
                return ""
            state = _employee_receipt(result)["execution_state"]
            if state != "completed":
                msg = ports.extract_employee_failure_text(result)
                if state not in {"failed", "cancelled", "rejected"}:
                    return msg or {
                        "unknown": "执行结果尚未确认，请核对原任务，勿重复提交。",
                        "waiting_approval": "原任务正在等待审批。",
                        "waiting_input": "原任务正在等待补充信息。",
                        "paused": "原任务已暂停。",
                        "blocked": "原任务已阻断，请核对任务状态。",
                    }.get(state, "原任务尚未完成，请继续查看任务回执。")
                return f"⚠️ 员工执行失败：{msg or '未知错误'}"
            r = result.get("result") or {}
            if not isinstance(r, dict):
                return str(r) if r else ""
            outputs = r.get("outputs") or []
            if isinstance(outputs, list):
                for out in outputs:
                    if not isinstance(out, dict):
                        continue
                    text = out.get("output") or out.get("summary") or out.get("text")
                    if text:
                        return str(text)
            for k in ("response", "output", "message", "text", "answer"):
                v = r.get(k)
                if v:
                    return str(v)
            return str(r) if r else ""

        self._extract_employee_reply_text = _extract_employee_reply_text

        @router.post("/employees/{employee_id}/chat/stream", response_model=None)
        async def mobile_employee_chat_stream(
            employee_id: str,
            request: Request,
            user: MobilePrincipal | None = Depends(get_user),
            body: dict[str, Any] = Body(default_factory=dict),
        ) -> object:
            """员工 chat 流式接口（手机端）。

            POST /api/mobile/v1/employees/{employee_id}/chat/stream
            body: {"message": "...", "conversation_id": "employee:modId:employeeId"}

            内部调 execute_employee_task_local 跑员工 agent loop，
            然后把完整结果按句号 chunk emit 成 SSE token 流（伪流式）。
            """
            # get_mobile_user deliberately returns None on an invalid/revoked
            # session; execution routes must reject that result before streaming.
            try:
                user_id = int(getattr(user, "id", 0) or 0)
            except (TypeError, ValueError):
                user_id = 0
            if user is None or user_id <= 0:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401),
                    status_code=401,
                )
            pid = str(employee_id or "").strip()
            if not pid:
                return JSONResponse(
                    format_mobile_response(None, "employee_id 必填", success=False, code=400),
                    status_code=400,
                )
            message = str((body or {}).get("message") or "").strip()
            if not message:
                return JSONResponse(
                    format_mobile_response(None, "message 必填", success=False, code=400),
                    status_code=400,
                )
            from app.fastapi_routes.domains.agent.route_support import request_runtime_context

            runtime_context = request_runtime_context(request)
            if str(runtime_context.get("user_id")) != str(user_id):
                raise HTTPException(status_code=403, detail="employee actor mismatch")
            conversation_id = str((body or {}).get("conversation_id") or "").strip()
            turn_id = (
                str(body.get("turn_id") or body.get("idempotency_key") or "").strip()
                or uuid.uuid4().hex
            )
            if len(turn_id) > 160 or (
                body.get("turn_id")
                and body.get("idempotency_key")
                and body["turn_id"] != body["idempotency_key"]
            ):
                raise HTTPException(
                    status_code=400, detail="turn_id 与 idempotency_key 必须一致且不超过160字符"
                )
            conversation_id = (
                conversation_id or f"employee:{runtime_context.get('mod_id') or 'host'}:{pid}"
            )
            runtime_context.update(
                local_user_id=user_id,
                conversation_id=conversation_id,
                session_id=conversation_id,
                turn_id=turn_id,
                idempotency_key=turn_id,
                source="mobile_app",
                invoke_mode="interactive_chat",
                client_surface="mobile_app",
            )
            payload = {
                "trigger": "mobile_chat",
                "invoke_mode": "interactive_chat",
                "source": "mobile_app",
                "conversation_id": conversation_id,
                "client_surface": "mobile_app",
                "mod_id": str((body or {}).get("mod_id") or "").strip(),
                "employee_id": pid,
                "turn_id": turn_id,
                "idempotency_key": turn_id,
            }

            def execute_turn() -> dict[str, Any]:
                from app.application.ai_chat.conversation_history import persist_chat_turn
                from app.application.ai_chat.dialogue_memory import (
                    prepare_chat_turn,
                    settle_chat_turn,
                )
                from app.domain.shared_services.conversation_service import (
                    ConversationRevisionError,
                )
                from app.infrastructure.tenant_scope import tenant_scope

                with tenant_scope(runtime_context.get("tenant_id")):
                    prepared = prepare_chat_turn(message, runtime_context)
                    if prepared is not None:
                        return {
                            **prepared,
                            **_employee_receipt(prepared),
                            "turn_id": turn_id,
                            "conversation_id": conversation_id,
                        }
                    try:
                        result = ports.execute_employee(
                            pid,
                            message,
                            payload,
                            user_id=user_id,
                            workspace_root=None,
                            session_id=conversation_id,
                            runtime_context=runtime_context,
                        )
                        result = result if isinstance(result, dict) else {}
                        receipt = _employee_receipt(result)
                        receipt["response"] = (
                            ports.extract_employee_reply_text(result) or "（员工未返回内容）"
                        )
                    except RECOVERABLE_ERRORS:
                        logger.exception("mobile employee execution interrupted")
                        receipt = {
                            "success": False,
                            "execution_state": "unknown",
                            "requires_reconciliation": True,
                            "retryable": False,
                            "response": "执行结果尚未确认，请查询原任务回执，勿重复提交。",
                        }
                    receipt.update(turn_id=turn_id, conversation_id=conversation_id)
                    try:
                        receipt["history_persistence"] = persist_chat_turn(
                            str(user_id), message, runtime_context, receipt
                        )
                    except ConversationRevisionError:
                        receipt["history_persistence"] = {"status": "invalidated", "retry": "none"}
                    except RECOVERABLE_ERRORS:
                        logger.exception("mobile employee history persistence failed")
                        receipt["history_persistence"] = {
                            "status": "failed",
                            "retry": "save_only",
                            "turn_id": turn_id,
                            "conversation_id": conversation_id,
                            "revision": runtime_context.get("_conversation_revision"),
                        }
                    try:
                        settle_chat_turn(
                            message, runtime_context, receipt, receipt["execution_state"]
                        )
                    except RECOVERABLE_ERRORS:
                        logger.exception("mobile employee receipt persistence failed")
                    return receipt

            async def sse_gen():
                try:
                    yield ports.sse_line(
                        {"type": "token", "text": f"已连接员工 {pid}，正在思考..."}
                    )

                    result = await asyncio.to_thread(execute_turn)
                    final_text = str(result.get("response") or result.get("message") or "")
                    for chunk in ports.chunk_employee_reply(final_text):
                        yield ports.sse_line({"type": "token", "text": chunk})
                        await asyncio.sleep(0.05)
                    yield ports.sse_line({"type": "done", "result": result})
                except RECOVERABLE_ERRORS as exc:
                    logger.exception("mobile_employee_chat_stream failed: %s", exc)
                    yield ports.sse_line(
                        {
                            "type": "error",
                            "message": "员工对话暂不可用，请查询原轮回执。",
                            "turn_id": turn_id,
                            "conversation_id": conversation_id,
                        }
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

        self.mobile_employee_chat_stream = mobile_employee_chat_stream
