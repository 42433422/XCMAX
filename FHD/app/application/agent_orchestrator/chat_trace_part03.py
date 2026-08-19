# ruff: noqa
# mypy: ignore-errors
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.application.agent_orchestrator.chat_trace')

def finalize_legacy_chat_run(run_id: str, payload: dict[str, _facade().Any], *, message: str, runtime_context: dict[str, _facade().Any] | None=None, user_id: str | None=None, source: str | None=None, channel: str='compat_chat', intent: str='legacy_chat_adapter') -> dict[str, _facade().Any]:
    if not isinstance(payload, dict):
        return payload
    repository = _facade().get_agent_run_repository()
    run = repository.get(run_id)
    if run is None:
        return _facade().attach_chat_trace_run(payload, message=message, runtime_context=runtime_context, user_id=user_id, source=source, channel=channel, intent=intent)
    status = _facade()._payload_status(payload)
    records = _facade()._extract_legacy_tool_records(payload)
    run.status = status
    run.error = ''
    run.metadata['channel'] = channel
    run.metadata['source'] = str(source or '').strip()
    run.metadata['trace_mode'] = 'legacy_planner_run'
    run.metadata['runtime_context'] = _facade()._trace_safe_value(runtime_context or {})
    run.add_event('planner.completed', '执行计划已生成', {'status': status, 'observed_tool_records': len(records)})
    node_outputs: dict[str, _facade().Any] = {}
    total_cost = 0
    if records:
        run.metadata['trace_mode'] = 'legacy_planner_run_with_tools'
        (node_outputs, total_cost) = _facade()._append_legacy_tool_records_to_run(run, records)
        if status == 'completed' and any((step.status == 'failed' for step in run.steps)):
            run.status = 'failed'
            run.error = 'legacy planner tool failed'
    _facade()._append_llm_calls_to_run(run, _facade()._extract_llm_calls(payload))
    _facade()._append_retrieval_calls_to_run(run, _facade()._extract_retrieval_calls(payload, query=message))
    _facade()._append_memory_references_to_run(run, _facade()._extract_memory_references(payload, query=message))
    _facade()._append_artifacts_to_run(run, _facade()._extract_artifacts(payload))
    run.metadata['tool_call_count'] = len(run.tool_calls)
    run.metadata['cost_units_total'] = total_cost
    run.final_output = {'chat_payload': _facade()._trace_safe_value(payload), 'node_outputs': node_outputs, 'tool_calls': [call.to_dict() for call in run.tool_calls], 'cost_units_total': total_cost}
    _facade()._append_llm_calls_to_final_output(run)
    _facade()._append_retrieval_calls_to_final_output(run)
    _facade()._append_memory_references_to_final_output(run)
    _facade()._append_artifacts_to_final_output(run)
    if run.status == 'waiting_user':
        run.add_event('step.waiting_user', str(payload.get('message') or '等待用户授权'), {})
    elif run.status == 'failed':
        run.error = run.error or _facade()._payload_error_message(payload)
        run.add_event('run.failed', run.error, run.final_output)
    else:
        run.add_event('run.completed', '智能任务执行完成', run.final_output)
    repository.save(run)
    return _facade()._attach_run_id(payload, run.run_id)

def create_chat_trace_run(payload: dict[str, _facade().Any], *, message: str, runtime_context: dict[str, _facade().Any] | None=None, user_id: str | None=None, source: str | None=None, channel: str='compat_chat', intent: str='legacy_chat_adapter') -> _facade().AgentRun:
    repository = _facade().get_agent_run_repository()
    observed = _facade()._create_legacy_tool_records_run(payload, message=message, runtime_context=runtime_context, user_id=user_id, source=source, channel=channel, repository=repository, intent=str(intent or '').strip() if str(intent or '').strip() and str(intent or '').strip() != 'legacy_chat_adapter' else 'legacy_tool_chain')
    if observed is not None:
        return observed
    orchestrated = _facade()._create_tool_call_agent_run(payload, message=message, runtime_context=runtime_context, user_id=user_id, source=source, channel=channel, repository=repository)
    if orchestrated is not None:
        return orchestrated
    status = _facade()._payload_status(payload)
    resolved_user_id = _facade()._resolved_user_id(runtime_context=runtime_context, user_id=user_id)
    text = str(payload.get('response') or _facade()._payload_data(payload).get('text') or '')
    run = _facade().AgentRun(user_id=resolved_user_id, message=str(message or ''), status=status, intent=str(intent or 'legacy_chat_adapter').strip() or 'legacy_chat_adapter', metadata={'channel': channel, 'source': str(source or '').strip(), 'trace_mode': 'post_execution', 'runtime_context': _facade()._trace_safe_value(runtime_context or {})}, final_output={'chat_payload': _facade()._trace_safe_value(payload)})
    _facade().apply_task_context(run, runtime_context)
    run.add_event('run.created', 'Chat 请求已进入 AgentRun 追踪', {'channel': channel, 'source': str(source or '').strip()})
    _facade()._append_llm_calls_to_run(run, _facade()._extract_llm_calls(payload))
    _facade()._append_retrieval_calls_to_run(run, _facade()._extract_retrieval_calls(payload, query=message))
    _facade()._append_memory_references_to_run(run, _facade()._extract_memory_references(payload, query=message))
    _facade()._append_artifacts_to_run(run, _facade()._extract_artifacts(payload))
    _facade()._append_llm_calls_to_final_output(run)
    _facade()._append_retrieval_calls_to_final_output(run)
    _facade()._append_memory_references_to_final_output(run)
    _facade()._append_artifacts_to_final_output(run)
    if status == 'waiting_user':
        run.add_event('step.waiting_user', str(payload.get('message') or '等待用户授权'), {'token_name': payload.get('token_name') or _facade()._payload_data(payload).get('token_name'), 'token_description': payload.get('token_description') or _facade()._payload_data(payload).get('token_description')})
    elif status == 'failed':
        run.error = _facade()._payload_error_message(payload)
        run.add_event('run.failed', run.error, {'response_preview': text[:500]})
    else:
        run.add_event('run.completed', 'Chat 响应已完成', {'response_preview': text[:500]})
    return repository.save(run)

def attach_chat_trace_run(payload: dict[str, _facade().Any], *, message: str, runtime_context: dict[str, _facade().Any] | None=None, user_id: str | None=None, source: str | None=None, channel: str='compat_chat', intent: str='legacy_chat_adapter') -> dict[str, _facade().Any]:
    if not isinstance(payload, dict):
        return payload
    data = payload.get('data')
    if isinstance(data, dict) and (data.get('run_id') or data.get('agent_run_id')):
        return payload
    if payload.get('run_id') or payload.get('agent_run_id'):
        return payload
    try:
        run = _facade().create_chat_trace_run(payload, message=message, runtime_context=runtime_context, user_id=user_id, source=source, channel=channel, intent=intent)
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception('failed to attach AgentRun trace to chat response')
        return payload
    return _facade()._attach_run_id(payload, run.run_id)
