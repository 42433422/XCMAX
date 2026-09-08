import { apiFetch } from '@/utils/apiBase'

export interface ControlTask {
  id: string
  state: string
  reason: string
  request: { message: string; target: string; ticket_id?: number; customer_id?: number; parent_task_id?: string; source_sha?: string; source_archive_sha256?: string }
  para_task_id: string
  updated_at: number
  execution: { status?: string; merge_commit_sha?: string; subtasks?: Array<{ id: string; device_name: string; status: string }>; reports?: Array<{ event_id: string; report: string; applied: number; status: string; received_at: string }> }
  delivery: { status: string }
  facts?: { source: string; observed_at: number; tickets: Array<{ id: number; error?: string; title: string; status: string; resolution: { state?: string }; receipt_counts: { install_receipts: number; receipt_events: number }; delivery_verification?: { customer_acceptance: string; runtime_business_verified: boolean; completed: boolean; receipts: Array<{ receipt_id: string; stage: string; version: string; host_sha?: string; verified: boolean }> } }> }
}
export interface Fleet {
  enabled: boolean
  freshness: string
  error: string
  observed_at: number | null
  primary_device_id: string
  devices: Array<{ id: string; name: string; status: string; last_seen: string; tools: Array<{ toolName: string; status: string; currentTask?: string }> }>
}

async function json<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await apiFetch(path, options)
  const body = await response.json()
  if (!response.ok || body.success === false) throw new Error(body.detail || body.message || `HTTP ${response.status}`)
  return body as T
}

const base = '/api/xcmax/admin/mac-control'
export const readFleet = () => json<Fleet>(`${base}/fleet`)
export const readTasks = () => json<{ tasks: ControlTask[] }>(`${base}/tasks`)
export const readTask = (id: string, after = 0) => json<{ task: ControlTask; cursor?: number; events: Array<{ id: number; state: string; created_at: number }> }>(`${base}/tasks/${encodeURIComponent(id)}?after=${after}`)
export const readCustomerFacts = (id: number) => json<{ source: string; observed_at: number; deliveries: unknown[] }>(`${base}/facts?customer_id=${id}`)
export const cancelTask = (id: string) => json(`${base}/tasks/${encodeURIComponent(id)}/cancel`, { method: 'POST' })
export const submitControlTask = (message: string, requestKey: string, target: string, mode: string, ticketId?: number, verifyOnWindows = false) => json<{ task: ControlTask }>(
  '/api/admin/codex-super-employee/messages', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, durable_request: { request_key: requestKey, target, mode, ticket_id: ticketId, verify_on_windows: verifyOnWindows } }),
  },
)
