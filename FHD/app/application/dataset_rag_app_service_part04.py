# ruff: noqa
# mypy: ignore-errors
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.application.dataset_rag_app_service')

def _build_knowledge_graph_payload(*, dataset_id: str, tenant_id: str, documents: list[_facade().DatasetDocument], chunks: list[_facade().RetrievedChunk], limit: int) -> dict[str, _facade().Any]:
    ordered_documents = sorted(documents, key=lambda item: (item.source.casefold(), -int(item.version), item.document_id))[:40]
    allowed_document_ids = {doc.document_id for doc in ordered_documents}
    graph_chunks = [chunk for chunk in chunks if str((chunk.metadata or {}).get('document_id') or '') in allowed_document_ids]
    selected_chunks = _facade()._select_graph_chunks(graph_chunks, limit=max(1, limit - len(ordered_documents) - 20))
    root_id = f'persy:{dataset_id}'
    nodes: list[dict[str, _facade().Any]] = [{'id': root_id, 'label': 'Persy', 'type': 'core', 'summary': f'{len(ordered_documents)} 个来源，{len(graph_chunks)} 条知识切片' if ordered_documents else '等待资料进入后形成企业知识网络', 'size': 72, 'strength': 1.0, 'metadata': {'dataset_id': dataset_id, 'tenant_id': tenant_id, 'document_count': len(ordered_documents), 'chunk_count': len(graph_chunks)}}]
    edges: list[dict[str, _facade().Any]] = []
    for doc in ordered_documents:
        node_id = f'document:{doc.document_id}'
        nodes.append({'id': node_id, 'label': _facade()._graph_source_label(doc.source), 'type': 'source', 'summary': f'{doc.chunk_count} 个知识切片 · {doc.version_label}', 'source': doc.source, 'document_id': doc.document_id, 'size': 36 + min(doc.chunk_count, 8), 'strength': min(1.0, 0.45 + doc.chunk_count / 20), 'metadata': {'parser': doc.parser, 'text_length': doc.text_length, 'chunk_count': doc.chunk_count, 'tenant_id': doc.tenant_id, 'version': doc.version, 'version_label': doc.version_label, **_facade()._public_graph_metadata(doc.metadata)}})
        edges.append({'id': f'edge:{root_id}:{node_id}', 'source': root_id, 'target': node_id, 'type': 'source', 'label': '来源', 'weight': 0.72})
    chunk_node_rows: list[tuple[str, _facade().RetrievedChunk]] = []
    for chunk in selected_chunks:
        metadata = dict(chunk.metadata or {})
        document_id = str(metadata.get('document_id') or '')
        node_id = _facade()._graph_chunk_node_id(chunk)
        chunk_node_rows.append((node_id, chunk))
        nodes.append({'id': node_id, 'label': _facade()._graph_knowledge_label(chunk.text), 'type': 'knowledge', 'summary': _facade()._graph_excerpt(chunk.text, 420), 'source': chunk.source, 'document_id': document_id, 'chunk_index': chunk.chunk_index, 'size': 24, 'strength': 0.5, 'metadata': {'char_start': chunk.char_start, 'char_end': chunk.char_end, 'page': chunk.page, 'tenant_id': str(metadata.get('tenant_id') or ''), 'version_label': str(metadata.get('version_label') or '')}})
        parent_id = f'document:{document_id}'
        if document_id in allowed_document_ids:
            edges.append({'id': f'edge:{parent_id}:{node_id}', 'source': parent_id, 'target': node_id, 'type': 'contains', 'label': '包含', 'weight': 0.58})
    topic_rows = _facade()._extract_graph_topics(chunk_node_rows, limit=18)
    for topic in topic_rows:
        topic_id = f"topic:{_facade().hashlib.sha1(topic['key'].encode('utf-8')).hexdigest()[:12]}"
        nodes.append({'id': topic_id, 'label': topic['label'], 'type': 'topic', 'summary': f"连接 {topic['count']} 条知识", 'size': 28 + min(int(topic['count']) * 3, 18), 'strength': min(1.0, 0.48 + int(topic['count']) / 12), 'metadata': {'mention_count': topic['count']}})
        edges.append({'id': f'edge:{root_id}:{topic_id}', 'source': root_id, 'target': topic_id, 'type': 'topic', 'label': '主题', 'weight': 0.64})
        for chunk_node_id in topic['chunk_ids'][:6]:
            edges.append({'id': f'edge:{topic_id}:{chunk_node_id}', 'source': topic_id, 'target': chunk_node_id, 'type': 'mentions', 'label': '关联', 'weight': 0.42})
    category_counts = _facade().Counter((str(node.get('type') or 'unknown') for node in nodes))
    return {'success': True, 'dataset_id': dataset_id, 'tenant_id': tenant_id, 'nodes': nodes, 'edges': edges, 'stats': {'node_count': len(nodes), 'edge_count': len(edges), 'document_count': len(ordered_documents), 'knowledge_count': len(selected_chunks), 'topic_count': len(topic_rows), 'total_chunk_count': len(graph_chunks), 'truncated': len(selected_chunks) < len(graph_chunks), 'categories': dict(sorted(category_counts.items()))}, 'generated_at': _facade()._utc_now_iso()}

def _select_graph_chunks(chunks: list[_facade().RetrievedChunk], *, limit: int) -> list[_facade().RetrievedChunk]:
    """Round-robin documents so one large source cannot dominate the graph."""
    grouped: dict[str, list[_facade().RetrievedChunk]] = _facade().defaultdict(list)
    for chunk in chunks:
        document_id = str((chunk.metadata or {}).get('document_id') or chunk.source or 'inline')
        grouped[document_id].append(chunk)
    for rows in grouped.values():
        rows.sort(key=lambda item: (item.chunk_index, item.char_start))
    selected: list[_facade().RetrievedChunk] = []
    document_ids = sorted(grouped)
    cursor = 0
    while document_ids and len(selected) < max(0, limit):
        remaining: list[str] = []
        for document_id in document_ids:
            rows = grouped[document_id]
            if cursor < len(rows):
                selected.append(rows[cursor])
                if len(selected) >= limit:
                    break
            if cursor + 1 < len(rows):
                remaining.append(document_id)
        document_ids = remaining
        cursor += 1
    return selected

def _extract_graph_topics(chunk_rows: list[tuple[str, _facade().RetrievedChunk]], *, limit: int) -> list[dict[str, _facade().Any]]:
    topics: dict[str, dict[str, _facade().Any]] = {}
    for (node_id, chunk) in chunk_rows:
        for label in _facade()._graph_topic_candidates(chunk):
            key = label.casefold()
            row = topics.setdefault(key, {'key': key, 'label': label, 'count': 0, 'chunk_ids': []})
            row['count'] += 1
            if node_id not in row['chunk_ids']:
                row['chunk_ids'].append(node_id)
    return sorted(topics.values(), key=lambda item: (-int(item['count']), str(item['label']).casefold()))[:limit]

def _graph_topic_candidates(chunk: _facade().RetrievedChunk) -> list[str]:
    values: list[str] = []
    metadata = dict(chunk.metadata or {})
    for key in _facade()._GRAPH_TOPIC_METADATA_KEYS:
        raw = metadata.get(key)
        if isinstance(raw, (list, tuple, set, frozenset)):
            values.extend((str(item) for item in raw))
        elif raw is not None:
            values.extend(_facade().re.split('[,，;；|/#]+', str(raw)))
    source_stem = _facade().Path(str(chunk.source or '')).stem
    if source_stem and source_stem.casefold() not in {'inline', 'default'}:
        values.append(source_stem)
    for raw_line in str(chunk.text or '').splitlines()[:40]:
        line = _facade().re.sub('^[#>*\\-\\d.、\\s]+', '', raw_line).strip()
        is_heading = raw_line.lstrip().startswith('#') or line.endswith(('：', ':'))
        if is_heading and 2 <= len(line.rstrip('：:')) <= 32:
            values.append(line.rstrip('：:'))
    for match in _facade().re.finditer('(?:^|[，。；：、\\s])([A-Za-z][A-Za-z0-9_.-]{2,30}|[\\u4e00-\\u9fff]{2,16})(?=是|为|包括|支持|需要|必须|负责|属于|采用|禁止|应当|不得)', str(chunk.text or '')):
        values.append(match.group(1))
    english_counts = _facade().Counter((token.casefold() for token in _facade().re.findall('[A-Za-z][A-Za-z0-9_-]{2,30}', str(chunk.text or ''))))
    values.extend((token for (token, count) in english_counts.most_common(4) if count >= 2))
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        label = _facade()._clean_graph_label(value, max_length=30)
        key = label.casefold()
        if len(label) < 2 or key in _facade()._GRAPH_TOPIC_STOPWORDS or key in seen:
            continue
        seen.add(key)
        cleaned.append(label)
    return cleaned[:8]

def _graph_chunk_node_id(chunk: _facade().RetrievedChunk) -> str:
    metadata = dict(chunk.metadata or {})
    document_id = str(metadata.get('document_id') or chunk.source or 'inline')
    raw = f'{document_id}:{chunk.chunk_index}:{chunk.char_start}:{chunk.text}'
    return f"knowledge:{_facade().hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]}"

def _graph_source_label(source: str) -> str:
    label = _facade().Path(str(source or '资料来源')).name or '资料来源'
    return _facade()._clean_graph_label(label, max_length=32)

def _graph_knowledge_label(text: str) -> str:
    for raw_line in str(text or '').splitlines():
        line = _facade().re.sub('^[#>*\\-\\d.、\\s]+', '', raw_line).strip()
        if not line:
            continue
        sentence = _facade().re.split('[。！？!?；;]', line, maxsplit=1)[0]
        return _facade()._clean_graph_label(sentence or line, max_length=34)
    return '知识片段'

def _graph_excerpt(text: str, limit: int) -> str:
    compact = _facade().re.sub('\\s+', ' ', str(text or '')).strip()
    if len(compact) <= limit:
        return compact
    return compact[:max(1, limit - 1)].rstrip() + '…'

def _clean_graph_label(value: _facade().Any, *, max_length: int) -> str:
    label = _facade().re.sub('\\s+', ' ', str(value or '')).strip(' \t\r\n#*_-—:：')
    if len(label) <= max_length:
        return label
    return label[:max(1, max_length - 1)].rstrip() + '…'

def _public_graph_metadata(metadata: dict[str, _facade().Any] | None) -> dict[str, _facade().Any]:
    return {str(key): value for (key, value) in dict(metadata or {}).items() if not str(key).startswith('_') and str(key) not in {'file_path'}}

def _embedding_metadata(embedder: _facade().Callable[[str], list[float]] | None, text: str) -> dict[str, _facade().Any]:
    if embedder is None:
        return {}
    try:
        embedding = embedder(text)
    except _facade().RECOVERABLE_ERRORS:
        return {}
    if not isinstance(embedding, list) or not embedding:
        return {}
    try:
        return {'_embedding': [float(value) for value in embedding]}
    except (TypeError, ValueError):
        return {}

def _filter_chunks(chunks: list[_facade().RetrievedChunk], *, tenant_id: str, version: str | int, metadata_filter: dict[str, _facade().Any]) -> list[_facade().RetrievedChunk]:
    selected = list(chunks)
    tenant_key = _facade()._clean_key(str(tenant_id or ''), default='') if tenant_id else ''
    if tenant_key:
        selected = [chunk for chunk in selected if str((chunk.metadata or {}).get('tenant_id') or '') == tenant_key]
    if metadata_filter:
        selected = [chunk for chunk in selected if _facade()._metadata_matches(chunk, metadata_filter)]
    version_text = str(version or '').strip()
    if not version_text:
        return selected
    if version_text.lower() == 'latest':
        latest_by_scope: dict[tuple[str, str], int] = {}
        for chunk in selected:
            metadata = chunk.metadata or {}
            scope = (str(metadata.get('tenant_id') or ''), str(metadata.get('source') or chunk.source or ''))
            latest_by_scope[scope] = max(latest_by_scope.get(scope, 0), int(metadata.get('document_version') or 1))
        return [chunk for chunk in selected if int((chunk.metadata or {}).get('document_version') or 1) == latest_by_scope.get((str((chunk.metadata or {}).get('tenant_id') or ''), str((chunk.metadata or {}).get('source') or chunk.source or '')), 1)]
    normalized = version_text[1:] if version_text.lower().startswith('v') else version_text
    return [chunk for chunk in selected if str((chunk.metadata or {}).get('document_version') or '') == normalized or str((chunk.metadata or {}).get('version_label') or '') == version_text]

def _metadata_matches(chunk: _facade().RetrievedChunk, metadata_filter: dict[str, _facade().Any]) -> bool:
    metadata = dict(chunk.metadata or {})
    metadata.setdefault('source', chunk.source)
    for (key, expected) in metadata_filter.items():
        actual = metadata.get(str(key))
        if isinstance(expected, list):
            expected_values = {str(item) for item in expected}
            if str(actual) not in expected_values:
                return False
        elif isinstance(expected, dict):
            if not isinstance(actual, dict):
                return False
            for (nested_key, nested_expected) in expected.items():
                if str(actual.get(str(nested_key))) != str(nested_expected):
                    return False
        elif str(actual) != str(expected):
            return False
    return True

def _rerank_chunks(query: str, chunks: list[_facade().RetrievedChunk], *, top_k: int) -> list[_facade().RetrievedChunk]:
    query_terms = set(_facade()._tokenize_for_rerank(query))
    if not query_terms:
        return chunks[:top_k]
    reranked: list[_facade().RetrievedChunk] = []
    for chunk in chunks:
        chunk_terms = set(_facade()._tokenize_for_rerank(chunk.text))
        overlap = len(query_terms & chunk_terms)
        exact_bonus = 1.0 if query.strip().lower() and query.strip().lower() in chunk.text.lower() else 0.0
        boost = overlap / max(1, len(query_terms)) + exact_bonus
        reranked.append(_facade().RetrievedChunk(text=chunk.text, score=float(chunk.score) + boost, source=f'{chunk.source}+rerank' if 'rerank' not in chunk.source else chunk.source, chunk_index=chunk.chunk_index, char_start=chunk.char_start, char_end=chunk.char_end, metadata=chunk.metadata, source_url=chunk.source_url, page=chunk.page))
    return sorted(reranked, key=lambda item: item.score, reverse=True)[:top_k]

def _tokenize_for_rerank(text: str) -> list[str]:
    cleaned = ''.join((ch.lower() if ch.isalnum() else ' ' for ch in text))
    return [part for part in cleaned.split() if part]

def _utc_now_iso() -> str:
    return _facade().datetime.now(_facade().UTC).isoformat().replace('+00:00', 'Z')
