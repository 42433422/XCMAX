import { req, authHeaders } from './shared'

export const llm = {
  llmStatus: () => req('/api/llm/status'),
  llmResolveChatDefault: () => req('/api/llm/resolve-chat-default'),
  llmCatalog: (refresh = false) =>
    req(`/api/llm/catalog?refresh=${refresh ? 1 : 0}`, { timeoutMs: 120_000 }),
  llmSaveCredentials: (provider: string, apiKey: string, baseUrl?: string | null) => req(`/api/llm/credentials/${encodeURIComponent(provider)}`, { method: 'PUT', body: JSON.stringify({ api_key: apiKey, base_url: baseUrl ?? null }) }),
  llmDeleteCredentials: (provider: string) => req(`/api/llm/credentials/${encodeURIComponent(provider)}`, { method: 'DELETE' }),
  llmSavePreferences: (provider: string, model: string) => req('/api/llm/preferences', { method: 'PUT', body: JSON.stringify({ provider, model }) }),
  llmPricing: () => req('/api/llm/pricing'),
  llmUsage: (limit = 50, offset = 0) => req(`/api/llm/usage?limit=${limit}&offset=${offset}`),
  llmConversations: (limit = 30, offset = 0) => req(`/api/llm/conversations?limit=${limit}&offset=${offset}`),
  llmConversationDetail: (id: string | number) => req(`/api/llm/conversations/${encodeURIComponent(String(id))}`),
  llmAdminSavePrice: (data: Record<string, unknown>) => req('/api/llm/admin/pricing', { method: 'PUT', body: JSON.stringify(data || {}) }),
  llmAdminListPricing: (opts?: { provider?: string; q?: string; limit?: number; offset?: number }) => {
    const p = new URLSearchParams()
    if (opts?.provider) p.set('provider', opts.provider)
    if (opts?.q) p.set('q', opts.q)
    if (opts?.limit != null) p.set('limit', String(opts.limit))
    if (opts?.offset != null) p.set('offset', String(opts.offset))
    const qs = p.toString()
    return req(`/api/llm/admin/pricing${qs ? `?${qs}` : ''}`)
  },
  llmAdminBatchPricing: (body: Record<string, unknown>) =>
    req('/api/llm/admin/pricing/batch', { method: 'POST', body: JSON.stringify(body || {}) }),
  llmAdminPricingSettings: (body: Record<string, unknown>) =>
    req('/api/llm/admin/pricing/settings', { method: 'PUT', body: JSON.stringify(body || {}) }),
  llmAdminDisablePrice: (provider: string, model: string) => {
    const p = new URLSearchParams({ provider, model })
    return req(`/api/llm/admin/pricing?${p.toString()}`, { method: 'DELETE' })
  },
  llmAdminOfficialSources: (provider: string) =>
    req(`/api/llm/admin/pricing/official-sources?provider=${encodeURIComponent(provider)}`),
  llmAdminSyncOfficialPrices: (body: Record<string, unknown>) =>
    req('/api/llm/admin/pricing/sync-official', { method: 'POST', body: JSON.stringify(body || {}) }),
  llmAdminApplyOfficialMarkup: (body: Record<string, unknown>) =>
    req('/api/llm/admin/pricing/apply-official-markup', { method: 'POST', body: JSON.stringify(body || {}) }),
  llmAdminModelCapabilities: (opts?: { provider?: string; q?: string; limit?: number }) => {
    const p = new URLSearchParams()
    if (opts?.provider) p.set('provider', opts.provider)
    if (opts?.q) p.set('q', opts.q)
    if (opts?.limit != null) p.set('limit', String(opts.limit))
    const qs = p.toString()
    return req(`/api/llm/admin/model-capabilities${qs ? `?${qs}` : ''}`)
  },
  llmAdminModelCapabilityReview: (body: { provider: string; model: string; l3_status: string; notes?: string }) =>
    req('/api/llm/admin/model-capabilities/review', { method: 'PUT', body: JSON.stringify(body) }),
  llmChat: async (provider: string, model: string, messages: unknown[], maxTokens: number | null = null, conversationId: number | null = null) => {
    const res = (await req('/api/llm/chat', {
      method: 'POST',
      body: JSON.stringify({ provider, model, messages, max_tokens: maxTokens, conversation_id: conversationId }),
    })) as { billed?: boolean; charge_amount?: number; content?: unknown } & Record<string, unknown>
    if (res && (res.billed === true || (Number(res.charge_amount) || 0) > 0)) {
      void import('../utils/llmBillingRefresh').then((m) => m.refreshLevelAndWalletAfterLlm())
    }
    return res
  },
  llmChatStream: (provider: string, model: string, messages: unknown[], maxTokens: number | null = null, conversationId: number | null = null, signal?: AbortSignal) => {
    const headers = new Headers(authHeaders())
    headers.set('Content-Type', 'application/json')
    headers.set('Accept', 'text/event-stream')
    return fetch('/api/llm/chat/stream', {
      method: 'POST',
      headers,
      signal,
      body: JSON.stringify({ provider, model, messages, max_tokens: maxTokens, conversation_id: conversationId }),
    })
  },
  llmGenerateImage: (provider: string, model: string, prompt: string, opts: { size?: string; count?: number; n?: number } = {}) =>
    req('/api/llm/image', {
      method: 'POST',
      body: JSON.stringify({ provider, model, prompt, size: opts.size || '1024x1024', n: opts.count || opts.n || 1 }),
    }),
  llmGeneratePptxBlob: async (title: string, markdown: string, filename = 'ai-presentation.pptx') => {
    const headers = new Headers(authHeaders())
    headers.set('Content-Type', 'application/json')
    const res = await fetch('/api/llm/pptx', { method: 'POST', headers, body: JSON.stringify({ title, markdown, filename }) })
    const buf = await res.arrayBuffer()
    if (!res.ok) {
      let message = res.statusText || '生成 PPT 失败'
      try {
        const text = new TextDecoder().decode(buf)
        const data = JSON.parse(text)
        message = data?.detail || data?.message || message
      } catch { /* ignore */ }
      throw new Error(message)
    }
    return new Blob([buf], { type: 'application/vnd.openxmlformats-officedocument.presentationml.presentation' })
  },
}
