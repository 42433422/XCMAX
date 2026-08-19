# ruff: noqa
# mypy: ignore-errors
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.fastapi_routes.mobile_api_extensions')

def _extract_employee_reply_text(result: dict) -> str:
    """从 execute_employee_task_local 返回值里提取回复文本。

    返回结构（参考 executor.py 范式）：{success: bool, result: {outputs: [...]}}
    """
    if not isinstance(result, dict):
        return ''
    if not result.get('success'):
        msg = _facade()._extract_employee_failure_text(result)
        return f"⚠️ 员工执行失败：{msg or '未知错误'}"
    r = result.get('result') or {}
    if not isinstance(r, dict):
        return str(r) if r else ''
    outputs = r.get('outputs') or []
    if isinstance(outputs, list):
        for out in outputs:
            if not isinstance(out, dict):
                continue
            text = out.get('output') or out.get('summary') or out.get('text')
            if text:
                return str(text)
    for k in ('response', 'output', 'message', 'text', 'answer'):
        v = r.get(k)
        if v:
            return str(v)
    return str(r) if r else ''

def _extract_employee_failure_text(result: dict) -> str:
    for key in ('message', 'error'):
        value = result.get(key)
        if value:
            return str(value)
    payload = result.get('result')
    if not isinstance(payload, dict):
        return ''
    for key in ('message', 'error', 'summary', 'cognition_error'):
        value = payload.get(key)
        if value:
            return str(value)
    outputs = payload.get('outputs')
    if isinstance(outputs, list):
        for out in outputs:
            if not isinstance(out, dict):
                continue
            for key in ('error', 'summary', 'message', 'text'):
                value = out.get(key)
                if value:
                    return str(value)
            nested = out.get('output')
            if isinstance(nested, dict):
                for key in ('error', 'summary', 'message', 'text'):
                    value = nested.get(key)
                    if value:
                        return str(value)
            elif nested:
                return str(nested)
    return ''

@_facade().extension_router.post('/employees/{employee_id}/chat/stream')
async def mobile_employee_chat_stream(employee_id: str, request: _facade().Request, user=_facade().Depends(_facade().get_mobile_user), body: dict[str, _facade().Any]=_facade().Body(default_factory=dict)):
    """员工 chat 流式接口（手机端）。

    POST /api/mobile/v1/employees/{employee_id}/chat/stream
    body: {"message": "...", "conversation_id": "employee:modId:employeeId"}

    内部调 execute_employee_task_local 跑员工 agent loop，
    然后把完整结果按句号 chunk emit 成 SSE token 流（伪流式）。
    """
    pid = str(employee_id or '').strip()
    if not pid:
        return _facade().JSONResponse(_facade().format_mobile_response(None, 'employee_id 必填', success=False, code=400), status_code=400)
    message = str((body or {}).get('message') or '').strip()
    if not message:
        return _facade().JSONResponse(_facade().format_mobile_response(None, 'message 必填', success=False, code=400), status_code=400)
    user_id = 0
    try:
        user_id = int(getattr(user, 'id', 0) or 0)
    except (TypeError, ValueError):
        user_id = 0
    conversation_id = str((body or {}).get('conversation_id') or '').strip()
    payload = {'trigger': 'mobile_chat', 'invoke_mode': 'interactive_chat', 'source': 'mobile_app', 'conversation_id': conversation_id, 'client_surface': 'mobile_app', 'mod_id': str((body or {}).get('mod_id') or '').strip(), 'employee_id': pid}

    async def sse_gen():
        try:
            yield _facade()._sse_line({'type': 'token', 'text': f'已连接员工 {pid}，正在思考...'})
            from app.application.employee_runtime.executor import execute_employee_task_local
            result = await _facade().asyncio.to_thread(execute_employee_task_local, pid, message, payload, user_id=user_id, workspace_root=None, session_id=f'mobile_chat_{user_id}')
            final_text = _facade()._extract_employee_reply_text(result)
            if not final_text:
                final_text = '（员工未返回内容）'
            for chunk in _facade()._chunk_employee_reply(final_text):
                yield _facade()._sse_line({'type': 'token', 'text': chunk})
                await _facade().asyncio.sleep(0.05)
            yield _facade()._sse_line({'type': 'done', 'result': {'response': final_text}})
        except _facade().RECOVERABLE_ERRORS as exc:
            _facade().logger.exception('mobile_employee_chat_stream failed: %s', exc)
            yield _facade()._sse_line({'type': 'error', 'message': '员工对话失败，请稍后重试'})
    return _facade().StreamingResponse(sse_gen(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache', 'Connection': 'keep-alive', 'X-Accel-Buffering': 'no'})
