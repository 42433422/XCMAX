import { apiFetch, getApiBase } from '@/utils/apiBase'

export type ImConversationSummary = {
  id: number
  title: string
  is_direct: boolean
  last_message_at: string | null
  last_message_preview: string
  unread_count: number
  is_enterprise_dedicated_cs?: boolean
  /** 运营者客服收件箱里的「企业客户→专属客服」会话(管理端专用,走 /api/im/cs/inbox)。 */
  is_cs_inbox?: boolean
  /** CS 收件箱会话对应的企业客户 user_id(用于运营者视角判定气泡我方/对方)。 */
  customer_user_id?: number
  cs_mode?: 'ai' | 'human'
  cs_status?: 'ai_active' | 'ai_processing' | 'human_pending' | 'human_active'
  cs_transfer_reason?: string
  cs_summary?: string
  cs_last_operator_user_id?: number | null
  /** 客户端专属桥接对应的生产会话 id；本地 id 只用于固定入口。 */
  remote_conversation_id?: number
}

export type ImMessage = {
  id: number
  conversation_id: number
  sender_user_id: number
  sender_display_name?: string
  body: string
  origin?: 'user' | 'customer' | 'ai' | 'manual' | 'system'
  operator_user_id?: number | null
  /** 由生产端按已验证市场账号计算，跨节点时优先于本地 user id。 */
  is_self?: boolean
  created_at: string | null
}

export type EnterpriseCsThread = {
  conversation: ImConversationSummary
  messages: ImMessage[]
}

export type ImContact = {
  id: number
  display_name: string
  username: string
  is_enterprise_dedicated_cs?: boolean
}

const jsonHeaders: HeadersInit = { 'Content-Type': 'application/json' }

/** 仅当响应确为 JSON 时解析；否则抛出清晰错误（避免把 SPA 的 HTML 当 JSON 解析）。 */
async function readJson<T = Record<string, unknown>>(res: Response): Promise<T> {
  const ct = res.headers.get('content-type') || ''
  if (!ct.toLowerCase().includes('application/json')) {
    throw new Error(res.status === 401 ? '未登录' : `请求失败（HTTP ${res.status}）`)
  }
  return (await res.json()) as T
}

export async function fetchImContacts(keyword?: string): Promise<ImContact[]> {
  const suffix = keyword && keyword.trim() ? `?q=${encodeURIComponent(keyword.trim())}` : ''
  const res = await apiFetch(`/api/im/contacts${suffix}`, { headers: jsonHeaders })
  const data = await readJson<{ success?: boolean; contacts?: ImContact[] }>(res)
  if (!data.success) throw new Error('加载联系人失败')
  return data.contacts ?? []
}

export async function fetchImConversations(): Promise<ImConversationSummary[]> {
  const res = await apiFetch('/api/im/conversations', { headers: jsonHeaders })
  const data = await readJson<{ success?: boolean; conversations?: ImConversationSummary[] }>(res)
  if (!data.success) throw new Error('加载会话失败')
  return data.conversations ?? []
}

export async function fetchImUnreadTotal(): Promise<number> {
  try {
    const res = await apiFetch('/api/im/unread-total', { headers: jsonHeaders })
    const ct = res.headers.get('content-type') || ''
    if (!res.ok || !ct.toLowerCase().includes('application/json')) return 0
    const data = (await res.json()) as { success?: boolean; unread_total?: number }
    if (!data.success) return 0
    return Number(data.unread_total ?? 0)
  } catch {
    return 0
  }
}

export async function createDirectConversation(peerUserId: number): Promise<{ id: number; title: string | null; created: boolean }> {
  const res = await apiFetch('/api/im/conversations/direct', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ peer_user_id: peerUserId }),
  })
  const data = await readJson<{
    success?: boolean
    conversation?: { id: number; title: string | null; created: boolean }
    message?: string
  }>(res)
  if (!data.success || !data.conversation) {
    throw new Error(data.message ?? '创建会话失败')
  }
  return data.conversation
}

export async function fetchImMessages(conversationId: number, opts?: { limit?: number; beforeId?: number }): Promise<ImMessage[]> {
  const q = new URLSearchParams()
  if (opts?.limit) q.set('limit', String(opts.limit))
  if (opts?.beforeId) q.set('before_id', String(opts.beforeId))
  const suffix = q.toString() ? `?${q}` : ''
  const res = await apiFetch(`/api/im/conversations/${conversationId}/messages${suffix}`, {
    headers: jsonHeaders,
  })
  const data = await readJson<{ success?: boolean; messages?: ImMessage[] }>(res)
  if (!data.success) throw new Error('加载消息失败')
  return data.messages ?? []
}

export async function sendImMessage(conversationId: number, body: string): Promise<ImMessage> {
  const res = await apiFetch(`/api/im/conversations/${conversationId}/messages`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ body }),
  })
  const data = await readJson<{ success?: boolean; message?: ImMessage }>(res)
  const msg = data.message
  if (!data.success || !msg) throw new Error('发送失败')
  return msg
}

/** 客户端读取生产 SSOT 的企业专属客服会话，不使用本机 IM 主键同步。 */
export async function fetchEnterpriseCsThread(): Promise<EnterpriseCsThread> {
  const res = await apiFetch('/api/im/enterprise-cs/messages', {
    headers: jsonHeaders,
    timeoutMs: 25_000,
  })
  const data = await readJson<{
    success?: boolean
    conversation?: ImConversationSummary
    messages?: ImMessage[]
    message?: string
    detail?: string
  }>(res)
  if (!res.ok || !data.success || !data.conversation) {
    throw new Error(data.message || data.detail || '加载企业专属客服失败')
  }
  return { conversation: data.conversation, messages: data.messages ?? [] }
}

/** 客户端只提交正文；生产端从市场令牌解析真实企业账号。 */
export async function sendEnterpriseCsMessage(body: string): Promise<{
  conversation_id: number
  message: ImMessage
  state: Partial<ImConversationSummary>
}> {
  const res = await apiFetch('/api/im/enterprise-cs/messages', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ body }),
    timeoutMs: 25_000,
  })
  const data = await readJson<{
    success?: boolean
    conversation_id?: number
    message?: ImMessage
    state?: Partial<ImConversationSummary>
    detail?: string
  }>(res)
  if (!res.ok || !data.success || !data.message || !data.conversation_id) {
    throw new Error(data.detail || '发送失败')
  }
  return {
    conversation_id: data.conversation_id,
    message: data.message,
    state: data.state ?? {},
  }
}

export async function markImRead(conversationId: number, lastMessageId: number): Promise<void> {
  await apiFetch(`/api/im/conversations/${conversationId}/read`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ last_message_id: lastMessageId }),
  })
}

// ── 运营者客服收件箱(管理端):企业客户↔企业专属客服 ──

/** 运营者拉取所有「企业客户→专属客服」会话,映射成会话摘要给侧栏渲染。 */
export async function fetchCsInbox(): Promise<ImConversationSummary[]> {
  const res = await apiFetch('/api/im/cs/inbox', { headers: jsonHeaders })
  const data = await readJson<{
    success?: boolean
    conversations?: Array<{
      id: number
      customer_user_id: number
      customer_name: string
      unread_count: number
      last_message_at: string | null
      cs_mode?: 'ai' | 'human'
      cs_status?: 'ai_active' | 'ai_processing' | 'human_pending' | 'human_active'
      cs_transfer_reason?: string
      cs_summary?: string
      cs_last_operator_user_id?: number | null
    }>
  }>(res)
  if (!data.success) throw new Error('加载客服收件箱失败')
  return (data.conversations ?? []).map((c) => ({
    id: c.id,
    title: c.customer_name || `用户${c.customer_user_id}`,
    is_direct: true,
    last_message_at: c.last_message_at,
    last_message_preview: '',
    unread_count: c.unread_count,
    is_cs_inbox: true,
    customer_user_id: c.customer_user_id,
    cs_mode: c.cs_mode ?? 'ai',
    cs_status: c.cs_status ?? 'ai_active',
    cs_transfer_reason: c.cs_transfer_reason ?? '',
    cs_summary: c.cs_summary ?? '',
    cs_last_operator_user_id: c.cs_last_operator_user_id ?? null,
  }))
}

/** 运营者读某客服会话历史(以企业专属客服成员身份)。 */
export async function fetchCsInboxMessages(conversationId: number): Promise<ImMessage[]> {
  const res = await apiFetch(`/api/im/cs/inbox/${conversationId}/messages`, {
    headers: jsonHeaders,
  })
  const data = await readJson<{ success?: boolean; messages?: ImMessage[] }>(res)
  if (!data.success) throw new Error('加载客服消息失败')
  return data.messages ?? []
}

/** 运营者以「企业专属客服」身份回复客户。 */
export async function replyCsInbox(conversationId: number, body: string): Promise<ImMessage> {
  const res = await apiFetch(`/api/im/cs/inbox/${conversationId}/reply`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ body }),
  })
  const data = await readJson<{ success?: boolean; message?: ImMessage }>(res)
  const msg = data.message
  if (!data.success || !msg) throw new Error('回复失败')
  return msg
}

/** 管理端人工接管或恢复 AI 自动接待。 */
export async function updateCsInboxMode(conversationId: number, mode: 'ai' | 'human'): Promise<Partial<ImConversationSummary>> {
  const res = await apiFetch(`/api/im/cs/inbox/${conversationId}/mode`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ mode }),
  })
  const data = await readJson<{ success?: boolean; state?: Partial<ImConversationSummary>; message?: string }>(res)
  if (!data.success || !data.state) throw new Error(data.message || '切换接待模式失败')
  return data.state
}

export function imWebSocketUrl(): string {
  const apiBase = getApiBase().replace(/\/$/, '')
  if (/^https?:\/\//i.test(apiBase)) {
    return `${apiBase.replace(/^http/i, 'ws')}/ws/im`
  }

  const origin =
    typeof window !== 'undefined' && window.location?.origin ? window.location.origin.replace(/^http/i, 'ws') : 'ws://127.0.0.1:5000'
  const prefix = apiBase ? (apiBase.startsWith('/') ? apiBase : `/${apiBase}`) : ''
  return `${origin}${prefix}/ws/im`
}
