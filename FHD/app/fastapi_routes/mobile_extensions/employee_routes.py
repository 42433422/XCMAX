"""Mobile employee autonomy + chat SSE routes (split from mobile_api_extensions).

Included into ``extension_router``; handlers and helpers are re-exported from
``mobile_api_extensions`` for tests and patch compatibility.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.fastapi_routes.mobile_api import get_mobile_user
from app.fastapi_routes.mobile_extensions.admin_helpers import (
    _compact_text,
    _require_mobile_admin,
)
from app.utils.mobile_api import format_mobile_response

logger = logging.getLogger(__name__)

employee_router = APIRouter()

# ──────────────────────────────────────────────────────────────────────
# 员工任务中心：手机端拉员工 Phase-D 主动提问 + 老板回答
# 通过 httpx 代理调 MODstore 后端 admin_employee_autonomy_api：
#   GET  /api/admin/employee-autonomy/questions
#   POST /api/admin/employee-autonomy/questions/{id}/answer
# 认证：MODSTORE_AUTH_TOKEN 环境变量（与 ModstoreAdapter 一致）
# ──────────────────────────────────────────────────────────────────────


def _modstore_platform_base() -> str:
    """获取 MODstore 后端 base url（如 http://127.0.0.1:8765）。"""
    return os.environ.get("MODSTORE_PLATFORM_URL", "http://localhost:8000").rstrip("/")


def _modstore_admin_token() -> str:
    """获取调 MODstore admin API 用的 Bearer token。"""
    return os.environ.get("MODSTORE_AUTH_TOKEN", "").strip()


async def _modstore_admin_proxy(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """通用代理：调 MODstore 后端 admin API。

    返回 {"ok": bool, "status": int, "data": ..., "error": str}。
    """
    import httpx

    url = f"{_modstore_platform_base()}{path}"
    headers = {"Accept": "application/json"}
    token = _modstore_admin_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.request(method, url, params=params, json=json_body, headers=headers)
        try:
            data = resp.json()
        except Exception:  # noqa: BLE001
            data = {"raw": resp.text[:500]}
        if resp.is_success:
            return {"ok": True, "status": resp.status_code, "data": data}
        return {
            "ok": False,
            "status": resp.status_code,
            "error": str(data.get("detail") or data.get("error") or resp.text[:200])[:300],
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status": 0,
            "error": f"无法连接 MODstore 后端：{_compact_text(exc)[:200]}",
        }


@employee_router.get("/admin/employee-pending-questions")
async def mobile_admin_employee_pending_questions(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    include_history: bool = Query(default=False),
    employee_id: str | None = Query(default=None),
    user=Depends(get_mobile_user),
):
    """拉员工 Phase-D 主动提问列表（pending 优先）。

    GET /api/mobile/v1/admin/employee-pending-questions
      ?limit=50&include_history=false&employee_id=llm-ops-engineer

    返回 {"items": [...], "count": N, "market_connected": bool}
    每个 item 含：id / employee_id / task / question / status / asked_at / answer / answered_at
    """
    meta, err = _require_mobile_admin(request, user)
    if err is not None:
        return err

    params: dict[str, Any] = {"limit": limit, "include_expired": bool(include_history)}
    if employee_id:
        params["employee_id"] = employee_id

    out = await _modstore_admin_proxy(
        "GET",
        "/api/admin/employee-autonomy/questions",
        params=params,
    )
    if not out.get("ok"):
        return format_mobile_response(
            None,
            f"拉员工提问失败：{out.get('error') or '未知错误'}",
            success=False,
            code=out.get("status") or 502,
        )
    data = out.get("data") if isinstance(out.get("data"), dict) else {}
    items = data.get("items") if isinstance(data.get("items"), list) else []
    return format_mobile_response(
        data={
            "items": items,
            "count": int(data.get("count") or len(items)),
            "market_connected": bool(out.get("ok")),
        }
    )


@employee_router.post("/admin/employee-pending-questions/{question_id}/answer")
async def mobile_admin_employee_pending_question_answer(
    question_id: int,
    body: dict[str, Any],
    request: Request,
    user=Depends(get_mobile_user),
):
    """老板回答员工的 Phase-D 提问。

    POST /api/mobile/v1/admin/employee-pending-questions/{id}/answer
    body: {"answer": "先做 A，因为..."}

    成功后员工执行管道被阻塞的 ask_human_blocking() 会拿到答案继续执行。
    """
    meta, err = _require_mobile_admin(request, user)
    if err is not None:
        return err

    answer_text = str((body or {}).get("answer") or "").strip()
    if not answer_text:
        return format_mobile_response(None, "answer 字段不能为空", success=False, code=400)

    out = await _modstore_admin_proxy(
        "POST",
        f"/api/admin/employee-autonomy/questions/{int(question_id)}/answer",
        json_body={"answer": answer_text},
    )
    if not out.get("ok"):
        return format_mobile_response(
            None,
            f"回答失败：{out.get('error') or '未知错误'}",
            success=False,
            code=out.get("status") or 502,
        )
    data = out.get("data") if isinstance(out.get("data"), dict) else {}
    return format_mobile_response(data=data)


# ──────────────────────────────────────────────────────────────────────
# 员工 chat（手机端流式）：让老板在 app 里直接和员工对话
# ──────────────────────────────────────────────────────────────────────


def _sse_line(payload: dict) -> bytes:
    """构造 SSE event line：data: {json}\\n\\n"""
    return ("data: " + json.dumps(payload, ensure_ascii=False) + "\n\n").encode("utf-8")


def _chunk_employee_reply(text: str) -> list[str]:
    """把员工完整回复切成 SSE chunk（按句号/换行，每块 <= 120 字）。"""
    if not text:
        return []
    parts = re.split(r"(?<=[。！？!?\n])", text)
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


def _extract_employee_reply_text(result: dict) -> str:
    """从 execute_employee_task_local 返回值里提取回复文本。

    返回结构（参考 executor.py 范式）：{success: bool, result: {outputs: [...]}}
    """
    if not isinstance(result, dict):
        return ""
    if not result.get("success"):
        msg = _extract_employee_failure_text(result)
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


@employee_router.post("/employees/{employee_id}/chat/stream")
async def mobile_employee_chat_stream(
    employee_id: str,
    request: Request,
    user=Depends(get_mobile_user),
    body: dict[str, Any] = Body(default_factory=dict),
):
    """员工 chat 流式接口（手机端）。

    POST /api/mobile/v1/employees/{employee_id}/chat/stream
    body: {"message": "...", "conversation_id": "employee:modId:employeeId"}

    内部调 execute_employee_task_local 跑员工 agent loop，
    然后把完整结果按句号 chunk emit 成 SSE token 流（伪流式）。
    """
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

    user_id = 0
    try:
        user_id = int(getattr(user, "id", 0) or 0)
    except (TypeError, ValueError):
        user_id = 0

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
            yield _sse_line({"type": "token", "text": f"已连接员工 {pid}，正在思考..."})
            from app.application.employee_runtime.executor import execute_employee_task_local

            result = await asyncio.to_thread(
                execute_employee_task_local,
                pid,
                message,
                payload,
                user_id=user_id,
                workspace_root=None,
                session_id=f"mobile_chat_{user_id}",
            )
            final_text = _extract_employee_reply_text(result)
            if not final_text:
                final_text = "（员工未返回内容）"
            for chunk in _chunk_employee_reply(final_text):
                yield _sse_line({"type": "token", "text": chunk})
                await asyncio.sleep(0.05)
            yield _sse_line({"type": "done", "result": {"response": final_text}})
        except Exception as exc:
            logger.exception("mobile_employee_chat_stream failed: %s", exc)
            # 不向客户端回传异常原文，避免堆栈/路径信息外泄（CodeQL）
            yield _sse_line({"type": "error", "message": "员工对话失败，请稍后重试"})

    return StreamingResponse(
        sse_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
