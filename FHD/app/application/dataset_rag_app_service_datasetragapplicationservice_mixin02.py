# ruff: noqa
# mypy: ignore-errors
"""Behavior mixin extracted from the public facade class."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.application.dataset_rag_app_service')

class _DatasetRagApplicationServicePart02Mixin:

    def _extract_xls_text(self, path: _facade().Path) -> tuple[str, str, dict[str, _facade().Any]]:
        try:
            import xlrd
        except ImportError as exc:
            raise RuntimeError('xlrd is required to ingest XLS documents') from exc
        max_rows_per_sheet = 5000
        max_cols = 100
        parts: list[str] = []
        sheet_count = 0
        row_count = 0
        book = xlrd.open_workbook(str(path))
        for sheet in book.sheets():
            sheet_count += 1
            sheet_lines: list[str] = []
            nrows = min(int(sheet.nrows), max_rows_per_sheet)
            for row_index in range(nrows):
                cells: list[str] = []
                ncols = min(int(sheet.ncols), max_cols)
                for col_index in range(ncols):
                    value = sheet.cell_value(row_index, col_index)
                    if value is None or value == '':
                        continue
                    text = str(value).strip()
                    if text:
                        cells.append(text)
                if cells:
                    sheet_lines.append('\t'.join(cells))
                    row_count += 1
            if int(sheet.nrows) > max_rows_per_sheet:
                sheet_lines.append(f'... truncated after {max_rows_per_sheet} rows')
            if sheet_lines:
                parts.append(f'[sheet {sheet.name}]\n' + '\n'.join(sheet_lines))
        return ('\n\n'.join(parts), 'xlrd', {'extension': '.xls', 'sheet_count': sheet_count, 'row_count': row_count})

    def _split_text(self, text: str, *, strategy: str, chunk_size: int, chunk_overlap: int):
        if strategy == 'semantic':
            return self._chunker.split_by_semantic(text)
        return self._chunker.split_by_fixed(text, chunk_size=max(50, min(int(chunk_size), 5000)), chunk_overlap=max(0, min(int(chunk_overlap), 500)))

    def _load_persisted_state(self) -> None:
        try:
            if not self._storage_path.exists():
                return
            raw = _facade().json.loads(self._storage_path.read_text(encoding='utf-8'))
            datasets = raw.get('datasets') if isinstance(raw, dict) else {}
            if not isinstance(datasets, dict):
                return
            loaded: dict[str, _facade()._DatasetState] = {}
            for (dataset_id, payload) in datasets.items():
                if not isinstance(payload, dict):
                    continue
                documents_payload = payload.get('documents')
                chunks_payload = payload.get('chunks')
                jobs_payload = payload.get('rebuild_jobs')
                documents = {str(doc_id): _facade()._document_from_dict(row) for (doc_id, row) in (documents_payload or {}).items() if isinstance(row, dict)} if isinstance(documents_payload, dict) else {}
                chunks = [_facade()._dict_to_retrieved_chunk(row) for row in chunks_payload or [] if isinstance(row, dict)] if isinstance(chunks_payload, list) else []
                index_payload = payload.get('index')
                state = _facade()._DatasetState(str(dataset_id), documents=documents, chunks=chunks, index=dict(index_payload or {}) if isinstance(index_payload, dict) else {}, rebuild_jobs={str(job_id): _facade()._rebuild_job_from_dict(row) for (job_id, row) in (jobs_payload or {}).items() if isinstance(row, dict)} if isinstance(jobs_payload, dict) else {})
                self._recover_rebuild_jobs_locked(state)
                self._renumber_chunks(state)
                self._sync_vector_index_locked(state)
                self._refresh_index_metadata(state)
                loaded[str(dataset_id)] = state
            self._datasets = loaded
        except _facade().RECOVERABLE_ERRORS:
            self._datasets = {}

    def _persist_locked(self) -> None:
        payload = {'version': 1, 'datasets': {dataset_id: {'dataset_id': state.dataset_id, 'documents': {doc_id: doc.to_dict() for (doc_id, doc) in sorted(state.documents.items())}, 'chunks': [_facade()._chunk_to_dict(chunk) for chunk in state.chunks], 'index': dict(state.index or {}), 'rebuild_jobs': {job_id: job.to_dict() for (job_id, job) in sorted(state.rebuild_jobs.items())}} for (dataset_id, state) in sorted(self._datasets.items())}}
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._storage_path.with_suffix(self._storage_path.suffix + '.tmp')
        tmp_path.write_text(_facade().json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp_path.replace(self._storage_path)

    @staticmethod
    def _renumber_chunks(state: _facade()._DatasetState) -> None:
        for (index, chunk) in enumerate(state.chunks):
            chunk.chunk_index = index

    @staticmethod
    def _resolve_document_version(state: _facade()._DatasetState, *, source: str, tenant_id: str, requested: int | str | None) -> int:
        text = str(requested or '').strip()
        if text:
            if text.lower().startswith('v') and text[1:].isdigit():
                return max(1, int(text[1:]))
            if text.isdigit():
                return max(1, int(text))
            raise ValueError('version must be an integer, vN, or empty')
        versions = [int(doc.version or 1) for doc in state.documents.values() if doc.source == source and doc.tenant_id == tenant_id]
        return max(versions) + 1 if versions else 1

    @staticmethod
    def _resolve_document_for_version(state: _facade()._DatasetState, *, source: str, tenant_id: str, version: str | int) -> _facade().DatasetDocument | None:
        candidates = [doc for doc in state.documents.values() if doc.source == source and doc.tenant_id == tenant_id]
        if not candidates:
            return None
        version_text = str(version or '').strip()
        if not version_text or version_text.lower() == 'latest':
            return max(candidates, key=lambda doc: int(doc.version or 1))
        normalized = version_text[1:] if version_text.lower().startswith('v') else version_text
        for doc in candidates:
            if str(doc.version) == normalized or doc.version_label == version_text:
                return doc
        return None

    @staticmethod
    def _document_text_locked(state: _facade()._DatasetState, document_id: str) -> str:
        chunks = [chunk for chunk in state.chunks if isinstance(chunk.metadata, dict) and str(chunk.metadata.get('document_id') or '') == document_id]
        chunks.sort(key=lambda item: (item.char_start, item.chunk_index))
        return '\n'.join((chunk.text for chunk in chunks if chunk.text))

    def _schedule_rebuild_jobs(self) -> None:
        if not self._rebuild_workers_enabled:
            return
        with self._lock:
            starts = self._claim_next_rebuild_jobs_locked()
            if starts:
                self._persist_locked()
        self._start_rebuild_threads(starts)

    def _claim_next_rebuild_jobs_locked(self, *, limit: int | None=None) -> list[tuple[str, str]]:
        running = sum((1 for state in self._datasets.values() for job in state.rebuild_jobs.values() if job.status == 'running'))
        capacity = max(0, self._max_concurrent_rebuild_jobs - running)
        if limit is not None:
            capacity = min(capacity, max(0, int(limit)))
        if capacity <= 0:
            return []
        queued: list[tuple[str, _facade().DatasetRebuildJob]] = []
        for (dataset_id, state) in sorted(self._datasets.items()):
            for job in state.rebuild_jobs.values():
                if job.status == 'queued':
                    queued.append((dataset_id, job))
        queued.sort(key=lambda item: (item[1].queued_at or item[1].created_at, item[1].job_id))
        starts: list[tuple[str, str]] = []
        for (dataset_id, job) in queued[:capacity]:
            now = _facade()._utc_now_iso()
            job.status = 'running'
            job.started_at = now if not job.started_at else job.started_at
            job.updated_at = now
            job.attempt_count += 1
            job.worker_id = f'rag_worker_{_facade().uuid.uuid4().hex[:8]}'
            starts.append((dataset_id, job.job_id))
        return starts

    def _start_rebuild_threads(self, starts: list[tuple[str, str]]) -> None:
        for (dataset_id, job_id) in starts:
            thread = _facade().threading.Thread(target=self._run_rebuild_job, kwargs={'dataset_id': dataset_id, 'job_id': job_id, 'claimed': True}, daemon=True)
            thread.start()

    def _run_rebuild_job(self, dataset_id: str, job_id: str, *, claimed: bool=False, schedule_next: bool=True) -> None:
        with self._lock:
            state = self._datasets.get(dataset_id)
            job = state.rebuild_jobs.get(job_id) if state is not None else None
            if state is None or job is None:
                return
            if job.status in _facade().REBUILD_TERMINAL_STATUSES:
                return
            if not claimed:
                now = _facade()._utc_now_iso()
                job.status = 'running'
                job.started_at = now if not job.started_at else job.started_at
                job.updated_at = now
                job.attempt_count += 1
                job.worker_id = f'rag_worker_{_facade().uuid.uuid4().hex[:8]}'
                self._persist_locked()
        try:
            with self._lock:
                state = self._datasets.get(dataset_id)
                job = state.rebuild_jobs.get(job_id) if state is not None else None
                if state is None or job is None:
                    return
                matched_document_ids: set[str] = set()
                rebuilt_chunks = 0
                for chunk in state.chunks:
                    metadata = dict(chunk.metadata or {})
                    if job.tenant_id and str(metadata.get('tenant_id') or '') != job.tenant_id:
                        continue
                    if job.metadata_filter and (not _facade()._metadata_matches(chunk, job.metadata_filter)):
                        continue
                    metadata.pop('_embedding', None)
                    metadata.update(_facade()._embedding_metadata(self._embedder, chunk.text))
                    chunk.metadata = metadata
                    rebuilt_chunks += 1
                    document_id = str(metadata.get('document_id') or '')
                    if document_id:
                        matched_document_ids.add(document_id)
                self._renumber_chunks(state)
                self._sync_vector_index_locked(state)
                self._refresh_index_metadata(state)
                job.status = 'completed'
                job.document_count = len(matched_document_ids)
                job.chunk_count = rebuilt_chunks
                now = _facade()._utc_now_iso()
                job.completed_at = now
                job.updated_at = now
                self._persist_locked()
        except _facade().RECOVERABLE_ERRORS as exc:
            with self._lock:
                state = self._datasets.get(dataset_id)
                job = state.rebuild_jobs.get(job_id) if state is not None else None
                if job is not None:
                    now = _facade()._utc_now_iso()
                    if job.attempt_count < max(1, int(job.max_attempts or 1)):
                        job.status = 'queued'
                        job.queued_at = now
                    else:
                        job.status = 'failed'
                        job.completed_at = now
                    job.error = str(exc)
                    job.updated_at = now
                    self._persist_locked()
        finally:
            if schedule_next:
                self._schedule_rebuild_jobs()

    def _query_vector_index_candidates(self, *, dataset_id: str, query: str, top_k: int, tenant_id: str, version: str | int, metadata_filter: dict[str, _facade().Any]) -> list[_facade().RetrievedChunk] | None:
        if self._vector_index_backend is None or self._embedder is None:
            return None
        try:
            query_vector = self._embedder(query)
            if not isinstance(query_vector, list) or not query_vector:
                return None
            return self._vector_index_backend.query(dataset_id, [float(value) for value in query_vector], top_k=top_k, tenant_id=tenant_id, version=version, metadata_filter=metadata_filter)
        except _facade().RECOVERABLE_ERRORS:
            return None

    def _sync_vector_index_locked(self, state: _facade()._DatasetState) -> None:
        if self._vector_index_backend is None:
            state.index['vector_backend_sync_status'] = 'disabled'
            return
        try:
            count = self._vector_index_backend.replace_dataset(state.dataset_id, state.chunks)
            state.index['vector_backend_sync_status'] = 'synced'
            state.index['vector_backend_synced_chunks'] = count
            state.index['vector_backend_synced_at'] = _facade()._utc_now_iso()
        except _facade().RECOVERABLE_ERRORS as exc:
            state.index['vector_backend_sync_status'] = 'failed'
            state.index['vector_backend_error'] = str(exc)

    def _vector_index_backend_name(self) -> str:
        if self._vector_index_backend is None:
            return 'none'
        return str(getattr(self._vector_index_backend, 'backend_name', 'vector_index'))

    def _vector_index_status(self, dataset_id: str) -> dict[str, _facade().Any]:
        if self._vector_index_backend is None:
            return {'backend': 'none', 'persistent': False, 'dataset_id': dataset_id, 'chunk_count': 0, 'index_exists': False}
        try:
            return dict(self._vector_index_backend.status(dataset_id))
        except _facade().RECOVERABLE_ERRORS as exc:
            return {'backend': self._vector_index_backend_name(), 'persistent': True, 'dataset_id': dataset_id, 'chunk_count': 0, 'index_exists': False, 'status': 'failed', 'error': str(exc)}

    def _refresh_index_metadata(self, state: _facade()._DatasetState) -> None:
        embedding_count = sum((1 for chunk in state.chunks if isinstance(chunk.metadata, dict) and isinstance(chunk.metadata.get('_embedding'), list)))
        vector_status = self._vector_index_status(state.dataset_id)
        previous = dict(state.index or {})
        state.index = {'schema_version': 2, 'retriever': 'hybrid_bm25_vector', 'reranker': 'lexical_overlap_v1', 'document_count': len(state.documents), 'chunk_count': len(state.chunks), 'embedding_count': embedding_count, 'embedding_persisted': embedding_count > 0, 'vector_backend': vector_status, 'vector_backend_name': vector_status.get('backend', self._vector_index_backend_name()), 'vector_backend_chunk_count': int(vector_status.get('chunk_count') or 0), 'vector_backend_persistent': bool(vector_status.get('persistent')), 'vector_backend_sync_status': previous.get('vector_backend_sync_status', ''), 'vector_backend_synced_chunks': int(previous.get('vector_backend_synced_chunks') or 0), 'vector_backend_synced_at': str(previous.get('vector_backend_synced_at') or ''), 'vector_backend_error': str(previous.get('vector_backend_error') or ''), 'updated_at': _facade()._utc_now_iso()}

    def _status_for_state(self, dataset_id: str, state: _facade()._DatasetState | None, *, tenant_id_filter: str='', include_documents: bool=True) -> dict[str, _facade().Any]:
        if state is None:
            empty_index = {'semantic_embedding_available': _facade()._semantic_embedding_available(0), 'embedding_count': 0}
            return {'success': True, 'dataset_id': dataset_id, 'document_count': 0, 'chunk_count': 0, 'documents': [], 'tenant_ids': [], 'versions': [], 'index': empty_index, 'rebuild_jobs': [], 'rebuild_job_count': 0, 'rebuild_queue': _facade()._empty_rebuild_queue_summary(self._max_concurrent_rebuild_jobs, worker_enabled=self._rebuild_workers_enabled), 'storage_path': str(self._storage_path), 'persistent': True}
        documents = [doc for doc in state.documents.values() if not tenant_id_filter or doc.tenant_id == tenant_id_filter]
        chunks = [chunk for chunk in state.chunks if not tenant_id_filter or str((chunk.metadata or {}).get('tenant_id') or '') == tenant_id_filter]
        rebuild_job_records = [job for job in state.rebuild_jobs.values() if not tenant_id_filter or job.tenant_id == tenant_id_filter]
        embedding_count = sum((1 for chunk in chunks if isinstance(chunk.metadata, dict) and isinstance(chunk.metadata.get('_embedding'), list)))
        index = dict(state.index or {})
        if tenant_id_filter:
            index.update({'document_count': len(documents), 'chunk_count': len(chunks), 'embedding_count': embedding_count, 'filtered_by_tenant': tenant_id_filter})
        index['embedding_count'] = int(index.get('embedding_count') or embedding_count or 0)
        index['semantic_embedding_available'] = _facade()._semantic_embedding_available(int(index.get('embedding_count') or 0))
        rebuild_jobs = [self._rebuild_job_to_dict_locked(state, job) for job in sorted(rebuild_job_records, key=lambda item: item.created_at, reverse=True)[:10]]
        return {'success': True, 'dataset_id': dataset_id, 'document_count': len(documents), 'chunk_count': len(chunks), 'documents': [doc.to_dict() for doc in documents] if include_documents else [], 'tenant_ids': sorted({doc.tenant_id for doc in documents}), 'versions': sorted({doc.version_label for doc in documents}), 'index': index, 'rebuild_jobs': rebuild_jobs, 'rebuild_job_count': len(rebuild_jobs), 'rebuild_queue': self._rebuild_queue_summary_locked(state, tenant_id_filter=tenant_id_filter), 'storage_path': str(self._storage_path), 'persistent': True}

    def _rebuild_job_to_dict_locked(self, state: _facade()._DatasetState, job: _facade().DatasetRebuildJob) -> dict[str, _facade().Any]:
        payload = job.to_dict()
        payload['queue_position'] = self._rebuild_job_queue_position_locked(state, job)
        payload['max_concurrent_jobs'] = self._max_concurrent_rebuild_jobs
        return payload

    @staticmethod
    def _rebuild_job_queue_position_locked(state: _facade()._DatasetState, job: _facade().DatasetRebuildJob) -> int:
        if job.status != 'queued':
            return 0
        queued = [item for item in state.rebuild_jobs.values() if item.status == 'queued']
        queued.sort(key=lambda item: (item.queued_at or item.created_at, item.job_id))
        for (index, item) in enumerate(queued, start=1):
            if item.job_id == job.job_id:
                return index
        return 0

    def _rebuild_queue_summary_locked(self, state: _facade()._DatasetState, *, tenant_id_filter: str='') -> dict[str, _facade().Any]:
        jobs = [job for job in state.rebuild_jobs.values() if not tenant_id_filter or job.tenant_id == tenant_id_filter]
        counts = {'queued': 0, 'running': 0, 'completed': 0, 'failed': 0, 'cancelled': 0}
        for job in jobs:
            if job.status in counts:
                counts[job.status] += 1
        queued = sorted((job for job in jobs if job.status == 'queued'), key=lambda item: (item.queued_at or item.created_at, item.job_id))
        running = sorted((job for job in jobs if job.status == 'running'), key=lambda item: (item.started_at or item.updated_at, item.job_id))
        return {'max_concurrent_jobs': self._max_concurrent_rebuild_jobs, 'worker_enabled': self._rebuild_workers_enabled, 'queued': counts['queued'], 'running': counts['running'], 'completed': counts['completed'], 'failed': counts['failed'], 'cancelled': counts['cancelled'], 'next_job_id': queued[0].job_id if queued else '', 'running_job_ids': [job.job_id for job in running]}

    @staticmethod
    def _recover_rebuild_jobs_locked(state: _facade()._DatasetState) -> None:
        for job in state.rebuild_jobs.values():
            if job.status == 'running':
                now = _facade()._utc_now_iso()
                job.status = 'queued'
                job.error = 'requeued after service restart'
                job.worker_id = ''
                job.queued_at = now
                job.updated_at = now
