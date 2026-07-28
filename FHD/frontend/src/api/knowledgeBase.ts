import { api, primeCsrfCookie } from './core'

export const PERSY_KNOWLEDGE_DATASET_ID = 'persy-knowledge'

export interface KnowledgeBaseDocument {
  document_id?: string
  source?: string
  parser?: string
  text_length?: number
  chunk_count?: number
  tenant_id?: string
  version?: number
  version_label?: string
  metadata?: Record<string, unknown>
}

export interface KnowledgeTenant {
  id: number | string
  tenant_id?: string
  code?: string
  name?: string
  is_active?: boolean
  plan_id?: string
}

export interface KnowledgeTenantDirectoryResponse {
  success: boolean
  data?: KnowledgeTenant[]
  message?: string
}

export type KnowledgePublicationStatus = 'draft' | 'published' | 'archived'

export interface KnowledgePublicationResponse {
  success: boolean
  dataset_id?: string
  document_id?: string
  previous_status?: string
  publication_status?: KnowledgePublicationStatus
  document?: KnowledgeBaseDocument
  message?: string
  error_code?: string
}

export interface KnowledgeBaseStatus {
  success: boolean
  dataset_id: string
  document_count: number
  chunk_count: number
  documents: KnowledgeBaseDocument[]
  tenant_ids?: string[]
  versions?: string[]
  index?: Record<string, unknown> & {
    semantic_embedding_available?: boolean
    embedding_count?: number
  }
  rebuild_jobs?: Array<Record<string, unknown>>
  rebuild_job_count?: number
  storage_path?: string
  persistent?: boolean
  message?: string
  error_code?: string
}

export interface KnowledgeOmniscientOverview {
  success: boolean
  omniscient?: boolean
  rag_enabled?: boolean
  embedder_available?: boolean
  semantic_embedding_available?: boolean
  recommended_dataset_id?: string
  dataset_count?: number
  document_count?: number
  chunk_count?: number
  datasets?: Record<string, KnowledgeBaseStatus>
  is_admin?: boolean
  message?: string
}

export interface KnowledgeRuntimeHealth {
  success: boolean
  rag_enabled?: boolean
  embedder_available?: boolean
  semantic_embedding_available?: boolean
  indexed_sources?: number
  indexed_chunks?: number
  dataset_count?: number
  dataset_document_count?: number
  dataset_chunk_count?: number
  recommended_dataset_id?: string
}

export type KnowledgeGraphNodeType =
  | 'core'
  | 'source'
  | 'topic'
  | 'knowledge'
  | 'memory'
  | 'recall'
  | 'onboarding'

export interface KnowledgeGraphNode {
  id: string
  label: string
  type: KnowledgeGraphNodeType | string
  summary?: string
  source?: string
  document_id?: string
  chunk_index?: number
  size?: number
  strength?: number
  metadata?: Record<string, unknown>
}

export interface KnowledgeGraphEdge {
  id?: string
  source: string
  target: string
  type?: string
  label?: string
  weight?: number
}

export interface KnowledgeGraphResponse {
  success: boolean
  dataset_id: string
  tenant_id?: string
  nodes: KnowledgeGraphNode[]
  edges: KnowledgeGraphEdge[]
  stats?: {
    node_count?: number
    edge_count?: number
    document_count?: number
    knowledge_count?: number
    topic_count?: number
    total_chunk_count?: number
    memory_count?: number
    active_memory_count?: number
    pending_memory_count?: number
    entity_count?: number
    truncated?: boolean
    categories?: Record<string, number>
  }
  generated_at?: string
  message?: string
  error_code?: string
}

export interface KnowledgeBaseIngestPayload {
  datasetId?: string
  source: string
  text: string
  documentId?: string
  tenantId?: string
  version?: string
  versionLabel?: string
  metadata?: Record<string, unknown>
}

export interface KnowledgeBaseUploadPayload {
  datasetId?: string
  file: File
  source?: string
  tenantId?: string
  version?: string
  versionLabel?: string
  metadata?: Record<string, unknown>
}

export interface KnowledgeBaseIngestResponse {
  success: boolean
  dataset_id: string
  document?: KnowledgeBaseDocument
  chunk_count?: number
  message?: string
  error_code?: string
  run_id?: string
  agent_run_id?: string
  agent_status?: string
}

export interface KnowledgeBaseChunk {
  text?: string
  source?: string
  score?: number
  chunk_index?: number
  char_start?: number
  char_end?: number
  metadata?: Record<string, unknown>
}

export interface KnowledgeBaseCitation {
  index?: number
  source?: string
  text?: string
  chunk_index?: number
  score?: number
}

export interface KnowledgeBaseQueryPayload {
  datasetId?: string
  query: string
  topK?: number
  includeAnswer?: boolean
  tenantId?: string
  version?: string
  metadataFilter?: Record<string, unknown>
  rerank?: boolean
  includePublic?: boolean
}

export interface KnowledgeBaseQueryResponse {
  success: boolean
  dataset_id: string
  query?: string
  answer?: string
  raw?: string
  chunks: KnowledgeBaseChunk[]
  citations?: KnowledgeBaseCitation[]
  tenant_id?: string
  version?: string
  metadata_filter?: Record<string, unknown>
  vector_backend_used?: boolean
  index?: Record<string, unknown>
  message?: string
  error_code?: string
  run_id?: string
  agent_run_id?: string
  agent_status?: string
  persy_memory?: {
    available: boolean
    count: number
    retriever?: string
    error_code?: string
  }
}

export interface PersyMemoryEntity {
  name?: string
  type?: string
  role?: string
}

export interface PersyMemoryValue {
  subject?: string
  predicate?: string
  object?: string
  statement?: string
  entities?: PersyMemoryEntity[]
  [key: string]: unknown
}

export interface PersyMemoryRecord {
  memory_id: string
  memory_type: 'preference' | 'entity' | 'episodic' | string
  key?: string
  value?: PersyMemoryValue | unknown
  statement: string
  status: 'pending' | 'active' | 'rejected' | 'deleted' | string
  scope: 'user' | 'tenant' | string
  confidence?: number
  strength?: number
  score?: number
  source?: string
  source_policy?: string
  source_trust?: string
  requires_user_confirmation?: boolean
  eligible_for_planner?: boolean
  evidence?: Array<Record<string, unknown>>
  created_at?: string
  updated_at?: string
  confirmed_at?: string
  last_recalled_at?: string
  recall_count?: number
  correction_count?: number
}

export interface PersyMemoryListResponse {
  success: boolean
  memories: PersyMemoryRecord[]
  summary?: {
    total?: number
    active?: number
    pending?: number
    returned?: number
  }
  message?: string
  error_code?: string
}

export interface PersyMemoryQueryResponse extends PersyMemoryListResponse {
  query?: string
  chunks: KnowledgeBaseChunk[]
  retriever?: string
}

export interface PersyMemoryMutationResponse {
  success: boolean
  memory?: PersyMemoryRecord
  message?: string
  error_code?: string
  required_permission?: string
}

export function normalizeKnowledgeDatasetId(datasetId?: string): string {
  return String(datasetId || PERSY_KNOWLEDGE_DATASET_ID).trim() || PERSY_KNOWLEDGE_DATASET_ID
}

function datasetPath(datasetId: string, suffix: string): string {
  return `/api/knowledge/v1/datasets/${encodeURIComponent(normalizeKnowledgeDatasetId(datasetId))}${suffix}`
}

export const knowledgeBaseApi = {
  health(): Promise<KnowledgeRuntimeHealth> {
    return api.get<KnowledgeRuntimeHealth>('/api/knowledge/v1/health')
  },

  listDatasets(): Promise<{
    success: boolean
    datasets?: Record<string, KnowledgeBaseStatus>
    dataset_count?: number
    document_count?: number
    chunk_count?: number
  }> {
    return api.get('/api/knowledge/v1/datasets')
  },

  omniscient(): Promise<KnowledgeOmniscientOverview> {
    return api.get<KnowledgeOmniscientOverview>('/api/knowledge/v1/omniscient')
  },

  tenants(): Promise<KnowledgeTenantDirectoryResponse> {
    return api.get<KnowledgeTenantDirectoryResponse>('/api/rbac/tenants')
  },

  async omniscientQuery(payload: {
    query: string
    topK?: number
  }): Promise<KnowledgeBaseQueryResponse & { omniscient?: boolean; dataset_hits?: number }> {
    await primeCsrfCookie()
    return api.post('/api/knowledge/v1/omniscient/query', {
      query: payload.query,
      top_k: payload.topK || 8,
      include_citations: true,
    })
  },

  status(
    datasetId = PERSY_KNOWLEDGE_DATASET_ID,
    options: { includeDocuments?: boolean; tenantId?: string } = {},
  ): Promise<KnowledgeBaseStatus> {
    const includeDocuments = options.includeDocuments !== false
    const params = new URLSearchParams()
    if (!includeDocuments) params.set('include_documents', 'false')
    if (options.tenantId) params.set('tenant_id', options.tenantId)
    const suffix = `/status${params.size ? `?${params.toString()}` : ''}`
    return api.get<KnowledgeBaseStatus>(datasetPath(datasetId, suffix))
  },

  async diffVersions(
    datasetId: string,
    payload: { leftVersion?: string; rightVersion?: string; tenantId?: string } = {},
  ): Promise<Record<string, unknown>> {
    await primeCsrfCookie()
    return api.post(datasetPath(datasetId, '/versions/diff'), {
      left_version: payload.leftVersion || '',
      right_version: payload.rightVersion || '',
      tenant_id: payload.tenantId || '',
    })
  },

  async rollbackVersion(
    datasetId: string,
    payload: { version: string; tenantId?: string },
  ): Promise<Record<string, unknown>> {
    await primeCsrfCookie()
    return api.post(datasetPath(datasetId, '/versions/rollback'), {
      version: payload.version,
      tenant_id: payload.tenantId || '',
    })
  },

  async rebuildIndex(
    datasetId: string,
    payload: { tenantId?: string } = {},
  ): Promise<Record<string, unknown>> {
    await primeCsrfCookie()
    return api.post(datasetPath(datasetId, '/index/rebuild'), {
      tenant_id: payload.tenantId || '',
    })
  },

  graph(
    datasetId = PERSY_KNOWLEDGE_DATASET_ID,
    limit = 80,
    options: { tenantId?: string } = {},
  ): Promise<KnowledgeGraphResponse> {
    const boundedLimit = Math.max(20, Math.min(Number(limit) || 80, 160))
    const params = new URLSearchParams({ limit: String(boundedLimit) })
    if (options.tenantId) params.set('tenant_id', options.tenantId)
    return api.get<KnowledgeGraphResponse>(datasetPath(datasetId, `/graph?${params.toString()}`))
  },

  async ingestDocument(payload: KnowledgeBaseIngestPayload): Promise<KnowledgeBaseIngestResponse> {
    await primeCsrfCookie()
    return api.post<KnowledgeBaseIngestResponse>(
      datasetPath(payload.datasetId || PERSY_KNOWLEDGE_DATASET_ID, '/documents'),
      {
        source: payload.source,
        text: payload.text,
        document_id: payload.documentId || '',
        tenant_id: payload.tenantId || '',
        version: payload.version || '',
        version_label: payload.versionLabel || '',
        chunk_strategy: 'semantic',
        metadata: payload.metadata || {},
      },
    )
  },

  async uploadDocument(payload: KnowledgeBaseUploadPayload): Promise<KnowledgeBaseIngestResponse> {
    await primeCsrfCookie()
    const form = new FormData()
    form.append('file', payload.file)
    form.append('source', payload.source || payload.file.name)
    form.append('tenant_id', payload.tenantId || '')
    form.append('version', payload.version || '')
    form.append('version_label', payload.versionLabel || '')
    form.append('chunk_strategy', 'semantic')
    form.append('metadata_json', JSON.stringify(payload.metadata || {}))
    return api.post<KnowledgeBaseIngestResponse>(
      datasetPath(payload.datasetId || PERSY_KNOWLEDGE_DATASET_ID, '/documents/upload'),
      form,
    )
  },

  async query(payload: KnowledgeBaseQueryPayload): Promise<KnowledgeBaseQueryResponse> {
    await primeCsrfCookie()
    return api.post<KnowledgeBaseQueryResponse>(
      datasetPath(payload.datasetId || PERSY_KNOWLEDGE_DATASET_ID, '/query'),
      {
        query: payload.query,
        top_k: payload.topK || 5,
        include_answer: payload.includeAnswer !== false,
        tenant_id: payload.tenantId || '',
        version: payload.version || '',
        metadata_filter: payload.metadataFilter || {},
        rerank: payload.rerank === true,
        include_public: payload.includePublic !== false,
      },
    )
  },

  memories(
    datasetId = PERSY_KNOWLEDGE_DATASET_ID,
    filters: { status?: string; memoryType?: string; limit?: number } = {},
  ): Promise<PersyMemoryListResponse> {
    const params = new URLSearchParams()
    if (filters.status) params.set('status', filters.status)
    if (filters.memoryType) params.set('memory_type', filters.memoryType)
    params.set('limit', String(Math.max(1, Math.min(Number(filters.limit) || 200, 1000))))
    return api.get<PersyMemoryListResponse>(
      datasetPath(datasetId, `/memories?${params.toString()}`),
    )
  },

  async queryMemories(
    payload: Pick<KnowledgeBaseQueryPayload, 'datasetId' | 'query' | 'topK'> & {
      reinforce?: boolean
    },
  ): Promise<PersyMemoryQueryResponse> {
    await primeCsrfCookie()
    return api.post<PersyMemoryQueryResponse>(
      datasetPath(payload.datasetId || PERSY_KNOWLEDGE_DATASET_ID, '/memories/query'),
      {
        query: payload.query,
        top_k: Math.max(1, Math.min(Number(payload.topK) || 5, 20)),
        reinforce: payload.reinforce !== false,
      },
    )
  },

  async confirmMemory(
    datasetId: string,
    memoryId: string,
    correction: Record<string, unknown> = {},
  ): Promise<PersyMemoryMutationResponse> {
    await primeCsrfCookie()
    return api.post<PersyMemoryMutationResponse>(
      datasetPath(datasetId, `/memories/${encodeURIComponent(memoryId)}/confirm`),
      correction,
    )
  },

  async rejectMemory(
    datasetId: string,
    memoryId: string,
    reason = '',
  ): Promise<PersyMemoryMutationResponse> {
    await primeCsrfCookie()
    return api.post<PersyMemoryMutationResponse>(
      datasetPath(datasetId, `/memories/${encodeURIComponent(memoryId)}/reject`),
      { reason },
    )
  },

  async updateMemory(
    datasetId: string,
    memoryId: string,
    patch: Record<string, unknown>,
  ): Promise<PersyMemoryMutationResponse> {
    await primeCsrfCookie()
    return api.patch<PersyMemoryMutationResponse>(
      datasetPath(datasetId, `/memories/${encodeURIComponent(memoryId)}`),
      patch,
    )
  },

  async deleteMemory(
    datasetId: string,
    memoryId: string,
    reason = '',
  ): Promise<PersyMemoryMutationResponse> {
    await primeCsrfCookie()
    const query = reason ? `?reason=${encodeURIComponent(reason)}` : ''
    return api.delete<PersyMemoryMutationResponse>(
      datasetPath(datasetId, `/memories/${encodeURIComponent(memoryId)}${query}`),
    )
  },

  async deleteDocument(
    datasetId: string,
    documentId: string,
  ): Promise<KnowledgeBaseStatus> {
    await primeCsrfCookie()
    return api.delete<KnowledgeBaseStatus>(
      datasetPath(datasetId, `/documents/${encodeURIComponent(documentId)}`),
    )
  },

  async setDocumentPublication(
    datasetId: string,
    documentId: string,
    status: KnowledgePublicationStatus,
    reason: string,
    expectedStatus?: KnowledgePublicationStatus,
  ): Promise<KnowledgePublicationResponse> {
    await primeCsrfCookie()
    return api.patch<KnowledgePublicationResponse>(
      datasetPath(
        datasetId,
        `/documents/${encodeURIComponent(documentId)}/publication`,
      ),
      { status, reason, expected_status: expectedStatus },
    )
  },
}

export default knowledgeBaseApi
