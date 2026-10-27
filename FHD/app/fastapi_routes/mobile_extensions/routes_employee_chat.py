"""EmployeeChatRoutes: explicit collaborators for one mobile capability."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Body, Depends, Request
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
from app.utils.device_system.mobile_api import format_mobile_response
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


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
            if not result.get("success"):
                msg = ports.extract_employee_failure_text(result)
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
            conversation_id = str((body or {}).get("conversation_id") or "").strip()
            payload = {
                "trigger": "mobile_chat",
                "invoke_mode": "interactive_chat",
                "source": "mobile_app",
                "conversation_id": conversation_id,
                "client_surface": "mobile_app",
                "mod_id": str((body or {}).get("mod_id") or "").strip(),
                "employee_id": pid,
            }

            async def sse_gen():
                try:
                    yield ports.sse_line(
                        {"type": "token", "text": f"已连接员工 {pid}，正在思考..."}
                    )

                    result = await asyncio.to_thread(
                        ports.execute_employee,
                        pid,
                        message,
                        payload,
                        user_id=user_id,
                        workspace_root=None,
                        session_id=f"mobile_chat_{user_id}",
                    )
                    final_text = ports.extract_employee_reply_text(result)
                    if not final_text:
                        final_text = "（员工未返回内容）"
                    for chunk in ports.chunk_employee_reply(final_text):
                        yield ports.sse_line({"type": "token", "text": chunk})
                        await asyncio.sleep(0.05)
                    yield ports.sse_line({"type": "done", "result": {"response": final_text}})
                except RECOVERABLE_ERRORS as exc:
                    logger.exception("mobile_employee_chat_stream failed: %s", exc)
                    yield ports.sse_line({"type": "error", "message": "员工对话失败，请稍后重试"})

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
