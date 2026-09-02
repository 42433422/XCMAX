// 知识库 v1/v2 域端点（自 legacyMonolith.ts 拆分，方法体保持不变）
import { req } from './shared'

export const knowledgeEndpoints = {
  knowledgeStatus: () => req('/api/knowledge/status'),
  knowledgeListDocuments: () => req('/api/knowledge/documents'),
  knowledgeUploadDocument: (file: File, opts?: { embeddingProvider?: string; embeddingModel?: string }) => {
    const form = new FormData()
    form.append('file', file)
    if (opts?.embeddingProvider) form.append('embedding_provider', opts.embeddingProvider)
    if (opts?.embeddingModel) form.append('embedding_model', opts.embeddingModel)
    return req('/api/knowledge/documents', { method: 'POST', body: form })
  },
  knowledgeDeleteDocument: (docId: string) => req(`/api/knowledge/documents/${encodeURIComponent(docId)}`, { method: 'DELETE' }),
  knowledgeExtractText: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return req('/api/knowledge/extract-text', { method: 'POST', body: form })
  },
  knowledgeSearch: (query: string, limit = 6, opts?: { embeddingProvider?: string; embeddingModel?: string }) =>
    req('/api/knowledge/search', {
      method: 'POST',
      body: JSON.stringify({
        query,
        limit,
        embedding_provider: opts?.embeddingProvider,
        embedding_model: opts?.embeddingModel,
      }),
    }),

  // v2: 集合 + 共享 + 跨上下文检索
  knowledgeV2Status: () => req('/api/knowledge/v2/status'),
  knowledgeV2ListCollections: (params?: { ownerKind?: string; ownerId?: string }) => {
    const qs: string[] = []
    if (params?.ownerKind) qs.push(`owner_kind=${encodeURIComponent(params.ownerKind)}`)
    if (params?.ownerId !== undefined && params?.ownerId !== null)
      qs.push(`owner_id=${encodeURIComponent(String(params.ownerId))}`)
    const suffix = qs.length ? `?${qs.join('&')}` : ''
    return req(`/api/knowledge/v2/collections${suffix}`)
  },
  knowledgeV2CreateCollection: (body: {
    owner_kind?: string
    owner_id?: string
    name: string
    description?: string
    visibility?: string
    embedding_model?: string
    embedding_dim?: number
  }) => req('/api/knowledge/v2/collections', { method: 'POST', body: JSON.stringify(body) }),
  knowledgeV2UpdateCollection: (
    id: number,
    body: { name?: string; description?: string; visibility?: string },
  ) =>
    req(`/api/knowledge/v2/collections/${encodeURIComponent(String(id))}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  knowledgeV2DeleteCollection: (id: number) =>
    req(`/api/knowledge/v2/collections/${encodeURIComponent(String(id))}`, { method: 'DELETE' }),
  knowledgeV2ListDocuments: (id: number) =>
    req(`/api/knowledge/v2/collections/${encodeURIComponent(String(id))}/documents`),
  knowledgeV2UploadDocument: (id: number, file: File, opts?: { embeddingProvider?: string; embeddingModel?: string }) => {
    const form = new FormData()
    form.append('file', file)
    if (opts?.embeddingProvider) form.append('embedding_provider', opts.embeddingProvider)
    if (opts?.embeddingModel) form.append('embedding_model', opts.embeddingModel)
    return req(
      `/api/knowledge/v2/collections/${encodeURIComponent(String(id))}/documents`,
      { method: 'POST', body: form },
    )
  },
  knowledgeV2DeleteDocument: (id: number, docId: string) =>
    req(
      `/api/knowledge/v2/collections/${encodeURIComponent(String(id))}/documents/${encodeURIComponent(docId)}`,
      { method: 'DELETE' },
    ),
  knowledgeV2ShareCollection: (
    id: number,
    body: { grantee_kind: string; grantee_id: string; permission?: string },
  ) =>
    req(`/api/knowledge/v2/collections/${encodeURIComponent(String(id))}/share`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  knowledgeV2Unshare: (id: number, membershipId: number) =>
    req(
      `/api/knowledge/v2/collections/${encodeURIComponent(String(id))}/share/${encodeURIComponent(String(membershipId))}`,
      { method: 'DELETE' },
    ),
  knowledgeV2Retrieve: (body: {
    query: string
    top_k?: number
    min_score?: number
    employee_id?: string | null
    workflow_id?: number | null
    org_id?: string | null
    collection_ids?: number[]
    embedding_provider?: string | null
    embedding_model?: string | null
  }) => req('/api/knowledge/v2/retrieve', { method: 'POST', body: JSON.stringify(body) }),
}
