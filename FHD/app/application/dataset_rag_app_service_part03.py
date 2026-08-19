# ruff: noqa
# mypy: ignore-errors
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.application.dataset_rag_app_service')

class DatasetRagApplicationService(_facade()._DatasetRagApplicationServicePart01Mixin, _facade()._DatasetRagApplicationServicePart02Mixin):
    """Minimal in-process dataset lifecycle for document RAG and citation QA."""

def _default_storage_path() -> _facade().Path:
    configured = (_facade().os.environ.get('DATASET_RAG_STORE_PATH') or _facade().os.environ.get('XCAGI_DATASET_RAG_STORE_PATH') or '').strip()
    if configured:
        return _facade().Path(configured).expanduser().resolve()
    return _facade().Path(_facade().get_app_data_dir()).resolve() / 'dataset_rag' / 'datasets.json'

def _build_dataset_vector_index_backend(*, backend_name: str | None, storage_path: _facade().Path, vector_index_path: str | _facade().Path | None) -> _facade().DatasetVectorIndexBackend | None:
    configured = backend_name if backend_name is not None else _facade().os.environ.get('DATASET_RAG_VECTOR_BACKEND') or _facade().os.environ.get('XCAGI_DATASET_RAG_VECTOR_BACKEND') or 'sqlite'
    name = str(configured or '').strip().lower()
    if name in {'', 'none', 'disabled', 'off', 'json', 'memory'}:
        return None
    if name in {'sqlite', 'sqlite_vector'}:
        path = _facade().Path(vector_index_path).expanduser().resolve() if vector_index_path is not None else _facade().default_dataset_vector_index_path(storage_path)
        return _facade().DatasetVectorSQLiteIndex(path)
    if name in {'pgvector', 'postgres', 'postgresql'}:
        database_url = (_facade().os.environ.get('DATASET_RAG_PGVECTOR_DATABASE_URL') or _facade().os.environ.get('XCAGI_DATASET_RAG_PGVECTOR_DATABASE_URL') or _facade().os.environ.get('PGVECTOR_DATABASE_URL') or _facade().os.environ.get('DATABASE_URL') or '').strip()
        dimension_raw = _facade().os.environ.get('DATASET_RAG_PGVECTOR_DIMENSION') or _facade().os.environ.get('XCAGI_DATASET_RAG_PGVECTOR_DIMENSION') or '256'
        try:
            dimension = int(dimension_raw)
        except (TypeError, ValueError):
            dimension = 256
        return _facade().DatasetVectorPgIndex(database_url, dimension=dimension)
    raise ValueError(f'unsupported dataset vector backend: {configured}')

def _resolve_max_concurrent_rebuild_jobs(configured: int | None) -> int:
    if configured is not None:
        return max(1, min(int(configured), 8))
    raw = _facade().os.environ.get('DATASET_RAG_REBUILD_MAX_CONCURRENT', '').strip()
    if not raw:
        raw = _facade().os.environ.get('XCAGI_DATASET_RAG_REBUILD_MAX_CONCURRENT', '').strip()
    if raw.isdigit():
        return max(1, min(int(raw), 8))
    return 1

def _empty_rebuild_queue_summary(max_concurrent_jobs: int, *, worker_enabled: bool) -> dict[str, _facade().Any]:
    return {'max_concurrent_jobs': max_concurrent_jobs, 'worker_enabled': worker_enabled, 'queued': 0, 'running': 0, 'completed': 0, 'failed': 0, 'cancelled': 0, 'next_job_id': '', 'running_job_ids': []}

def _clean_key(value: str, *, default: str) -> str:
    cleaned = ''.join((ch if ch.isalnum() or ch in {'-', '_', '.'} else '_' for ch in value.strip()))
    return cleaned.strip('._-') or default

def _coerce_access_context(value: _facade().DatasetAccessContext | dict[str, _facade().Any] | None) -> _facade().DatasetAccessContext | None:
    if value is None:
        return None
    if isinstance(value, _facade().DatasetAccessContext):
        return value
    permissions_value = value.get('permissions') if isinstance(value, dict) else None
    if isinstance(permissions_value, str):
        permissions = frozenset((part.strip() for part in permissions_value.replace(';', ',').split(',') if part.strip()))
    elif isinstance(permissions_value, (list, tuple, set, frozenset)):
        permissions = frozenset((str(part).strip() for part in permissions_value if str(part).strip()))
    else:
        permissions = frozenset()
    return _facade().DatasetAccessContext(actor_id=str(value.get('actor_id') or value.get('user_id') or ''), tenant_id=_facade()._clean_key(str(value.get('tenant_id') or ''), default='') if value.get('tenant_id') else '', permissions=permissions, is_admin=bool(value.get('is_admin') or value.get('admin')))

def _has_dataset_permission(context: _facade().DatasetAccessContext | None, permission: str) -> bool:
    if context is None:
        return True
    if context.is_admin or _facade().DATASET_ADMIN_PERMISSION in context.permissions:
        return True
    if permission in context.permissions:
        return True
    prefix = permission.split('.', 1)[0]
    return f'{prefix}.*' in context.permissions or '*' in context.permissions

def _dataset_permission_denied(*, dataset_id: str, permission: str, message: str, context: _facade().DatasetAccessContext | None) -> dict[str, _facade().Any]:
    return {'success': False, 'dataset_id': dataset_id, 'error_code': 'dataset_permission_denied', 'message': message, 'required_permission': permission, 'access': context.to_dict() if context is not None else {}}

def _ensure_dataset_permission(context: _facade().DatasetAccessContext | None, permission: str, *, dataset_id: str) -> dict[str, _facade().Any] | None:
    if _facade()._has_dataset_permission(context, permission):
        return None
    return _facade()._dataset_permission_denied(dataset_id=dataset_id, permission=permission, message=f'{permission} permission is required', context=context)

def _ensure_tenant_allowed(context: _facade().DatasetAccessContext | None, tenant_id: str, *, dataset_id: str, operation: str) -> dict[str, _facade().Any] | None:
    if context is None or context.is_admin or _facade().DATASET_ADMIN_PERMISSION in context.permissions:
        return None
    actor_tenant = _facade()._clean_key(context.tenant_id, default='') if context.tenant_id else ''
    target_tenant = _facade()._clean_key(str(tenant_id or ''), default='') if tenant_id else ''
    if not actor_tenant:
        return _facade()._dataset_permission_denied(dataset_id=dataset_id, permission=_facade().DATASET_READ_PERMISSION, message=f'{operation} requires an actor tenant context', context=context)
    if not target_tenant:
        return _facade()._dataset_permission_denied(dataset_id=dataset_id, permission=_facade().DATASET_ADMIN_PERMISSION, message=f'{operation} across all tenants requires dataset admin', context=context)
    if actor_tenant != target_tenant:
        return _facade()._dataset_permission_denied(dataset_id=dataset_id, permission=_facade().DATASET_ADMIN_PERMISSION, message=f'{operation} cannot access tenant {target_tenant}', context=context)
    return None

def _resolve_tenant_for_access(access_context: _facade().DatasetAccessContext | dict[str, _facade().Any] | None, requested_tenant_id: str, *, required_permission: str, default_without_context: str, dataset_id: str) -> tuple[str, dict[str, _facade().Any] | None]:
    context = _facade()._coerce_access_context(access_context)
    denied = _facade()._ensure_dataset_permission(context, required_permission, dataset_id=dataset_id)
    if denied is not None:
        return ('', denied)
    requested = _facade()._clean_key(str(requested_tenant_id or ''), default='') if requested_tenant_id else ''
    if context is None:
        if requested:
            return (requested, None)
        return (_facade()._clean_key(str(default_without_context), default=default_without_context) if default_without_context else '', None)
    if context.is_admin or _facade().DATASET_ADMIN_PERMISSION in context.permissions:
        if requested:
            return (requested, None)
        return (_facade()._clean_key(str(default_without_context), default=default_without_context) if default_without_context else '', None)
    actor_tenant = _facade()._clean_key(context.tenant_id, default='') if context.tenant_id else ''
    if not actor_tenant:
        return ('', _facade()._dataset_permission_denied(dataset_id=dataset_id, permission=required_permission, message='dataset tenant context is required', context=context))
    if requested and requested != actor_tenant:
        return ('', _facade()._dataset_permission_denied(dataset_id=dataset_id, permission=_facade().DATASET_ADMIN_PERMISSION, message=f'tenant {requested} is outside requester scope', context=context))
    return (actor_tenant, None)

def _stable_document_id(dataset_id: str, tenant_id: str, source: str, version: int, text: str) -> str:
    digest = _facade().hashlib.sha256(f'{dataset_id}\x00{tenant_id}\x00{source}\x00{version}\x00{text}'.encode()).hexdigest()
    return f'doc_{digest[:16]}'

def _document_from_dict(data: dict[str, _facade().Any]) -> _facade().DatasetDocument:
    metadata = dict(data.get('metadata') or {})
    version = int(data.get('version') or metadata.get('document_version') or 1)
    return _facade().DatasetDocument(document_id=str(data.get('document_id') or ''), source=str(data.get('source') or ''), parser=str(data.get('parser') or ''), text_length=int(data.get('text_length') or 0), chunk_count=int(data.get('chunk_count') or 0), tenant_id=_facade()._clean_key(str(data.get('tenant_id') or metadata.get('tenant_id') or 'default'), default='default'), version=version, version_label=str(data.get('version_label') or metadata.get('version_label') or f'v{version}'), metadata=metadata)

def _rebuild_job_from_dict(data: dict[str, _facade().Any]) -> _facade().DatasetRebuildJob:
    created_at = str(data.get('created_at') or _facade()._utc_now_iso())
    queued_at = str(data.get('queued_at') or created_at)
    return _facade().DatasetRebuildJob(job_id=str(data.get('job_id') or ''), dataset_id=str(data.get('dataset_id') or ''), status=str(data.get('status') or 'queued'), tenant_id=str(data.get('tenant_id') or ''), metadata_filter=dict(data.get('metadata_filter') or {}), document_count=int(data.get('document_count') or 0), chunk_count=int(data.get('chunk_count') or 0), error=str(data.get('error') or ''), attempt_count=int(data.get('attempt_count') or 0), max_attempts=max(1, int(data.get('max_attempts') or 1)), worker_id=str(data.get('worker_id') or ''), created_at=created_at, queued_at=queued_at, started_at=str(data.get('started_at') or ''), completed_at=str(data.get('completed_at') or ''), cancelled_at=str(data.get('cancelled_at') or ''), updated_at=str(data.get('updated_at') or queued_at))

def _chunk_to_dict(chunk: _facade().RetrievedChunk, *, public: bool=False) -> dict[str, _facade().Any]:
    metadata = dict(chunk.metadata or {})
    if public:
        metadata = {key: value for (key, value) in metadata.items() if not str(key).startswith('_')}
    return {'text': chunk.text, 'score': chunk.score, 'source': chunk.source, 'chunk_index': chunk.chunk_index, 'char_start': chunk.char_start, 'char_end': chunk.char_end, 'metadata': metadata, 'source_url': chunk.source_url, 'page': chunk.page}

def _dict_to_retrieved_chunk(data: dict[str, _facade().Any]) -> _facade().RetrievedChunk:
    return _facade().RetrievedChunk(text=str(data.get('text') or ''), score=float(data.get('score') or 0.0), source=str(data.get('source') or ''), chunk_index=int(data.get('chunk_index') or 0), char_start=int(data.get('char_start') or 0), char_end=int(data.get('char_end') or 0), metadata=dict(data.get('metadata') or {}), source_url=str(data.get('source_url') or ''), page=data.get('page') if isinstance(data.get('page'), int) else None)

def _citation_to_dict(citation: _facade().Citation) -> dict[str, _facade().Any]:
    return {'index': citation.index, 'text': citation.text, 'source': citation.source, 'chunk_index': citation.chunk_index, 'char_range': list(citation.char_range), 'source_url': citation.source_url, 'page': citation.page}

def _deterministic_answer(query: str, chunks: list[_facade().RetrievedChunk]) -> str:
    if not chunks:
        return ''
    excerpt = chunks[0].text.strip().replace('\n', ' ')
    if len(excerpt) > 320:
        excerpt = excerpt[:317].rstrip() + '...'
    prefix = f'Based on the retrieved dataset evidence for {query!r}: ' if query else ''
    return f'{prefix}{excerpt} [1]'
