import { apiFetch } from '@/utils/apiBase'
import { clientShellRequestHeaders } from '@/utils/clientShell'

export type KellaiBindingState = 'connected' | 'pending' | 'not_connected' | 'offline' | 'revoked'

export type KellaiBindingConnection = {
  connection_id?: string
  source?: 'kellai'
  source_name?: string
  authorized_scopes?: string[]
  connected_at?: string
  authorized_by?: {
    id?: string
    display_name?: string
  }
}

export type KellaiBindingStatus = {
  state: KellaiBindingState
  message?: string
  connection?: KellaiBindingConnection | null
  pending?: {
    request_id?: string
    expires_at?: string
  } | null
  requires_reauthorization?: boolean
  available_scopes?: Array<{
    id: string
    label: string
    description: string
  }>
}

export type KellaiChannel = {
  channel_type: string
  name: string
  enabled: boolean
  connected: boolean
  connection_id: string
  capabilities: {
    send: boolean
    receive: boolean
    contacts: boolean
    sync: boolean
    transport?: string
    receive_mode?: string
    reason?: string
    [key: string]: unknown
  }
}

export type KellaiSendInput = {
  connection_id: string
  client_request_id: string
  customer_id: number
  channel_type: string
  contact_id: string
  content: string
}

export type KellaiSendReceipt = {
  connection_id?: string
  customer_id?: number
  channel_type?: string
  contact_id?: string
  request_id: string
  status: 'sending' | 'accepted' | 'delivered' | 'failed' | 'unknown' | 'requires_desktop_execution' | string
  provider_state?: 'accepted' | 'sent' | 'delivered' | 'read' | 'failed' | 'unknown' | string
  message_id?: string | null
  provider_message_id?: string | null
  persisted?: boolean
  replayed?: boolean
  error?: string | null
}

export type KellaiContact = {
  customer_id: number
  connection_id: string
  channel_type: string
  contact_id: string
  contact_name: string
  last_message_at?: string
}

export type KellaiConversationMessage = {
  id: string
  customer_id: number
  connection_id: string
  contact_id?: string
  contact_name?: string
  channel_type?: string
  direction: 'inbound' | 'outbound' | string
  content: string
  content_type?: string
  metadata?: Record<string, unknown> | null
  read?: boolean
  created_at?: string
}

type Envelope<T> = {
  success?: boolean
  data?: T
  detail?: string | { error?: string; message?: string; code?: string; request_not_dispatched?: boolean }
    | Array<{ loc?: unknown[]; msg?: string; type?: string }>
  error?: string
  message?: string
}

const PAIRING_HEADERS: HeadersInit = {
  'Content-Type': 'application/json',
  'X-Kellai-Local-Pairing': '1',
  ...clientShellRequestHeaders(),
}

async function request<T>(path: string, init?: RequestInit, allowEmptyData = false, receiptRequestId?: string): Promise<T> {
  const response = await apiFetch(path, {
    ...init,
    headers: {
      ...PAIRING_HEADERS,
      ...(init?.headers || {}),
    },
  })
  const payload = (await response.json().catch(() => ({}))) as Envelope<T>
  const receipt = payload.data as Partial<KellaiSendReceipt> | undefined
  const validReceipt = receiptRequestId && receipt?.request_id === receiptRequestId
    && typeof receipt.status === 'string'
    && ['sending', 'unknown', 'accepted', 'delivered', 'failed', 'cancelled', 'requires_desktop_execution', 'rejected'].includes(receipt.status)
  if (!response.ok || (receiptRequestId ? !validReceipt : payload.success !== true) || (!allowEmptyData && payload.data === undefined)) {
    const detail = payload.detail
    const structured = detail && typeof detail === 'object' && !Array.isArray(detail) ? detail : undefined
    const invalidBody = response.status === 422 && Array.isArray(detail) && detail.length > 0
      && detail.every(item => item && typeof item === 'object' && Array.isArray(item.loc)
        && item.loc[0] === 'body' && typeof item.type === 'string')
    const message = typeof detail === 'string' ? detail : structured?.message || structured?.error
    throw Object.assign(new Error(message || (invalidBody ? '消息内容或接收人不符合要求，本次未发送' : '') || payload.error || payload.message || `请求失败（HTTP ${response.status}）`), {
      code: structured?.code,
      requestNotDispatched: init?.method === 'POST' && path.endsWith('/messages/send')
        && (structured?.request_not_dispatched === true || invalidBody),
    })
  }
  return payload.data as T
}

export const kellaiBindingApi = {
  status(): Promise<KellaiBindingStatus> {
    return request<KellaiBindingStatus>('/api/kellai/binding/status')
  },

  start(requestedScopes?: string[]): Promise<{ request_id: string; expires_at: string }> {
    return request<{ request_id: string; expires_at: string }>('/api/kellai/binding/start', {
      method: 'POST',
      body: JSON.stringify(requestedScopes ? { requested_scopes: requestedScopes } : {}),
    })
  },

  async channels(): Promise<KellaiChannel[]> {
    const data = await request<{ channels?: KellaiChannel[] }>('/api/kellai/binding/channels')
    return data.channels || []
  },

  sendMessage(input: KellaiSendInput): Promise<KellaiSendReceipt> {
    return request<KellaiSendReceipt>('/api/kellai/binding/messages/send', {
      method: 'POST', body: JSON.stringify(input),
    }, false, input.client_request_id)
  },

  sendReceipt(requestId: string): Promise<KellaiSendReceipt> {
    return request<KellaiSendReceipt>(`/api/kellai/binding/messages/requests/${encodeURIComponent(requestId)}`, undefined, false, requestId)
  },

  async contacts(limit = 50): Promise<KellaiContact[]> {
    const safeLimit = Math.max(1, Math.min(Number(limit) || 50, 100))
    const data = await request<{ contacts?: KellaiContact[] }>(`/api/kellai/binding/contacts?limit=${safeLimit}`)
    return data.contacts || []
  },

  async messages(customerId: number, connectionId: string, limit = 100): Promise<KellaiConversationMessage[]> {
    if (!Number.isInteger(customerId) || customerId <= 0 || !/^[A-Za-z0-9_-]{1,128}$/.test(connectionId)) {
      throw new Error('请选择有效的账号连接和联系人')
    }
    const safeLimit = Math.max(1, Math.min(Number(limit) || 100, 100))
    const query = new URLSearchParams({ connection_id: connectionId, limit: String(safeLimit) })
    const data = await request<{ messages?: KellaiConversationMessage[] }>(
      `/api/kellai/binding/contacts/${customerId}/messages?${query}`,
    )
    return data.messages || []
  },

  async disconnect(): Promise<void> {
    await request<void>(
      '/api/kellai/binding/disconnect',
      {
        method: 'POST',
        body: '{}',
      },
      true,
    )
  },
}

export default kellaiBindingApi
