# ruff: noqa
# mypy: ignore-errors
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.fastapi_routes.knowledge_v1')

def _ensure_bounded_metadata(value: _facade().Any, *, max_bytes: int=_facade()._DATASET_METADATA_MAX_BYTES) -> None:

    def walk(item: _facade().Any, depth: int=0) -> None:
        if depth > 8:
            raise ValueError('metadata nesting exceeds 8 levels')
        if isinstance(item, dict):
            if len(item) > 200:
                raise ValueError('metadata has too many fields')
            for (key, child) in item.items():
                if len(str(key)) > 200:
                    raise ValueError('metadata key is too long')
                walk(child, depth + 1)
        elif isinstance(item, (list, tuple)):
            if len(item) > 1000:
                raise ValueError('metadata list is too long')
            for child in item:
                walk(child, depth + 1)
    walk(value)
    try:
        encoded = _facade().json.dumps(value, ensure_ascii=False, separators=(',', ':'), default=str).encode('utf-8')
    except (TypeError, ValueError) as exc:
        raise ValueError('metadata must be JSON serializable') from exc
    if len(encoded) > max_bytes:
        raise ValueError(f'metadata cannot exceed {max_bytes} bytes')

def _public_dataset_payload(value: _facade().Any) -> _facade().Any:
    """Remove local storage details from HTTP responses without changing service internals."""
    if isinstance(value, dict):
        return {str(key): _public_dataset_payload(item) for (key, item) in value.items() if not str(key).startswith('_') and str(key) not in {'storage_path', 'file_path', 'vector_index_path'}}
    if isinstance(value, list):
        return [_public_dataset_payload(item) for item in value]
    return value

class IngestRequest(_facade().BaseModel):
    text: str = _facade().Field(..., min_length=1, max_length=_facade()._DATASET_INLINE_MAX_CHARS, description='待入库文本')
    source: str = _facade().Field('default', max_length=300, description='来源标识')
    chunk_strategy: str = _facade().Field('semantic', pattern='^(semantic|fixed)$', description='semantic | fixed')
    chunk_size: int = _facade().Field(500, ge=50, le=5000)
    chunk_overlap: int = _facade().Field(50, ge=0, le=500)

    @_facade().model_validator(mode='after')
    def validate_chunk_window(self):
        if self.chunk_strategy == 'fixed' and self.chunk_overlap >= self.chunk_size:
            raise ValueError('chunk_overlap must be smaller than chunk_size')
        return self

class QueryRequest(_facade().BaseModel):
    query: str = _facade().Field(..., min_length=1, max_length=2000, description='查询文本')
    top_k: int = _facade().Field(5, ge=1, le=50)
    include_citations: bool = _facade().Field(True, description='是否返回 [1][2] 引用')

class IngestResponse(_facade().BaseModel):
    success: bool
    chunk_count: int
    source: str
    strategy: str
    message: str = ''

class QueryResponse(_facade().BaseModel):
    success: bool
    query: str
    chunks: list[dict[str, _facade().Any]]
    citations: list[dict[str, _facade().Any]] = []
    rag_enabled: bool

class StatusResponse(_facade().BaseModel):
    rag_enabled: bool
    embedder_available: bool
    indexed_sources: int
    indexed_chunks: int
    dataset_count: int = 0
    dataset_document_count: int = 0
    dataset_chunk_count: int = 0
    semantic_embedding_available: bool = False
    recommended_dataset_id: str = _facade()._PERSY_DATASET_ID

class DatasetDocumentIngestRequest(_facade().BaseModel):
    text: str = _facade().Field('', max_length=_facade()._DATASET_INLINE_MAX_CHARS, description='inline document text')
    file_path: str = _facade().Field('', max_length=4096, description='allowed local file path')
    source: str = _facade().Field('', max_length=300, description='source label')
    document_id: str = _facade().Field('', max_length=200, description='optional stable document id')
    tenant_id: str = _facade().Field('', max_length=160, description='tenant/user isolation key')
    version: str = _facade().Field('', max_length=80, description='document version number, vN, or empty for auto increment')
    version_label: str = _facade().Field('', max_length=120, description='optional display version label')
    chunk_strategy: str = _facade().Field('semantic', pattern='^(semantic|fixed)$', description='semantic | fixed')
    chunk_size: int = _facade().Field(500, ge=50, le=5000)
    chunk_overlap: int = _facade().Field(50, ge=0, le=500)
    metadata: dict[str, _facade().Any] = _facade().Field(default_factory=dict)

    @_facade().field_validator('metadata')
    @classmethod
    def validate_metadata(cls, value: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
        _facade()._ensure_bounded_metadata(value)
        return value

    @_facade().model_validator(mode='after')
    def validate_document_input(self):
        if not self.text.strip() and (not self.file_path.strip()):
            raise ValueError('text or file_path is required')
        if self.chunk_strategy == 'fixed' and self.chunk_overlap >= self.chunk_size:
            raise ValueError('chunk_overlap must be smaller than chunk_size')
        return self

class DatasetQueryRequest(_facade().BaseModel):
    query: str = _facade().Field(..., min_length=1, max_length=2000, description='question or retrieval query')
    top_k: int = _facade().Field(5, ge=1, le=50)
    include_answer: bool = _facade().Field(True, description='return deterministic answer with citations')
    tenant_id: str = _facade().Field('', max_length=160, description='tenant/user isolation key')
    version: str = _facade().Field('', max_length=80, description='document version number, vN, latest, or empty')
    metadata_filter: dict[str, _facade().Any] = _facade().Field(default_factory=dict)
    rerank: bool = _facade().Field(False, description='apply cross-encoder reranking with safe fallback')

    @_facade().field_validator('metadata_filter')
    @classmethod
    def validate_metadata_filter(cls, value: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
        _facade()._ensure_bounded_metadata(value)
        return value

class DatasetVersionDiffRequest(_facade().BaseModel):
    source: str = _facade().Field(..., min_length=1, max_length=300, description='document source label')
    tenant_id: str = _facade().Field('', max_length=160, description='tenant/user isolation key')
    from_version: str = _facade().Field(..., min_length=1, max_length=120, description='source version number, vN, or label')
    to_version: str = _facade().Field('latest', max_length=120, description='target version number, vN, label, or latest')

class DatasetRollbackRequest(_facade().BaseModel):
    source: str = _facade().Field(..., min_length=1, max_length=300, description='document source label')
    tenant_id: str = _facade().Field('', max_length=160, description='tenant/user isolation key')
    target_version: str = _facade().Field(..., min_length=1, max_length=120, description='version to restore into a new latest version')
    metadata: dict[str, _facade().Any] = _facade().Field(default_factory=dict)

    @_facade().field_validator('metadata')
    @classmethod
    def validate_metadata(cls, value: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
        _facade()._ensure_bounded_metadata(value)
        return value

class DatasetRebuildRequest(_facade().BaseModel):
    tenant_id: str = _facade().Field('', max_length=160, description='tenant/user isolation key')
    metadata_filter: dict[str, _facade().Any] = _facade().Field(default_factory=dict)
    background: bool = _facade().Field(True, description='run index rebuild in a background thread')
    max_attempts: int = _facade().Field(1, ge=1, le=5)

    @_facade().field_validator('metadata_filter')
    @classmethod
    def validate_metadata_filter(cls, value: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
        _facade()._ensure_bounded_metadata(value)
        return value

class PersyMemoryQueryRequest(_facade().BaseModel):
    query: str = _facade().Field(..., min_length=1, max_length=2000)
    top_k: int = _facade().Field(5, ge=1, le=20)
    reinforce: bool = _facade().Field(True)

class PersyMemoryMutationRequest(_facade().BaseModel):
    key: str | None = _facade().Field(None, max_length=160)
    value: _facade().Any = None
    memory_type: str | None = _facade().Field(None, max_length=32)
    confidence: float | None = _facade().Field(None, ge=0, le=1)
    reason: str = _facade().Field('', max_length=500)

    @_facade().field_validator('value')
    @classmethod
    def validate_value(cls, value: _facade().Any) -> _facade().Any:
        if value is not None:
            _facade()._ensure_bounded_metadata(value, max_bytes=16 * 1024)
        return value

class _KnowledgeIndex:
    """进程内单例：保存所有 chunk + 检索器。"""

    def __init__(self) -> None:
        self._lock = _facade().threading.Lock()
        self._chunker = _facade().SemanticChunker(embedder=_facade().get_default_embedder())
        self._retriever = _facade().HybridRetriever(embedder=_facade().get_default_embedder())
        self._chunks: list[_facade().RetrievedChunk] = []
        self._sources: set[str] = set()
        self._rebuild_needed: bool = True

    def ingest(self, text: str, source: str, strategy: str, chunk_size: int, chunk_overlap: int) -> int:
        with self._lock:
            if strategy == 'semantic':
                chunks = self._chunker.split_by_semantic(text)
            else:
                chunks = self._chunker.split_by_fixed(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
            base = len(self._chunks)
            for (i, c) in enumerate(chunks):
                self._chunks.append(_facade().RetrievedChunk(text=c.text, score=0.0, source=source, chunk_index=base + i, char_start=c.char_start, char_end=c.char_end, metadata={'source': source, 'strategy': c.strategy}))
            self._sources.add(source)
            self._rebuild_needed = True
            return len(chunks)

    def query(self, q: str, top_k: int) -> list[_facade().RetrievedChunk]:
        with self._lock:
            if self._rebuild_needed:
                self._retriever.index(self._chunks)
                self._rebuild_needed = False
            return _facade().cast('list[Any]', self._retriever.retrieve(q))

    def status(self) -> dict[str, int]:
        with self._lock:
            return {'sources': len(self._sources), 'chunks': len(self._chunks)}

def _dataset_access_context_from_request(request: _facade().Request) -> _facade().Any | None:
    from app.fastapi_routes.dataset_access import dataset_access_context_from_request
    return dataset_access_context_from_request(request)

def _dataset_access_payload_from_request(request: _facade().Request) -> dict[str, _facade().Any]:
    from app.fastapi_routes.dataset_access import dataset_access_payload_from_request
    return dataset_access_payload_from_request(request)

def _dataset_read_tenant_scope(access: _facade().Any | None) -> str:
    """Tenant filter for per-dataset status/graph reads.

    Omniscient overview counts all tenants inside each dataset for admins. Per-dataset
    status/graph must use the same scope; otherwise admin console shows e.g. 1013 docs
    in the strip while the active space graph stays empty (filtered by admin's
    synthetic ``platform`` tenant).
    """
    if access is None:
        return ''
    if bool(getattr(access, 'is_admin', False)):
        return ''
    permissions = getattr(access, 'permissions', None) or ()
    try:
        from app.application.dataset_rag_app_service import DATASET_ADMIN_PERMISSION
        if DATASET_ADMIN_PERMISSION in permissions:
            return ''
    except _facade().RECOVERABLE_ERRORS:
        pass
    return str(getattr(access, 'tenant_id', '') or '')

def _persy_memory_service():
    from app.application.persy_memory_app_service import get_persy_memory_app_service
    return get_persy_memory_app_service()

def _persy_dataset_error(dataset_id: str) -> _facade().JSONResponse | None:
    if str(dataset_id or '').strip() == _facade()._PERSY_DATASET_ID:
        return None
    return _facade().JSONResponse({'success': False, 'message': 'Persy memory is only available for the Persy knowledge dataset', 'error_code': 'persy_dataset_required'}, status_code=404)

def _persy_memory_response(payload: dict[str, _facade().Any], *, request: _facade().Request, action: str) -> _facade().JSONResponse:
    success = bool(payload.get('success'))
    code = str(payload.get('error_code') or '')
    status_code = 200 if success else 400
    if code in {'dataset_permission_denied', 'persy_memory_scope_missing'}:
        status_code = 403
    elif code == 'persy_memory_not_found':
        status_code = 404
    try:
        from app.utils.logging import audit_logger
        access = _facade()._dataset_access_context_from_request(request)
        audit_logger.audit_log(f'persy_memory_{action}', getattr(access, 'actor_id', '') if access is not None else '', str(getattr(getattr(request, 'client', None), 'host', '') or ''), {'success': success, 'memory_id': str((payload.get('memory') or {}).get('memory_id') if isinstance(payload.get('memory'), dict) else ''), 'error_code': code}, success=success)
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.debug('Persy memory audit unavailable', exc_info=True)
    return _facade().JSONResponse(payload, status_code=status_code)

def _merge_persy_recall(payload: dict[str, _facade().Any], *, request: _facade().Request, params: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    if str(params.get('dataset_id') or '') != _facade()._PERSY_DATASET_ID or not payload.get('success'):
        return payload
    query_text = str(params.get('query') or '').strip()
    if not query_text:
        return payload
    memory_result = _facade()._persy_memory_service().query(access_context=_facade()._dataset_access_context_from_request(request), query=query_text, top_k=max(1, min(int(params.get('top_k') or 5), 20)), reinforce=True)
    result = dict(payload)
    result['persy_memory'] = {'available': bool(memory_result.get('success')), 'count': len(memory_result.get('chunks') or []), 'retriever': str(memory_result.get('retriever') or '')}
    if not memory_result.get('success'):
        result['persy_memory']['error_code'] = str(memory_result.get('error_code') or '')
        return result
    knowledge_chunks = [dict(chunk) for chunk in payload.get('chunks', []) if isinstance(chunk, dict)]
    memory_chunks = [dict(chunk) for chunk in memory_result.get('chunks', []) if isinstance(chunk, dict)]
    seen: set[str] = set()
    merged_chunks: list[dict[str, _facade().Any]] = []
    for chunk in sorted([*memory_chunks, *knowledge_chunks], key=lambda item: float(item.get('score') or 0.0), reverse=True):
        metadata = chunk.get('metadata') if isinstance(chunk.get('metadata'), dict) else {}
        if not isinstance(metadata, dict):
            metadata = {}
        fingerprint = str(metadata.get('memory_id') or metadata.get('document_id') or f"{chunk.get('source')}:{chunk.get('chunk_index')}:{chunk.get('text')}")
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        merged_chunks.append(chunk)
    result['chunks'] = merged_chunks[:max(2, min(int(params.get('top_k') or 5) * 2, 40))]
    citations = [dict(citation) for citation in payload.get('citations', []) if isinstance(citation, dict)]
    for chunk in memory_chunks:
        memory_metadata = chunk.get('metadata') if isinstance(chunk.get('metadata'), dict) else {}
        if not isinstance(memory_metadata, dict):
            memory_metadata = {}
        citations.append({'index': len(citations) + 1, 'source': '对话记忆', 'text': str(chunk.get('text') or ''), 'score': chunk.get('score'), 'memory_id': memory_metadata.get('memory_id')})
    result['citations'] = citations
    if memory_chunks and params.get('include_answer', True):
        memory_summary = '；'.join((str(chunk.get('text') or '').strip()[:180] for chunk in memory_chunks[:3] if str(chunk.get('text') or '').strip()))
        knowledge_answer = str(payload.get('answer') or '').strip()
        memory_answer = f'已确认的长期记忆：{memory_summary}。' if memory_summary else ''
        result['answer'] = '\n\n'.join((part for part in (memory_answer, knowledge_answer) if part))
    return result

def _agent_node_output(run: _facade().Any, node_id: str) -> dict[str, _facade().Any]:
    final_output = getattr(run, 'final_output', None)
    node_outputs = dict((final_output or {}).get('node_outputs') or {})
    output = dict(node_outputs.get(node_id) or {})
    if not output:
        for step in getattr(run, 'steps', []) or []:
            if str(getattr(step, 'node_id', '')) == node_id:
                output = dict(getattr(step, 'output', {}) or {})
                break
    if not output:
        output = {'success': getattr(run, 'status', '') == 'completed'}
    if not output.get('success') and getattr(run, 'error', False) and (not output.get('message')):
        output['message'] = getattr(run, 'error', False)
    run_id = str(getattr(run, 'run_id', '') or '')
    if run_id:
        output['run_id'] = run_id
        output['agent_run_id'] = run_id
    output['agent_status'] = str(getattr(run, 'status', '') or '')
    return _facade().cast('dict[str, Any]', _facade()._public_dataset_payload(output))

def _dataset_agent_user_id(request: _facade().Request, params: dict[str, _facade().Any]) -> str:
    access_context = params.get('access_context') if isinstance(params.get('access_context'), dict) else {}
    if not isinstance(access_context, dict):
        access_context = {}
    return str(request.headers.get('X-User-Id') or request.headers.get('X-User-ID') or access_context.get('actor_id') or params.get('actor_id') or params.get('user_id') or params.get('tenant_id') or 'dataset-rag-route').strip()

def _run_dataset_rag_agent(*, request: _facade().Request, action: str, params: dict[str, _facade().Any], route_path: str) -> _facade().JSONResponse:
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.workflow.types import PlanGraph, WorkflowNode
    from app.application.workflow_registry_app import get_workflow_tool_registry
    data = dict(params or {})
    access_payload = _facade()._dataset_access_payload_from_request(request)
    if access_payload:
        data['access_context'] = access_payload
        if access_payload.get('tenant_id'):
            if not str(data.get('tenant_id') or '').strip():
                data['tenant_id'] = access_payload['tenant_id']
    registry = get_workflow_tool_registry()
    action_meta = dict((registry.get('dataset_rag') or {}).get('actions') or {}).get(action)
    if not isinstance(action_meta, dict):
        return _facade().JSONResponse({'success': False, 'message': f'未注册的 Dataset/RAG 动作: {action}'}, status_code=400)
    node_id = f'dataset_rag_{action}'
    plan = PlanGraph(plan_id=node_id, intent=node_id, todo_steps=[f'通过 AgentOrchestrator 执行 dataset_rag.{action}'], nodes=[WorkflowNode(node_id=node_id, tool_id='dataset_rag', action=action, params=data, risk=_facade().normalize_workflow_risk(str(action_meta.get('risk') or 'medium')), idempotent=bool(action_meta.get('idempotent', False)), description=f'Execute dataset_rag.{action} through the unified Agent runtime.')], risk_level=_facade().normalize_workflow_risk(str(action_meta.get('risk') or 'medium')), metadata={'source': 'dataset_rag_route', 'route': route_path})
    user_id = _facade()._dataset_agent_user_id(request, data)
    runtime_context = {'source': 'dataset_rag_route', 'route': route_path, 'request_path': str(request.url.path), 'user_id': user_id, 'route_confirmed': True}
    if access_payload:
        runtime_context['dataset_access_context'] = access_payload
        if access_payload.get('tenant_id'):
            runtime_context['dataset_tenant_id'] = access_payload['tenant_id']
        runtime_context['dataset_permissions'] = list(access_payload.get('permissions') or [])
        runtime_context['dataset_admin'] = bool(access_payload.get('is_admin'))
    orchestrator = AgentOrchestrator()
    run = orchestrator.start_run_from_plan(user_id=user_id, message=str(data.get('message') or f'Dataset/RAG {action}'), plan=plan, runtime_context=runtime_context)
    if run.status in {'waiting_user', 'running'}:
        continued = orchestrator.continue_run(run.run_id, approved_by=user_id or 'dataset-rag-route', approved_step_id=node_id, runtime_context=runtime_context)
        if continued is not None:
            run = continued
    payload = _facade()._agent_node_output(run, node_id)
    if action == 'query':
        payload = _facade()._merge_persy_recall(payload, request=request, params=data)
    if run.status in {'waiting_user', 'blocked'}:
        status_code = 202
    elif payload.get('error_code') == 'tool_exception':
        status_code = 500
    else:
        status_code = 200
    return _facade().JSONResponse(payload, status_code=status_code)

def _mirror_ingest_to_persy(*, text: str, source: str, chunk_strategy: str, chunk_size: int, chunk_overlap: int, request: _facade().Request | None=None) -> dict[str, _facade().Any]:
    """Dual-write legacy /ingest into governed persy-knowledge dataset."""
    try:
        from app.application.dataset_rag_app_service import get_dataset_rag_app_service
        access = _facade()._dataset_access_context_from_request(request) if request is not None else None
        return _facade().cast('dict[str, Any]', get_dataset_rag_app_service().ingest_document(dataset_id=_facade()._PERSY_DATASET_ID, source=source or 'legacy-ingest', text=text, chunk_strategy=chunk_strategy, chunk_size=chunk_size, chunk_overlap=chunk_overlap, metadata={'entrypoint': 'legacy_ingest_mirror'}, access_context=access))
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('mirror ingest to persy-knowledge failed: %s', exc)
        return {'success': False, 'message': str(exc)}
