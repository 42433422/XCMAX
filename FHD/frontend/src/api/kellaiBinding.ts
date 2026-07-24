import { apiFetch } from '@/utils/apiBase'
import { clientShellRequestHeaders } from '@/utils/clientShell'

export type KellaiBindingState = 'connected' | 'pending' | 'not_connected' | 'offline'

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
  connection?: KellaiBindingConnection | null
  pending?: {
    request_id?: string
    expires_at?: string
  } | null
  available_scopes?: Array<{
    id: string
    label: string
    description: string
  }>
}

export type KellaiDataStatus = {
  customer_count: number
  unread_message_count: number
  latest_customer_at?: string
}

export type KellaiCustomer = {
  customer_id: number
  display_name: string
  stage?: string
  stage_label?: string
  channel_sources?: string[]
  last_message_preview?: string
  updated_at?: string
}

export type KellaiConversationMessage = {
  id: string
  customer_id: number
  customer_name?: string
  contact_id?: string
  contact_name?: string
  channel_type?: string
  direction: 'inbound' | 'outbound' | string
  content: string
  content_type?: string
  metadata?: Record<string, unknown> | null
  read?: boolean
  created_at?: string
  stage?: string
  stage_label?: string
  ai_score?: number
  ai_intent?: string
  pending_follow_up?: boolean
  next_action?: string
}

export type KellaiCopilotDraft = {
  draft_id: string
  customer_id: number
  summary: string
  intent: string
  risk_level: 'low' | 'medium' | 'high' | 'critical' | string
  next_action: string
  reply_draft: string
  evidence_message_ids: string[]
  status: 'pending_approval' | 'approved_for_manual_send' | 'rejected' | string
  created_at: string
  decided_at?: string
  decision_note?: string
  model?: string
}

export type KellaiFollowUpTask = {
  task_id: string
  customer_id: number
  source_draft_id: string
  title: string
  description: string
  priority: 'normal' | 'high' | 'urgent' | string
  status: 'open' | 'completed' | 'failed' | 'cancelled' | string
  due_at: string
  created_at: string
  completed_at?: string
  cancelled_at?: string
  outcome_result?: 'success' | 'no_result' | 'failed' | string
}

export type KellaiFollowUpMetrics = {
  total: number
  open: number
  completed: number
  failed: number
  cancelled: number
  outcomes: {
    success: number
    no_result: number
    failed: number
  }
  success_rate: number | null
}

export type KellaiFollowUpOverview = {
  tasks: KellaiFollowUpTask[]
  metrics: KellaiFollowUpMetrics
}

type Envelope<T> = {
  success?: boolean
  data?: T
  detail?: string
  error?: string
  message?: string
}

const PAIRING_HEADERS: HeadersInit = {
  'Content-Type': 'application/json',
  'X-Kellai-Local-Pairing': '1',
  ...clientShellRequestHeaders(),
}

async function request<T>(
  path: string,
  init?: RequestInit,
  allowEmptyData = false,
): Promise<T> {
  const response = await apiFetch(path, {
    ...init,
    headers: {
      ...PAIRING_HEADERS,
      ...(init?.headers || {}),
    },
  })
  const payload = (await response.json().catch(() => ({}))) as Envelope<T>
  if (
    !response.ok
    || payload.success !== true
    || (!allowEmptyData && payload.data === undefined)
  ) {
    throw new Error(payload.detail || payload.error || payload.message || `请求失败（HTTP ${response.status}）`)
  }
  return payload.data as T
}

export const kellaiBindingApi = {
  status(): Promise<KellaiBindingStatus> {
    return request<KellaiBindingStatus>('/api/kellai/binding/status')
  },

  start(): Promise<{ request_id: string; expires_at: string }> {
    return request<{ request_id: string; expires_at: string }>('/api/kellai/binding/start', {
      method: 'POST',
      body: '{}',
    })
  },

  dataStatus(): Promise<KellaiDataStatus> {
    return request<KellaiDataStatus>('/api/kellai/binding/data-status')
  },

  async customers(limit = 50): Promise<KellaiCustomer[]> {
    const safeLimit = Math.max(1, Math.min(Number(limit) || 50, 50))
    const data = await request<{ customers?: KellaiCustomer[] }>(
      `/api/kellai/binding/customers?limit=${safeLimit}`,
    )
    return data.customers || []
  },

  async conversations(customerId: number, limit = 100): Promise<KellaiConversationMessage[]> {
    const safeCustomerId = Number(customerId)
    if (!Number.isInteger(safeCustomerId) || safeCustomerId <= 0) {
      throw new Error('客户编号无效')
    }
    const safeLimit = Math.max(1, Math.min(Number(limit) || 100, 100))
    const data = await request<{ messages?: KellaiConversationMessage[] }>(
      `/api/kellai/binding/customers/${safeCustomerId}/conversations?limit=${safeLimit}`,
    )
    return data.messages || []
  },

  latestDraft(customerId: number): Promise<KellaiCopilotDraft | null> {
    const safeCustomerId = Number(customerId)
    if (!Number.isInteger(safeCustomerId) || safeCustomerId <= 0) {
      return Promise.reject(new Error('客户编号无效'))
    }
    return request<KellaiCopilotDraft | null>(
      `/api/kellai/binding/customers/${safeCustomerId}/copilot-drafts/latest`,
    )
  },

  followUpOverview(customerId: number): Promise<KellaiFollowUpOverview> {
    const safeCustomerId = Number(customerId)
    if (!Number.isInteger(safeCustomerId) || safeCustomerId <= 0) {
      return Promise.reject(new Error('客户编号无效'))
    }
    return request<KellaiFollowUpOverview>(
      `/api/kellai/binding/customers/${safeCustomerId}/follow-up-tasks`,
    )
  },

  async followUpTasks(customerId: number): Promise<KellaiFollowUpTask[]> {
    const overview = await this.followUpOverview(customerId)
    return overview.tasks || []
  },

  generateDraft(customerId: number): Promise<KellaiCopilotDraft> {
    const safeCustomerId = Number(customerId)
    if (!Number.isInteger(safeCustomerId) || safeCustomerId <= 0) {
      return Promise.reject(new Error('客户编号无效'))
    }
    return request<KellaiCopilotDraft>(
      `/api/kellai/binding/customers/${safeCustomerId}/copilot-drafts`,
      { method: 'POST', body: '{}' },
    )
  },

  decideDraft(
    draftId: string,
    decision: 'approve' | 'reject',
    note = '',
  ): Promise<KellaiCopilotDraft> {
    const safeDraftId = String(draftId || '').trim()
    if (!safeDraftId) return Promise.reject(new Error('草稿编号无效'))
    return request<KellaiCopilotDraft>(
      `/api/kellai/binding/copilot-drafts/${encodeURIComponent(safeDraftId)}/${decision}`,
      {
        method: 'POST',
        body: JSON.stringify({ note: String(note || '').slice(0, 500) }),
      },
    )
  },

  createFollowUpTask(draftId: string): Promise<KellaiFollowUpTask> {
    const safeDraftId = String(draftId || '').trim()
    if (!safeDraftId) return Promise.reject(new Error('草稿编号无效'))
    return request<KellaiFollowUpTask>(
      `/api/kellai/binding/copilot-drafts/${encodeURIComponent(safeDraftId)}/follow-up-task`,
      { method: 'POST', body: '{}' },
    )
  },

  decideFollowUpTask(
    taskId: string,
    decision: 'complete' | 'cancel',
    outcomeResult: 'success' | 'no_result' | 'failed' | '' = '',
  ): Promise<KellaiFollowUpTask> {
    const safeTaskId = String(taskId || '').trim()
    if (!safeTaskId) return Promise.reject(new Error('跟进任务编号无效'))
    if (decision === 'complete' && !['success', 'no_result', 'failed'].includes(outcomeResult)) {
      return Promise.reject(new Error('完成任务时必须记录执行结果'))
    }
    return request<KellaiFollowUpTask>(
      `/api/kellai/binding/follow-up-tasks/${encodeURIComponent(safeTaskId)}/${decision}`,
      { method: 'POST', body: JSON.stringify({ outcome_result: outcomeResult }) },
    )
  },

  async disconnect(): Promise<void> {
    await request<void>('/api/kellai/binding/disconnect', {
      method: 'POST',
      body: '{}',
    }, true)
  },
}

export default kellaiBindingApi
