import { req, authHeaders, requestBlob, requestStreamBlob } from './shared'

const requestStreamResponse = (url: string, init: RequestInit = {}) => fetch(url, init)

export const workbench = {
  workbenchWebSearch: (body: { query: string; max_results?: number; max_chars?: number }) =>
    req('/api/workbench/web-search', { method: 'POST', body: JSON.stringify(body) }),
  workbenchResearchContext: (body: unknown) => req('/api/workbench/research-context', { method: 'POST', body: JSON.stringify(body) }),
  workbenchStartSession: (body: unknown) => req('/api/workbench/sessions', { method: 'POST', body: JSON.stringify(body) }),
  workbenchStartSessionWithFiles: (body: unknown, files: File[]) => {
    const fd = new FormData()
    fd.append('metadata', JSON.stringify(body || {}))
    for (const f of files || []) fd.append('files', f)
    return req('/api/workbench/sessions', { method: 'POST', body: fd })
  },
  workbenchStartScriptSession: (metadata: unknown, files: File[]) => {
    const fd = new FormData()
    fd.append('metadata', JSON.stringify(metadata || {}))
    for (const f of files || []) fd.append('files', f)
    return req('/api/workbench/script-sessions', { method: 'POST', body: fd })
  },
  workbenchGetSession: (sessionId: string) => req(`/api/workbench/sessions/${encodeURIComponent(sessionId)}`),
  streamEmployeeAiDraft: (brief: string, opts?: { provider?: string; model?: string; suggestedId?: string }) =>
    requestStreamResponse('/api/workbench/employee-ai/draft', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({
        brief,
        provider: opts?.provider || undefined,
        model: opts?.model || undefined,
        suggested_id: opts?.suggestedId || undefined,
      }),
    }),
  refineSystemPrompt: (body: { current_prompt: string; instruction: string; role_context?: string; provider?: string; model?: string }) =>
    req('/api/workbench/employee-ai/refine-prompt', { method: 'POST', body: JSON.stringify(body) }),
  workbenchEdgeTts: (text: string, voice?: string, rate?: number) =>
    requestBlob('/api/workbench/tts/edge', {
      method: 'POST',
      body: JSON.stringify({ text, ...(voice ? { voice } : {}), ...(rate != null && Number.isFinite(rate) ? { rate } : {}) }),
    }),
  workbenchEdgeTtsStream: (text: string, voice?: string, rate?: number) =>
    requestStreamBlob('/api/workbench/tts/edge/stream', {
      method: 'POST',
      body: JSON.stringify({ text, ...(voice ? { voice } : {}), ...(rate != null && Number.isFinite(rate) ? { rate } : {}) }),
    }),
  listStudioAssets: (params?: { offset?: number; limit?: number }) => {
    const o = params?.offset ?? 0
    const l = params?.limit ?? 50
    return req(`/api/workbench/studio-assets?offset=${encodeURIComponent(String(o))}&limit=${encodeURIComponent(String(l))}`)
  },
  uploadStudioAsset: (file: File, opts?: { kind?: string; metadata?: Record<string, unknown> }) => {
    const form = new FormData()
    form.append('file', file)
    if (opts?.kind) form.append('kind', opts.kind)
    if (opts?.metadata && Object.keys(opts.metadata).length) form.append('metadata', JSON.stringify(opts.metadata))
    return req('/api/workbench/studio-assets', { method: 'POST', body: form })
  },
  deleteStudioAsset: (id: number) => req(`/api/workbench/studio-assets/${encodeURIComponent(String(id))}`, { method: 'DELETE' }),
  patchStudioAssetMetadata: (id: number, metadata: Record<string, unknown>) =>
    req(`/api/workbench/studio-assets/${encodeURIComponent(String(id))}`, { method: 'PATCH', body: JSON.stringify({ metadata }) }),
  downloadStudioAssetBlob: (id: number) => requestBlob(`/api/workbench/studio-assets/${encodeURIComponent(String(id))}/file`),
}

export const knowledge = {
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
    req('/api/knowledge/search', { method: 'POST', body: JSON.stringify({ query, limit, embedding_provider: opts?.embeddingProvider, embedding_model: opts?.embeddingModel }) }),
  knowledgeV2Status: () => req('/api/knowledge/v2/status'),
  knowledgeV2ListCollections: (params?: { ownerKind?: string; ownerId?: string }) => {
    const qs: string[] = []
    if (params?.ownerKind) qs.push(`owner_kind=${encodeURIComponent(params.ownerKind)}`)
    if (params?.ownerId !== undefined && params?.ownerId !== null) qs.push(`owner_id=${encodeURIComponent(String(params.ownerId))}`)
    const suffix = qs.length ? `?${qs.join('&')}` : ''
    return req(`/api/knowledge/v2/collections${suffix}`)
  },
  knowledgeV2CreateCollection: (body: { owner_kind?: string; owner_id?: string; name: string; description?: string; visibility?: string; embedding_model?: string; embedding_dim?: number }) =>
    req('/api/knowledge/v2/collections', { method: 'POST', body: JSON.stringify(body) }),
  knowledgeV2UpdateCollection: (id: number, body: { name?: string; description?: string; visibility?: string }) =>
    req(`/api/knowledge/v2/collections/${encodeURIComponent(String(id))}`, { method: 'PATCH', body: JSON.stringify(body) }),
  knowledgeV2DeleteCollection: (id: number) => req(`/api/knowledge/v2/collections/${encodeURIComponent(String(id))}`, { method: 'DELETE' }),
  knowledgeV2ListDocuments: (id: number) => req(`/api/knowledge/v2/collections/${encodeURIComponent(String(id))}/documents`),
  knowledgeV2UploadDocument: (id: number, file: File, opts?: { embeddingProvider?: string; embeddingModel?: string }) => {
    const form = new FormData()
    form.append('file', file)
    if (opts?.embeddingProvider) form.append('embedding_provider', opts.embeddingProvider)
    if (opts?.embeddingModel) form.append('embedding_model', opts.embeddingModel)
    return req(`/api/knowledge/v2/collections/${encodeURIComponent(String(id))}/documents`, { method: 'POST', body: form })
  },
  knowledgeV2DeleteDocument: (id: number, docId: string) =>
    req(`/api/knowledge/v2/collections/${encodeURIComponent(String(id))}/documents/${encodeURIComponent(docId)}`, { method: 'DELETE' }),
  knowledgeV2ShareCollection: (id: number, body: { grantee_kind: string; grantee_id: string; permission?: string }) =>
    req(`/api/knowledge/v2/collections/${encodeURIComponent(String(id))}/share`, { method: 'POST', body: JSON.stringify(body) }),
  knowledgeV2Unshare: (id: number, membershipId: number) =>
    req(`/api/knowledge/v2/collections/${encodeURIComponent(String(id))}/share/${encodeURIComponent(String(membershipId))}`, { method: 'DELETE' }),
  knowledgeV2Retrieve: (body: {
    query: string; top_k?: number; min_score?: number; employee_id?: string | null; workflow_id?: number | null
    org_id?: string | null; collection_ids?: number[]; embedding_provider?: string | null; embedding_model?: string | null
  }) => req('/api/knowledge/v2/retrieve', { method: 'POST', body: JSON.stringify(body) }),
}

export const openApiConnectors = {
  openApiListConnectors: () => req('/api/openapi-connectors/'),
  openApiGetConnector: (id: number | string) => req(`/api/openapi-connectors/${encodeURIComponent(String(id))}`),
  openApiImportConnector: (payload: unknown) => req('/api/openapi-connectors/import', { method: 'POST', body: JSON.stringify(payload) }),
  openApiDeleteConnector: (id: number | string) => req(`/api/openapi-connectors/${encodeURIComponent(String(id))}`, { method: 'DELETE' }),
  openApiSaveCredentials: (id: number | string, authType: string, config: unknown) =>
    req(`/api/openapi-connectors/${encodeURIComponent(String(id))}/credentials`, { method: 'PUT', body: JSON.stringify({ auth_type: authType, config }) }),
  openApiDeleteCredentials: (id: number | string) => req(`/api/openapi-connectors/${encodeURIComponent(String(id))}/credentials`, { method: 'DELETE' }),
  openApiToggleOperation: (id: number | string, operationId: string, enabled: boolean) =>
    req(`/api/openapi-connectors/${encodeURIComponent(String(id))}/operations/${encodeURIComponent(operationId)}`, { method: 'PATCH', body: JSON.stringify({ enabled }) }),
  openApiTestOperation: (id: number | string, operationId: string, payload: unknown) =>
    req(`/api/openapi-connectors/${encodeURIComponent(String(id))}/operations/${encodeURIComponent(operationId)}/test`, { method: 'POST', body: JSON.stringify(payload || {}) }),
  openApiPublishWorkflowNode: (id: number | string, payload: unknown) =>
    req(`/api/openapi-connectors/${encodeURIComponent(String(id))}/publish-workflow-node`, { method: 'POST', body: JSON.stringify(payload || {}) }),
  openApiListLogs: (id: number | string, limit = 50, offset = 0) =>
    req(`/api/openapi-connectors/${encodeURIComponent(String(id))}/logs?limit=${limit}&offset=${offset}`),
}

export const customerService = {
  customerServiceChat: (payload: { message: string; session_id?: number | null; context?: Record<string, unknown> }) =>
    req('/api/customer-service/chat', { method: 'POST', body: JSON.stringify(payload) }),
  customerServiceSessions: () => req('/api/customer-service/sessions'),
  customerServiceSessionDetail: (id: number | string) => req(`/api/customer-service/sessions/${encodeURIComponent(String(id))}`),
  customerServiceTickets: (status = '') => req(`/api/customer-service/tickets${status ? `?status=${encodeURIComponent(status)}` : ''}`),
  customerServiceTicketDetail: (id: number | string) => req(`/api/customer-service/tickets/${encodeURIComponent(String(id))}`),
  customerServiceActions: (ticketId?: number | string) => req(`/api/customer-service/actions${ticketId ? `?ticket_id=${encodeURIComponent(String(ticketId))}` : ''}`),
  customerServiceStandards: () => req('/api/customer-service/standards'),
  customerServiceCreateStandard: (payload: unknown) => req('/api/customer-service/standards', { method: 'POST', body: JSON.stringify(payload || {}) }),
  customerServiceUpdateStandard: (id: number | string, payload: unknown) =>
    req(`/api/customer-service/standards/${encodeURIComponent(String(id))}`, { method: 'PUT', body: JSON.stringify(payload || {}) }),
  customerServiceIntegrations: () => req('/api/customer-service/integrations'),
  customerServiceCreateIntegration: (payload: unknown) => req('/api/customer-service/integrations', { method: 'POST', body: JSON.stringify(payload || {}) }),
  customerServiceUpdateIntegration: (id: number | string, payload: unknown) =>
    req(`/api/customer-service/integrations/${encodeURIComponent(String(id))}`, { method: 'PUT', body: JSON.stringify(payload || {}) }),
}

export const butler = {
  agentCorpChat: (payload: {
    messages: Array<{ role: string; content: string }>
    page_id?: string
    page_context?: string
    max_tokens?: number
  }) =>
    req('/api/agent/butler/corp-chat', { method: 'POST', body: JSON.stringify(payload) }),
  agentCorpIntakeFill: (payload: {
    message: string
    current_draft?: Record<string, unknown>
    page_summary?: string
  }) =>
    req('/api/agent/butler/corp-intake-fill', { method: 'POST', body: JSON.stringify(payload) }),
  agentButlerChat: (payload: { messages: unknown[]; conversation_id?: number | null; page_context?: string }) =>
    req('/api/agent/butler/chat', { method: 'POST', body: JSON.stringify(payload) }),
  agentButlerChatStream: (
    payload: { messages: unknown[]; conversation_id?: number | null; page_context?: string },
    signal?: AbortSignal,
  ) =>
    requestStreamResponse('/api/agent/butler/chat/stream', {
      method: 'POST',
      signal,
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', ...authHeaders() },
      body: JSON.stringify(payload),
    }),
  listButlerSkills: () => req('/api/agent/butler/skills'),
  recordButlerAction: (payload: { route: string; action: string; args?: Record<string, unknown>; risk: string; status: 'success' | 'failed' | 'cancelled' }) =>
    req('/api/agent/butler/actions', { method: 'POST', body: JSON.stringify(payload) }),
  updateButlerSkillActive: (id: number | string, isActive: boolean) =>
    req(`/api/agent/butler/skills/${encodeURIComponent(String(id))}`, { method: 'PATCH', body: JSON.stringify({ is_active: isActive }) }),
  butlerOrchestrateStart: (payload: {
    target_type: 'mod' | 'workflow' | 'employee'; target_id: string; brief: string; scope?: string
    focus_paths?: string[]; with_snapshot?: boolean; provider?: string; model?: string
  }) => req('/api/agent/butler/orchestrate', { method: 'POST', body: JSON.stringify(payload) }),
  butlerAllHandsReportStartSession: (payload: {
    employee_ids?: string[]; with_research?: boolean; max_employees?: number
    concurrency?: number; user_question?: string; synthesize?: boolean
  }) => req('/api/agent/butler/all-hands-report/sessions', { method: 'POST', body: JSON.stringify(payload || {}) }),
  butlerAllHandsReport: (payload: {
    employee_ids?: string[]; with_research?: boolean; max_employees?: number
    concurrency?: number; user_question?: string; synthesize?: boolean
  }) => req('/api/agent/butler/all-hands-report', { method: 'POST', body: JSON.stringify(payload || {}) }),
}
