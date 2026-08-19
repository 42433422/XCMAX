# mypy: disable-error-code=no-any-return
# ruff: noqa
"""JSON and batch execution paths for planner compatibility chat."""
from __future__ import annotations
import importlib
from contextvars import ContextVar, Token
from typing import TYPE_CHECKING, Any
from fastapi import HTTPException, Request
if TYPE_CHECKING:
    from app.fastapi_routes.xcagi_compat_chat_helpers import XcagiCompatChatBatchBody, XcagiCompatChatBody
_FACADE_GLOBALS: ContextVar[dict[str, Any] | None] = ContextVar('planner_compat_facade_globals', default=None)

class _GlobalsFacade:

    def __init__(self, values: dict[str, Any]) -> None:
        self._values = values

    def __getattr__(self, name: str) -> Any:
        return self._values[name]

def set_facade_globals(values: dict[str, Any]) -> Token[dict[str, Any] | None]:
    return _FACADE_GLOBALS.set(values)

def reset_facade_globals(token: Token[dict[str, Any] | None]) -> None:
    _FACADE_GLOBALS.reset(token)

def _facade():
    values = _FACADE_GLOBALS.get()
    if values is not None:
        return _GlobalsFacade(values)
    return importlib.import_module('app.application.planner_compat_service')

async def execute_compat_chat(request: Request, body: XcagiCompatChatBody) -> dict[str, Any]:
    m = (body.mode or '').strip().lower()
    if m in ('online', 'offline'):
        _facade().set_llm_mode(m)
    (runtime_context, _) = _facade()._merge_runtime_context_with_message_paths(body.context, body.message)
    runtime_context = _facade()._runtime_context_with_authenticated_actor(request, runtime_context)
    _facade().assert_p2_elevated_claim_or_raise(request)
    tier = _facade().resolve_ai_tier(request)
    runtime_context = _facade().runtime_context_with_tier(runtime_context, tier)
    from app.application.chat_business_safety import try_handle_business_chat_action
    business_payload = try_handle_business_chat_action(body.message, runtime_context=runtime_context, user_id=getattr(body, 'user_id', None), request=request)
    if business_payload is not None:
        return business_payload
    try:
        from app.application.kitten_planner_context import enrich_kitten_analyzer_runtime, kitten_reply_attachments
        runtime_context = await enrich_kitten_analyzer_runtime(runtime_context, body.message)
        kitten_extra = kitten_reply_attachments(runtime_context)
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.debug('kitten planner context enrich skipped', exc_info=True)
        kitten_extra = {}
    from app.application.normal_chat_dispatch import try_normal_slot_read_payload
    slot_payload = try_normal_slot_read_payload(body.message, request=request)
    if isinstance(slot_payload, dict) and slot_payload.get('response'):
        return _facade()._attach_compat_chat_trace(slot_payload, body, message=body.message, runtime_context=runtime_context, channel='compat_chat_agent_tool' if slot_payload.get('agent_tool_dispatch') else 'compat_chat_slot')
    (ok_read, read_req) = _facade()._ensure_chat_db_read_authorized(request, message=body.message, provided_token=body.db_read_token)
    if not ok_read and read_req:
        payload = {'success': True, 'requires_token': True, 'token_name': read_req.get('token_name'), 'token_description': read_req.get('token_description'), 'message': read_req.get('message'), 'response': read_req.get('message'), 'data': {'requires_token': True, 'token_name': read_req.get('token_name'), 'token_description': read_req.get('token_description')}}
        return _facade()._attach_compat_chat_trace(payload, body, message=body.message, runtime_context=runtime_context, channel='compat_chat')
    if ok_read and _facade()._message_requires_db_read_token(body.message):
        runtime_context['chat_db_read_authorized'] = True
    intr = _facade().planner_workflow_interrupt_reply(body.message)
    if intr is not None:
        cleared = _facade().runtime_context_after_workflow_interrupt(runtime_context)
        payload = _facade()._xcagi_compat_reply_payload(intr, runtime_context_update=cleared, kitten_attachments=kitten_extra or None)
        return _facade()._attach_compat_chat_trace(payload, body, message=body.message, runtime_context=cleared, channel='compat_chat')
    vector_error = _facade()._ensure_vector_index_if_needed(body.message, runtime_context)
    if vector_error:
        payload = _facade()._xcagi_compat_reply_payload(vector_error, kitten_attachments=kitten_extra or None)
        return _facade()._attach_compat_chat_trace(payload, body, message=body.message, runtime_context=runtime_context, channel='compat_chat')
    timeout = _facade()._xcagi_chat_timeout_seconds()
    pre_run = None
    planner_runtime_context = dict(runtime_context or {})
    if body.system_prompt:
        planner_runtime_context['system_prompt'] = body.system_prompt
    if body.db_write_token:
        planner_runtime_context['db_write_token_present'] = True
    if _facade()._use_ai_chat_mainline(planner_runtime_context):
        try:
            payload = await _facade()._await_with_timeout(_facade()._execute_ai_chat_mainline(body, planner_runtime_context, kitten_extra=kitten_extra or None), timeout=timeout)
            if payload.get('run_id') or payload.get('agent_run_id'):
                return _facade().cast('dict[str, Any]', payload)
            return _facade()._attach_compat_chat_trace(payload, body, message=body.message, runtime_context=planner_runtime_context, channel='compat_chat_mainline')
        except TimeoutError:
            payload = _facade()._xcagi_chat_timeout_error_payload(timeout)
            return _facade()._attach_compat_chat_trace(payload, body, message=body.message, runtime_context=planner_runtime_context, channel='compat_chat_mainline')
        except _facade().RECOVERABLE_ERRORS as e:
            if not _facade()._legacy_chat_fallback_allowed(planner_runtime_context):
                raise _facade()._xcagi_chat_http_exc(e) from e
            _facade().logger.warning('AIChatApplicationService mainline failed; legacy fallback explicitly allowed: %s', e, exc_info=True)
    try:
        workspace_root = _facade().os.environ.get('WORKSPACE_ROOT', _facade().os.getcwd())
        llm_client = _facade().create_modstore_openai_client_from_request(request)
        try:
            pre_run = _facade().start_legacy_chat_run(message=body.message, runtime_context=planner_runtime_context, user_id=getattr(body, 'user_id', None), source=getattr(body, 'source', None), channel='compat_chat')
            planner_runtime_context['run_id'] = pre_run.run_id
            planner_runtime_context['agent_run_id'] = pre_run.run_id
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.debug('legacy planner AgentRun pre-create skipped', exc_info=True)
        reply = await _facade()._await_with_timeout(_facade().asyncio.to_thread(_facade().run_agent_chat, body.message, runtime_context=planner_runtime_context or None, system_prompt=body.system_prompt, workspace_root=workspace_root, db_write_token=body.db_write_token, client=llm_client), timeout=timeout)
        try:
            parsed = reply if isinstance(reply, dict) else None
            if parsed is None and isinstance(reply, str):
                parsed = _facade().json.loads(reply)
            if isinstance(parsed, dict) and parsed.get('requires_token'):
                payload = _facade()._legacy_requires_token_payload(parsed)
                if pre_run is not None:
                    return _facade().finalize_legacy_chat_run(pre_run.run_id, payload, message=body.message, runtime_context=planner_runtime_context, user_id=getattr(body, 'user_id', None), source=getattr(body, 'source', None), channel='compat_chat')
                return _facade()._attach_compat_chat_trace(payload, body, message=body.message, runtime_context=planner_runtime_context, channel='compat_chat')
        except _facade().json.JSONDecodeError:
            pass
        _facade()._clear_legacy_tool_result_if_reply_has_no_records(reply)
    except TimeoutError:
        payload = _facade()._xcagi_chat_timeout_error_payload(timeout)
        if pre_run is not None:
            return _facade().finalize_legacy_chat_run(pre_run.run_id, payload, message=body.message, runtime_context=planner_runtime_context, user_id=getattr(body, 'user_id', None), source=getattr(body, 'source', None), channel='compat_chat')
        return _facade()._attach_compat_chat_trace(payload, body, message=body.message, runtime_context=planner_runtime_context, channel='compat_chat')
    except _facade().RECOVERABLE_ERRORS as e:
        if pre_run is not None:
            err_payload = {'success': False, 'message': str(e), 'response': str(e), 'data': {'error': str(e)}}
            _facade().finalize_legacy_chat_run(pre_run.run_id, err_payload, message=body.message, runtime_context=planner_runtime_context, user_id=getattr(body, 'user_id', None), source=getattr(body, 'source', None), channel='compat_chat')
        raise _facade()._xcagi_chat_http_exc(e) from e
    payload = _facade()._xcagi_compat_reply_payload(reply, kitten_attachments=kitten_extra or None)
    if pre_run is not None:
        return _facade().finalize_legacy_chat_run(pre_run.run_id, payload, message=body.message, runtime_context=planner_runtime_context, user_id=getattr(body, 'user_id', None), source=getattr(body, 'source', None), channel='compat_chat')
    return _facade()._attach_compat_chat_trace(payload, body, message=body.message, runtime_context=planner_runtime_context, channel='compat_chat')

async def execute_compat_chat_batch(request: Request, body: XcagiCompatChatBatchBody) -> dict[str, Any]:
    msgs = [str(x).strip() for x in body.messages or [] if str(x).strip()]
    if not msgs:
        raise _facade().HTTPException(status_code=400, detail='messages 须为非空字符串数组')
    _facade().assert_p2_elevated_claim_or_raise(request)
    batch_tier = _facade().resolve_ai_tier(request)
    m = (body.mode or '').strip().lower()
    if m in ('online', 'offline'):
        _facade().set_llm_mode(m)
    results: list[dict[str, Any]] = []
    timeout = _facade()._xcagi_chat_timeout_seconds()
    rolling_ctx = body.context
    llm_client = _facade().create_modstore_openai_client_from_request(request)
    for txt in msgs:
        (runtime_context, _) = _facade()._merge_runtime_context_with_message_paths(rolling_ctx, txt)
        runtime_context = _facade()._runtime_context_with_authenticated_actor(request, runtime_context)
        runtime_context = _facade().runtime_context_with_tier(runtime_context, batch_tier)
        from app.application.chat_business_safety import try_handle_business_chat_action
        business_payload = try_handle_business_chat_action(txt, runtime_context=runtime_context, user_id=getattr(body, 'user_id', None), request=request)
        if business_payload is not None:
            results.append(business_payload)
            continue
        (ok_read, read_req) = _facade()._ensure_chat_db_read_authorized(request, message=txt, provided_token=body.db_read_token)
        if not ok_read and read_req:
            payload = {'success': True, 'requires_token': True, 'token_name': read_req.get('token_name'), 'token_description': read_req.get('token_description'), 'message': read_req.get('message'), 'response': read_req.get('message'), 'data': {'requires_token': True, 'token_name': read_req.get('token_name'), 'token_description': read_req.get('token_description')}}
            results.append(_facade()._attach_compat_chat_trace(payload, body, message=txt, runtime_context=runtime_context, channel='compat_chat_batch'))
            continue
        if ok_read and _facade()._message_requires_db_read_token(txt):
            runtime_context['chat_db_read_authorized'] = True
        intr = _facade().planner_workflow_interrupt_reply(txt)
        if intr is not None:
            cleared = _facade().runtime_context_after_workflow_interrupt(runtime_context)
            rolling_ctx = cleared
            payload = _facade()._xcagi_compat_reply_payload(intr, runtime_context_update=cleared)
            results.append(_facade()._attach_compat_chat_trace(payload, body, message=txt, runtime_context=cleared, channel='compat_chat_batch'))
            continue
        vector_error = _facade()._ensure_vector_index_if_needed(txt, runtime_context)
        if vector_error:
            payload = _facade()._xcagi_compat_reply_payload(vector_error)
            results.append(_facade()._attach_compat_chat_trace(payload, body, message=txt, runtime_context=runtime_context, channel='compat_chat_batch'))
            continue
        pre_run = None
        planner_runtime_context = dict(runtime_context or {})
        if body.system_prompt:
            planner_runtime_context['system_prompt'] = body.system_prompt
        if body.db_write_token:
            planner_runtime_context['db_write_token_present'] = True
        if _facade()._use_ai_chat_mainline(planner_runtime_context):
            try:
                payload = await _facade()._await_with_timeout(_facade()._execute_ai_chat_mainline(body, planner_runtime_context, message=txt), timeout=timeout)
                results.append(payload if payload.get('run_id') or payload.get('agent_run_id') else _facade()._attach_compat_chat_trace(payload, body, message=txt, runtime_context=planner_runtime_context, channel='compat_chat_batch_mainline'))
                continue
            except TimeoutError:
                payload = _facade()._xcagi_chat_timeout_error_payload(timeout)
                results.append(_facade()._attach_compat_chat_trace(payload, body, message=txt, runtime_context=planner_runtime_context, channel='compat_chat_batch_mainline'))
                continue
            except _facade().RECOVERABLE_ERRORS as e:
                if not _facade()._legacy_chat_fallback_allowed(planner_runtime_context):
                    err = _facade()._xcagi_chat_http_exc(e)
                    results.append({'success': False, 'message': err.detail if isinstance(err.detail, str) else str(err.detail), 'response': err.detail if isinstance(err.detail, str) else str(err.detail), 'data': {'error': str(e)}})
                    continue
                _facade().logger.warning('AIChatApplicationService batch mainline failed; legacy fallback explicitly allowed: %s', e, exc_info=True)
        try:
            try:
                pre_run = _facade().start_legacy_chat_run(message=txt, runtime_context=planner_runtime_context, user_id=getattr(body, 'user_id', None), source=getattr(body, 'source', None), channel='compat_chat_batch')
                planner_runtime_context['run_id'] = pre_run.run_id
                planner_runtime_context['agent_run_id'] = pre_run.run_id
            except _facade().RECOVERABLE_ERRORS:
                _facade().logger.debug('legacy batch planner AgentRun pre-create skipped', exc_info=True)
            workspace_root = _facade().os.environ.get('WORKSPACE_ROOT', _facade().os.getcwd())
            reply = await _facade()._await_with_timeout(_facade().asyncio.to_thread(_facade().run_agent_chat, txt, runtime_context=planner_runtime_context or None, system_prompt=body.system_prompt, workspace_root=workspace_root, db_write_token=body.db_write_token, client=llm_client), timeout=timeout)
            try:
                parsed = reply if isinstance(reply, dict) else None
                if parsed is None and isinstance(reply, str):
                    parsed = _facade().json.loads(reply)
                if isinstance(parsed, dict) and parsed.get('requires_token'):
                    payload = _facade()._legacy_requires_token_payload(parsed)
                    if pre_run is not None:
                        results.append(_facade().finalize_legacy_chat_run(pre_run.run_id, payload, message=txt, runtime_context=planner_runtime_context, user_id=getattr(body, 'user_id', None), source=getattr(body, 'source', None), channel='compat_chat_batch'))
                    else:
                        results.append(_facade()._attach_compat_chat_trace(payload, body, message=txt, runtime_context=planner_runtime_context, channel='compat_chat_batch'))
                    continue
            except _facade().json.JSONDecodeError:
                pass
            _facade()._clear_legacy_tool_result_if_reply_has_no_records(reply)
            payload = _facade()._xcagi_compat_reply_payload(reply)
            if pre_run is not None:
                results.append(_facade().finalize_legacy_chat_run(pre_run.run_id, payload, message=txt, runtime_context=planner_runtime_context, user_id=getattr(body, 'user_id', None), source=getattr(body, 'source', None), channel='compat_chat_batch'))
            else:
                results.append(_facade()._attach_compat_chat_trace(payload, body, message=txt, runtime_context=planner_runtime_context, channel='compat_chat_batch'))
        except TimeoutError:
            payload = _facade()._xcagi_chat_timeout_error_payload(timeout)
            if pre_run is not None:
                results.append(_facade().finalize_legacy_chat_run(pre_run.run_id, payload, message=txt, runtime_context=planner_runtime_context, user_id=getattr(body, 'user_id', None), source=getattr(body, 'source', None), channel='compat_chat_batch'))
            else:
                results.append(_facade()._attach_compat_chat_trace(payload, body, message=txt, runtime_context=planner_runtime_context, channel='compat_chat_batch'))
        except _facade().RECOVERABLE_ERRORS as e:
            err = _facade()._xcagi_chat_http_exc(e)
            payload = {'success': False, 'message': err.detail if isinstance(err.detail, str) else str(err.detail)}
            if pre_run is not None:
                results.append(_facade().finalize_legacy_chat_run(pre_run.run_id, payload, message=txt, runtime_context=planner_runtime_context, user_id=getattr(body, 'user_id', None), source=getattr(body, 'source', None), channel='compat_chat_batch'))
            else:
                results.append(_facade()._attach_compat_chat_trace(payload, body, message=txt, runtime_context=planner_runtime_context, channel='compat_chat_batch'))
    ok = all((r.get('success') for r in results))
    return {'success': ok, 'batch': True, 'results': results, 'count': len(results)}
