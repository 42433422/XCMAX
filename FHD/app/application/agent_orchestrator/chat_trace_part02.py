# ruff: noqa
# mypy: ignore-errors
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.application.agent_orchestrator.chat_trace')

def _memory_reference_from_payload(item: dict[str, _facade().Any], *, default_query: str) -> _facade().MemoryReference | None:
    has_marker = _facade()._has_user_memory_marker(item)
    raw_hits = _facade()._first_list_value(item, ('user_memory_hits', 'userMemoryHits', 'memory_hits', 'memoryHits', 'hits'))
    hits = [dict(_facade()._trace_safe_value(hit)) for hit in raw_hits if isinstance(hit, dict) and isinstance(_facade()._trace_safe_value(hit), dict)]
    summary = str(item.get('user_memory_rag_summary') or item.get('userMemoryRagSummary') or item.get('user_memory_summary') or item.get('userMemorySummary') or item.get('memory_summary') or item.get('summary') or item.get('prompt_memory') or '')
    error = str(item.get('user_memory_error') or item.get('userMemoryError') or item.get('memory_error') or item.get('memoryError') or '')
    if not has_marker and (not hits) and ('UserMemoryRAG' not in summary):
        return None
    if not hits and (not summary) and (not error):
        return None
    query = str(item.get('query') or item.get('user_message') or item.get('message') or default_query or '')
    memory_type = str(item.get('memory_type') or item.get('memoryType') or 'user_memory')
    source = str(item.get('source') or item.get('memory_source') or item.get('memorySource') or item.get('index_id') or item.get('collection') or 'user_memory_rag')
    status: _facade().Literal['completed', 'failed'] = 'failed' if error else 'completed'
    return _facade().MemoryReference(query=query, memory_type=memory_type, source=source, hits=hits, summary=summary, status=status, error=error, metadata={'top_k': _facade()._coerce_trace_int(item.get('top_k') or item.get('topK')), 'hit_count': len(hits), 'raw_trace': _facade()._trace_safe_value({key: item.get(key) for key in ('query', 'user_message', 'source', 'memory_source', 'index_id', 'collection', 'top_k', 'user_memory_error', 'memory_error') if key in item})})

def _extract_memory_references(payload: dict[str, _facade().Any], *, query: str='') -> list[_facade().MemoryReference]:
    references: list[_facade().MemoryReference] = []
    seen: set[tuple[_facade().Any, ...]] = set()
    for item in _facade()._iter_memory_payloads(payload):
        reference = _facade()._memory_reference_from_payload(item, default_query=query)
        if reference is None:
            continue
        signature = _facade()._memory_reference_signature(reference)
        if signature in seen:
            continue
        seen.add(signature)
        references.append(reference)
    return references

def _refresh_memory_metadata(run: _facade().AgentRun) -> None:
    run.metadata['memory_reference_count'] = len(run.memory_references)
    run.metadata['memory_hit_count'] = sum((len(reference.hits) for reference in run.memory_references))
    run.metadata['memory_sources'] = sorted({reference.source for reference in run.memory_references if reference.source})

def _append_memory_references_to_run(run: _facade().AgentRun, references: list[_facade().MemoryReference]) -> None:
    existing = {_facade()._memory_reference_signature(reference) for reference in run.memory_references}
    for reference in references:
        signature = _facade()._memory_reference_signature(reference)
        if signature in existing:
            continue
        existing.add(signature)
        run.memory_references.append(reference)
        first_sources = [str(hit.get('source') or hit.get('chunk_id') or hit.get('id') or '') for hit in reference.hits[:5]]
        run.add_event('memory.recalled' if reference.status == 'completed' else 'memory.failed', f'记录用户记忆召回 {reference.memory_type}', {'reference_id': reference.reference_id, 'query': reference.query, 'memory_type': reference.memory_type, 'source': reference.source, 'hit_count': len(reference.hits), 'summary_preview': reference.summary[:500], 'hit_sources': first_sources, 'error': reference.error})
    if run.memory_references:
        _facade()._refresh_memory_metadata(run)

def _append_memory_references_to_final_output(run: _facade().AgentRun) -> None:
    if not run.memory_references:
        return
    final_output = dict(run.final_output or {})
    final_output['memory_references'] = [reference.to_dict() for reference in run.memory_references]
    final_output['memory_hit_count'] = run.metadata.get('memory_hit_count', 0)
    run.final_output = final_output

def _artifact_signature(artifact: _facade().AgentArtifact) -> tuple[str, str, str, str, str]:
    return (artifact.artifact_type, artifact.name, artifact.uri, artifact.source, artifact.summary[:240])

def _iter_explicit_artifact_payloads(payload: dict[str, _facade().Any]) -> _facade().Iterator[dict[str, _facade().Any]]:
    for item in _facade()._iter_payload_dicts(payload):
        artifacts = item.get('artifacts')
        if isinstance(artifacts, dict):
            yield artifacts
        elif isinstance(artifacts, list):
            for artifact in artifacts:
                if isinstance(artifact, dict):
                    yield artifact
        artifact = item.get('artifact')
        if isinstance(artifact, dict):
            yield artifact

def _artifact_from_ocr_payload(item: dict[str, _facade().Any]) -> _facade().AgentArtifact | None:
    text = str(item.get('text') or item.get('ocr_text') or '').strip()
    file_path = str(item.get('file_path') or item.get('image_path') or item.get('uri') or '').strip()
    has_ocr_shape = bool(text) and ('confidence' in item or 'ocr_confidence' in item or 'analysis' in item or ('structured_data' in item) or (isinstance(item.get('data'), dict) and 'raw_text' in item.get('data', {})) or bool(file_path))
    if not has_ocr_shape:
        return None
    structured = item.get('structured_data')
    if not isinstance(structured, dict):
        data = item.get('data')
        structured = data if isinstance(data, dict) else {}
    analysis = item.get('analysis') if isinstance(item.get('analysis'), dict) else {}
    confidence = item.get('confidence', item.get('ocr_confidence', 0))
    preview = {'text': text[:1000], 'confidence': _facade()._coerce_trace_float(confidence), 'structured_data': _facade()._trace_safe_value(structured), 'analysis': _facade()._trace_safe_value(analysis)}
    fields = [{'name': key, 'value': _facade()._trace_safe_value(value)} for (key, value) in structured.items() if value not in (None, '', [], {})][:20]
    summary = str(item.get('message') or item.get('summary') or 'OCR 解析结果').strip()
    return _facade().AgentArtifact(artifact_type='ocr_text', name=str(item.get('name') or item.get('filename') or 'ocr_result'), source=str(item.get('source') or 'ocr'), uri=file_path, mime_type=str(item.get('mime_type') or 'image/*'), summary=summary, fields=fields, preview=preview, metadata={'parser_used': 'ocr', 'success': item.get('success')})

def _artifact_from_file_analysis_payload(item: dict[str, _facade().Any]) -> _facade().AgentArtifact | None:
    if not any((key in item for key in ('parser_used', 'suggested_use', 'db_meta', 'extension'))):
        return None
    parser_used = str(item.get('parser_used') or '').strip()
    extension = str(item.get('extension') or '').strip().lower()
    suggested_use = str(item.get('suggested_use') or '').strip()
    saved_name = str(item.get('saved_name') or item.get('name') or item.get('filename') or '').strip()
    if not any((parser_used, extension, suggested_use, saved_name)):
        return None
    if parser_used == 'sqlite_db' or extension == '.db' or suggested_use.endswith('_db'):
        artifact_type = 'database_file'
    elif extension in {'.xlsx', '.xls', '.xlsm'} or 'excel' in parser_used:
        artifact_type = 'excel_file'
    elif extension == '.pdf' or 'pdf' in parser_used:
        artifact_type = 'pdf_document'
    elif extension in {'.doc', '.docx', '.ppt', '.pptx'} or 'office' in parser_used:
        artifact_type = 'office_document'
    else:
        artifact_type = 'file_analysis'
    db_meta = item.get('db_meta') if isinstance(item.get('db_meta'), dict) else {}
    if not isinstance(db_meta, dict):
        db_meta = {}
    table_columns = db_meta.get('table_columns') if isinstance(db_meta.get('table_columns'), dict) else {}
    fields = [{'name': str(table), 'columns': list(columns or [])[:40]} for (table, columns) in (table_columns or {}).items()][:20]
    preview = {'parser_used': parser_used, 'extension': extension, 'suggested_use': suggested_use, 'text_preview': str(item.get('text_preview') or '')[:1000], 'db_meta': _facade()._trace_safe_value(db_meta), 'unit_candidates': _facade()._trace_safe_value(item.get('unit_candidates') or [])}
    return _facade().AgentArtifact(artifact_type=artifact_type, name=saved_name or str(item.get('raw_filename') or item.get('filename') or 'file_analysis'), source=str(item.get('source') or 'file_analysis'), uri=str(item.get('file_path') or item.get('uri') or saved_name), mime_type=str(item.get('mime_type') or ''), summary=str(item.get('ai_summary') or item.get('message') or suggested_use or parser_used), fields=fields, preview=preview, metadata={'parser_used': parser_used, 'extension': extension, 'suggested_use': suggested_use, 'success': item.get('success')})

def _mime_from_document_name(name: str, default: str='') -> str:
    lowered = name.lower().strip()
    if lowered.endswith('.pdf'):
        return 'application/pdf'
    if lowered.endswith('.docx'):
        return 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    if lowered.endswith('.xlsx'):
        return 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    if lowered.endswith('.pptx'):
        return 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
    return default

def _artifact_type_from_document(name: str, mime_type: str) -> str:
    lowered_name = name.lower().strip()
    lowered_mime = mime_type.lower().strip()
    if lowered_name.endswith('.pdf') or lowered_mime == 'application/pdf':
        return 'pdf_document'
    if lowered_name.endswith(('.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx')):
        return 'office_document'
    if 'officedocument' in lowered_mime:
        return 'office_document'
    return 'document_file'

def _artifact_from_generated_document_payload(item: dict[str, _facade().Any]) -> _facade().AgentArtifact | None:
    document = item.get('document')
    candidate = document if isinstance(document, dict) else item
    has_document_marker = isinstance(document, dict) or any((key in candidate for key in ('download_url', 'pickup_token', 'document_url', 'doc_url')))
    if not has_document_marker:
        return None
    name = str(candidate.get('file_name') or candidate.get('doc_name') or candidate.get('filename') or candidate.get('name') or '').strip()
    uri = str(candidate.get('download_url') or candidate.get('document_url') or candidate.get('doc_url') or candidate.get('file_path') or candidate.get('uri') or '').strip()
    pickup_token = str(candidate.get('pickup_token') or candidate.get('token') or '').strip()
    if not any((name, uri, pickup_token)):
        return None
    mime_type = str(candidate.get('mime_type') or candidate.get('mime') or '').strip()
    mime_type = mime_type or _facade()._mime_from_document_name(name)
    artifact_type = _facade()._artifact_type_from_document(name, mime_type)
    source = str(candidate.get('source') or item.get('source') or 'generated_document')
    summary = str(candidate.get('summary') or candidate.get('message') or item.get('message') or '生成文档').strip()
    return _facade().AgentArtifact(artifact_type=artifact_type, name=name or uri or 'generated_document', source=source, uri=uri, mime_type=mime_type, summary=summary, preview={'file_name': name, 'download_url': uri, 'pickup_token': pickup_token}, metadata={'pickup_token': pickup_token, 'success': candidate.get('success', item.get('success')), 'generator': source})

def _artifact_from_excel_analysis_payload(item: dict[str, _facade().Any]) -> _facade().AgentArtifact | None:
    preview_data = item.get('preview_data')
    if not isinstance(preview_data, dict):
        return None
    if not any((key in preview_data for key in ('sample_rows', 'grid_preview', 'file_path', 'sheet_name', 'selected_sheet_name'))):
        return None
    fields = item.get('fields')
    if not isinstance(fields, list):
        fields = []
    record_count = _facade()._coerce_trace_int(item.get('record_count') or preview_data.get('record_count') or len(preview_data.get('sample_rows') or []))
    file_path = str(item.get('file_path') or preview_data.get('file_path') or '').strip()
    return _facade().AgentArtifact(artifact_type='excel_records', name=str(item.get('name') or preview_data.get('filename') or file_path or 'excel_analysis'), source=str(item.get('source') or 'excel_analysis'), uri=file_path, mime_type=str(item.get('mime_type') or 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'), summary=str(item.get('summary') or 'Excel 解析结果'), fields=[field for field in fields if isinstance(field, dict)][:40], preview={'record_count': record_count, 'preview_data': _facade()._trace_safe_value(preview_data)}, metadata={'parser_used': 'excel_analysis', 'success': item.get('success')})

def _iter_inferred_artifacts(payload: dict[str, _facade().Any]) -> _facade().Iterator[_facade().AgentArtifact]:
    for item in _facade()._iter_payload_dicts(payload):
        for key in ('ocr_result', 'ocr', 'recognized_text'):
            nested = item.get(key)
            if isinstance(nested, dict):
                artifact = _facade()._artifact_from_ocr_payload(nested)
                if artifact is not None:
                    yield artifact
        for key in ('file_analysis', 'analysis_result'):
            nested = item.get(key)
            if isinstance(nested, dict):
                artifact = _facade()._artifact_from_file_analysis_payload(nested)
                if artifact is not None:
                    yield artifact
        for key in ('document', 'generated_document', 'office_document'):
            nested = item.get(key)
            if isinstance(nested, dict):
                artifact = _facade()._artifact_from_generated_document_payload({'document': nested})
                if artifact is not None:
                    yield artifact
        excel_analysis = item.get('excel_analysis')
        if isinstance(excel_analysis, dict):
            artifact = _facade()._artifact_from_excel_analysis_payload(excel_analysis)
            if artifact is not None:
                yield artifact
        for factory in (_facade()._artifact_from_ocr_payload, _facade()._artifact_from_file_analysis_payload, _facade()._artifact_from_generated_document_payload, _facade()._artifact_from_excel_analysis_payload):
            artifact = factory(item)
            if artifact is not None:
                yield artifact

def _extract_artifacts(payload: dict[str, _facade().Any]) -> list[_facade().AgentArtifact]:
    artifacts: list[_facade().AgentArtifact] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for explicit in _facade()._iter_explicit_artifact_payloads(payload):
        artifact = _facade().artifact_from_dict(explicit)
        if not artifact.artifact_type:
            continue
        signature = _facade()._artifact_signature(artifact)
        if signature in seen:
            continue
        seen.add(signature)
        artifacts.append(artifact)
    for artifact in _facade()._iter_inferred_artifacts(payload):
        if not artifact.artifact_type:
            continue
        signature = _facade()._artifact_signature(artifact)
        if signature in seen:
            continue
        seen.add(signature)
        artifacts.append(artifact)
    return artifacts

def _refresh_artifact_metadata(run: _facade().AgentRun) -> None:
    run.metadata['artifact_count'] = len(run.artifacts)
    run.metadata['artifact_types'] = sorted({artifact.artifact_type for artifact in run.artifacts})

def _append_artifacts_to_run(run: _facade().AgentRun, artifacts: list[_facade().AgentArtifact]) -> None:
    existing = {_facade()._artifact_signature(artifact) for artifact in run.artifacts}
    for artifact in artifacts:
        signature = _facade()._artifact_signature(artifact)
        if signature in existing:
            continue
        existing.add(signature)
        run.artifacts.append(artifact)
        run.add_event('artifact.attached', f'Artifact 已附加: {artifact.artifact_type}', {'artifact_id': artifact.artifact_id, 'artifact_type': artifact.artifact_type, 'name': artifact.name, 'source': artifact.source, 'uri': artifact.uri})
        _facade().ingest_artifact_to_dataset(run, artifact)
    if run.artifacts:
        _facade()._refresh_artifact_metadata(run)

def _append_artifacts_to_final_output(run: _facade().AgentRun) -> None:
    if not run.artifacts:
        return
    final_output = dict(run.final_output or {})
    final_output['artifacts'] = [artifact.to_dict() for artifact in run.artifacts]
    final_output['artifact_count'] = len(run.artifacts)
    if run.metadata.get('dataset_ingests'):
        final_output['dataset_ingests'] = run.metadata['dataset_ingests']
        final_output['dataset_ingest_count'] = run.metadata.get('dataset_ingest_count', 0)
    run.final_output = final_output

def _normalized_record_payload(record: dict[str, _facade().Any]) -> tuple[str, str, dict[str, _facade().Any], dict[str, _facade().Any]]:
    tool_id = str(record.get('tool_id') or record.get('tool_name') or record.get('tool_key') or '').strip()
    action = str(record.get('action') or '').strip() or 'execute'
    params = record.get('params')
    output = record.get('output')
    return (tool_id, action, dict(params) if isinstance(params, dict) else {}, dict(output) if isinstance(output, dict) else {'success': False, 'message': str(output or '')})

def _append_legacy_tool_records_to_run(run: _facade().AgentRun, records: list[dict[str, _facade().Any]]) -> tuple[dict[str, _facade().Any], int]:
    node_outputs: dict[str, _facade().Any] = {}
    total_cost = 0
    for (idx, record) in enumerate(records, start=1):
        (tool_id, action, params, output) = _facade()._normalized_record_payload(record)
        if not tool_id:
            continue
        from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
        spec = get_tool_action_spec(tool_id, action)
        node_id = f'legacy_{idx}_{tool_id}_{action}'.replace('.', '_')
        step = _facade().AgentStep(node_id=node_id, tool_id=tool_id, action=getattr(spec, 'action', action) if spec is not None else action, params=params, risk=getattr(spec, 'risk', 'medium') if spec is not None else 'medium', idempotent=bool(getattr(spec, 'idempotent', False)) if spec is not None else False, description='legacy planner 已执行工具调用', status='completed' if output.get('success') is not False else 'failed', output=output, finished_at=_facade().utc_now_iso())
        call = _facade().ToolCall(step_id=step.step_id, node_id=step.node_id, tool_id=step.tool_id, action=step.action, params=params, status='completed' if step.status == 'completed' else 'failed', output=output, error='' if step.status == 'completed' else str(output.get('message') or output.get('error') or ''), cost_units=int(getattr(spec, 'cost_units', 0) or 0), permission=str(getattr(spec, 'permission', '') or ''), finished_at=step.finished_at, metadata={'observed': True, 'legacy_tool_call_id': str(record.get('tool_call_id') or ''), 'risk': step.risk, 'idempotent': step.idempotent})
        run.steps.append(step)
        run.tool_calls.append(call)
        node_outputs[step.node_id] = output
        total_cost += call.cost_units
        run.add_event('tool.started', f'观察到 legacy 工具 {step.tool_id}.{step.action}', {'step_id': step.step_id, 'node_id': step.node_id, 'call_id': call.call_id, 'cost_units': call.cost_units, 'permission': call.permission, 'observed': True})
        event_type = 'tool.completed' if step.status == 'completed' else 'tool.failed'
        run.add_event(event_type, f'记录 legacy 工具 {step.tool_id}.{step.action}', {'step_id': step.step_id, 'node_id': step.node_id, 'call_id': call.call_id, 'cost_units': call.cost_units, 'observed': True})
        _facade()._append_artifacts_to_run(run, _facade()._extract_artifacts(output))
    return (node_outputs, total_cost)

def _create_legacy_tool_records_run(payload: dict[str, _facade().Any], *, message: str, runtime_context: dict[str, _facade().Any] | None, user_id: str | None, source: str | None, channel: str, repository: _facade().AgentRunRepository, intent: str='legacy_tool_chain') -> _facade().AgentRun | None:
    records = _facade()._extract_legacy_tool_records(payload)
    if not records:
        return None
    resolved_user_id = _facade()._resolved_user_id(runtime_context=runtime_context, user_id=user_id)
    status = _facade()._payload_status(payload)
    run = _facade().AgentRun(user_id=resolved_user_id, message=str(message or ''), status=status, intent=str(intent or 'legacy_tool_chain').strip() or 'legacy_tool_chain', metadata={'channel': channel, 'source': str(source or '').strip(), 'trace_mode': 'legacy_tool_records', 'runtime_context': _facade()._trace_safe_value(runtime_context or {})}, final_output={'chat_payload': _facade()._trace_safe_value(payload)})
    _facade().apply_task_context(run, runtime_context)
    run.add_event('run.created', 'Legacy planner 工具调用已进入 AgentRun 追踪', {'channel': channel, 'source': str(source or '').strip(), 'observed': True})
    (node_outputs, total_cost) = _facade()._append_legacy_tool_records_to_run(run, records)
    _facade()._append_llm_calls_to_run(run, _facade()._extract_llm_calls(payload))
    _facade()._append_retrieval_calls_to_run(run, _facade()._extract_retrieval_calls(payload, query=message))
    _facade()._append_memory_references_to_run(run, _facade()._extract_memory_references(payload, query=message))
    _facade()._append_artifacts_to_run(run, _facade()._extract_artifacts(payload))
    if run.steps and status == 'completed' and any((step.status == 'failed' for step in run.steps)):
        run.status = 'failed'
        run.error = 'legacy planner tool failed'
    run.metadata['tool_call_count'] = len(run.tool_calls)
    run.metadata['cost_units_total'] = total_cost
    run.final_output = {'chat_payload': _facade()._trace_safe_value(payload), 'node_outputs': node_outputs, 'tool_calls': [call.to_dict() for call in run.tool_calls], 'cost_units_total': total_cost}
    _facade()._append_llm_calls_to_final_output(run)
    _facade()._append_retrieval_calls_to_final_output(run)
    _facade()._append_memory_references_to_final_output(run)
    _facade()._append_artifacts_to_final_output(run)
    if run.status == 'failed':
        run.add_event('run.failed', run.error or 'Legacy planner 工具调用失败', run.final_output)
    elif run.status == 'waiting_user':
        run.add_event('step.waiting_user', str(payload.get('message') or '等待用户授权'), {})
    else:
        run.add_event('run.completed', 'Legacy planner 工具调用追踪完成', run.final_output)
    return repository.save(run)

def _create_tool_call_agent_run(payload: dict[str, _facade().Any], *, message: str, runtime_context: dict[str, _facade().Any] | None, user_id: str | None, source: str | None, channel: str, repository: _facade().AgentRunRepository) -> _facade().AgentRun | None:
    extracted = _facade()._extract_low_risk_tool_call(payload)
    if extracted is None:
        return None
    (tool_id, action, params, raw_tool_call) = extracted
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.workflow.types import PlanGraph, WorkflowNode
    resolved_user_id = _facade()._resolved_user_id(runtime_context=runtime_context, user_id=user_id)
    runtime = dict(runtime_context or {})
    runtime.update({'channel': channel, 'source': str(source or '').strip(), 'trace_mode': 'orchestrated_tool_call', 'legacy_tool_call': _facade()._trace_safe_value(raw_tool_call)})
    plan = PlanGraph(plan_id=f'compat-tool-{_facade().uuid4().hex[:12]}', intent=f'{tool_id}_{action}', todo_steps=[f'执行兼容工具 {tool_id}.{action}'], nodes=[WorkflowNode(node_id=f'{tool_id}_{action}', tool_id=tool_id, action=action, params=params, risk='low', idempotent=True, description=f'兼容 toolCall 接管: {tool_id}.{action}')], risk_level='low', metadata={'channel': channel, 'source': str(source or '').strip(), 'trace_mode': 'orchestrated_tool_call', 'legacy_tool_call': _facade()._trace_safe_value(raw_tool_call)})
    run = AgentOrchestrator(repository=repository).start_run_from_plan(user_id=resolved_user_id, message=str(message or ''), plan=plan, runtime_context=runtime, auto_execute=True)
    run.metadata['channel'] = channel
    run.metadata['source'] = str(source or '').strip()
    run.metadata['trace_mode'] = 'orchestrated_tool_call'
    _facade()._append_llm_calls_to_run(run, _facade()._extract_llm_calls(payload))
    _facade()._append_retrieval_calls_to_run(run, _facade()._extract_retrieval_calls(payload, query=message))
    _facade()._append_memory_references_to_run(run, _facade()._extract_memory_references(payload, query=message))
    _facade()._append_artifacts_to_run(run, _facade()._extract_artifacts(payload))
    _facade()._append_llm_calls_to_final_output(run)
    _facade()._append_retrieval_calls_to_final_output(run)
    _facade()._append_memory_references_to_final_output(run)
    _facade()._append_artifacts_to_final_output(run)
    return repository.save(run)

def _attach_run_id(payload: dict[str, _facade().Any], run_id: str) -> dict[str, _facade().Any]:
    payload['run_id'] = run_id
    payload['agent_run_id'] = run_id
    data = payload.get('data')
    if isinstance(data, dict):
        data['run_id'] = run_id
        data['agent_run_id'] = run_id
    else:
        payload['data'] = {'run_id': run_id, 'agent_run_id': run_id}
    return payload

def start_legacy_chat_run(*, message: str, runtime_context: dict[str, _facade().Any] | None=None, user_id: str | None=None, source: str | None=None, channel: str='compat_chat', intent: str='legacy_chat_adapter') -> _facade().AgentRun:
    resolved_user_id = _facade()._resolved_user_id(runtime_context=runtime_context, user_id=user_id)
    run = _facade().AgentRun(user_id=resolved_user_id, message=str(message or ''), status='running', intent=str(intent or 'legacy_chat_adapter').strip() or 'legacy_chat_adapter', metadata={'channel': channel, 'source': str(source or '').strip(), 'trace_mode': 'legacy_planner_run', 'runtime_context': _facade()._trace_safe_value(runtime_context or {})})
    _facade().apply_task_context(run, runtime_context)
    run.add_event('run.created', '智能任务已创建', {'channel': channel, 'source': str(source or '').strip()})
    run.add_event('planner.started', '正在生成执行计划', {'channel': channel, 'source': str(source or '').strip()})
    return _facade().get_agent_run_repository().save(run)
