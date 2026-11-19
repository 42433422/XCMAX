import { requestJson } from '../infrastructure/http/client'

const butler = '/api/agent/butler'
const followups = `${butler}/delivery-followups`
const memory = `${butler}/admin-memory`

export interface DeliveryFollowup {
  ticket_id: number
  ticket_no: string
  title: string
  stage_label: string
  expected_completion_at: string | null
  following: boolean
  needs_attention: boolean
  attention_reason: string | null
  can_resume: boolean
  approval_id: string | null
  approval_title: string | null
  approval_reason: string | null
}

export interface DeliveryFollowupDetail {
  item: DeliveryFollowup
  events: DeliveryFollowupEvent[]
}

export interface DeliveryFollowupEvent {
  id: string
  kind: string
  label: string
  at: string | null
  status: string | null
}

export interface XiaoCMemoryInput {
  key: string
  statement: string
}

export interface XiaoCMemory extends XiaoCMemoryInput {
  memory_id: string
  updated_at: string
  source: string
}

export const xiaocAdminApi = {
  listFollowups: () => requestJson<{ items: DeliveryFollowup[] }>(followups),
  followupDetail: (id: number) => requestJson<DeliveryFollowupDetail>(`${followups}/${id}`),
  follow: (id: number, following: boolean) =>
    requestJson<DeliveryFollowupDetail>(`${followups}/${id}`, {
      method: 'PUT',
      body: JSON.stringify({ following }),
    }),
  resume: (id: number) => requestJson<DeliveryFollowupDetail>(`${followups}/${id}/resume`, { method: 'POST' }),
  approve: (id: number, approvalId: string) =>
    requestJson<DeliveryFollowupDetail>(`${followups}/${id}/approve`, {
      method: 'POST',
      body: JSON.stringify({ approval_id: approvalId }),
    }),
  listMemory: () => requestJson<{ memories: XiaoCMemory[] }>(memory),
  saveMemory: (input: XiaoCMemoryInput, id?: string) =>
    requestJson<{ memory: XiaoCMemory }>(id ? `${memory}/${encodeURIComponent(id)}` : memory, {
      method: id ? 'PATCH' : 'POST',
      body: JSON.stringify(input),
    }),
  deleteMemory: (id: string) =>
    requestJson<{ success: true }>(`${memory}/${encodeURIComponent(id)}`, { method: 'DELETE' }),
}
