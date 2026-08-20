import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiBaseMocks = vi.hoisted(() => ({
  apiFetch: vi.fn(),
}))

vi.mock('@/utils/apiBase', () => ({
  apiFetch: apiBaseMocks.apiFetch,
}))

import { kellaiBindingApi } from './kellaiBinding'

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('kellaiBindingApi', () => {
  beforeEach(() => {
    apiBaseMocks.apiFetch.mockReset()
  })

  it('loads binding status through the local pairing API', async () => {
    apiBaseMocks.apiFetch.mockResolvedValueOnce(
      jsonResponse({
        success: true,
        data: { state: 'connected', connection: { authorized_scopes: ['customer_profiles.read'] } },
      }),
    )

    await expect(kellaiBindingApi.status()).resolves.toMatchObject({ state: 'connected' })
    expect(apiBaseMocks.apiFetch).toHaveBeenCalledWith(
      '/api/kellai/binding/status',
      expect.objectContaining({
        headers: expect.objectContaining({
          'X-Kellai-Local-Pairing': '1',
          'X-XCMAX-Client-Shell': 'enterprise',
        }),
      }),
    )
  })

  it('normalizes customer and conversation limits', async () => {
    apiBaseMocks.apiFetch
      .mockResolvedValueOnce(
        jsonResponse({
          success: true,
          data: { customers: [{ customer_id: 7, display_name: '测试客户' }] },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          success: true,
          data: { messages: [{ id: 'm1', customer_id: 7, direction: 'inbound', content: '你好' }] },
        }),
      )

    await expect(kellaiBindingApi.customers(999)).resolves.toHaveLength(1)
    await expect(kellaiBindingApi.conversations(7, 999)).resolves.toHaveLength(1)

    expect(apiBaseMocks.apiFetch).toHaveBeenNthCalledWith(1, '/api/kellai/binding/customers?limit=50', expect.any(Object))
    expect(apiBaseMocks.apiFetch).toHaveBeenNthCalledWith(2, '/api/kellai/binding/customers/7/conversations?limit=100', expect.any(Object))
  })

  it('rejects invalid customer ids before making a request', async () => {
    await expect(kellaiBindingApi.conversations(0)).rejects.toThrow('客户编号无效')
    expect(apiBaseMocks.apiFetch).not.toHaveBeenCalled()
  })

  it('creates and approves a copilot draft through client-only endpoints', async () => {
    const draft = {
      draft_id: 'draft-1',
      customer_id: 7,
      summary: '客户询问交期',
      intent: '交期咨询',
      risk_level: 'medium',
      next_action: '核实交期',
      reply_draft: '我先为您核实。',
      evidence_message_ids: ['m1'],
      status: 'pending_approval',
      created_at: '2026-07-15T10:00:00Z',
    }
    apiBaseMocks.apiFetch
      .mockResolvedValueOnce(jsonResponse({ success: true, data: null }))
      .mockResolvedValueOnce(jsonResponse({ success: true, data: draft }))
      .mockResolvedValueOnce(
        jsonResponse({
          success: true,
          data: { ...draft, status: 'approved_for_manual_send' },
        }),
      )

    await expect(kellaiBindingApi.latestDraft(7)).resolves.toBeNull()
    await expect(kellaiBindingApi.generateDraft(7)).resolves.toMatchObject({ draft_id: 'draft-1' })
    await expect(kellaiBindingApi.decideDraft('draft-1', 'approve')).resolves.toMatchObject({
      status: 'approved_for_manual_send',
    })

    expect(apiBaseMocks.apiFetch).toHaveBeenNthCalledWith(
      2,
      '/api/kellai/binding/customers/7/copilot-drafts',
      expect.objectContaining({ method: 'POST' }),
    )
    expect(apiBaseMocks.apiFetch).toHaveBeenNthCalledWith(
      3,
      '/api/kellai/binding/copilot-drafts/draft-1/approve',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('creates and completes an idempotent follow-up task through bounded action endpoints', async () => {
    const task = {
      task_id: 'task-1',
      customer_id: 7,
      source_draft_id: 'draft-1',
      title: '客户跟进 · 交期咨询',
      description: '核实交期并回访',
      priority: 'normal',
      status: 'open',
      due_at: '2026-07-16T10:00:00Z',
      created_at: '2026-07-15T10:00:00Z',
    }
    apiBaseMocks.apiFetch
      .mockResolvedValueOnce(jsonResponse({ success: true, data: { tasks: [task] } }))
      .mockResolvedValueOnce(jsonResponse({ success: true, data: task }))
      .mockResolvedValueOnce(
        jsonResponse({
          success: true,
          data: { ...task, status: 'completed' },
        }),
      )

    await expect(kellaiBindingApi.followUpTasks(7)).resolves.toHaveLength(1)
    await expect(kellaiBindingApi.createFollowUpTask('draft-1')).resolves.toMatchObject({
      task_id: 'task-1',
    })
    await expect(kellaiBindingApi.decideFollowUpTask('task-1', 'complete', 'success')).resolves.toMatchObject({
      status: 'completed',
    })

    expect(apiBaseMocks.apiFetch).toHaveBeenNthCalledWith(
      2,
      '/api/kellai/binding/copilot-drafts/draft-1/follow-up-task',
      expect.objectContaining({ method: 'POST' }),
    )
    expect(apiBaseMocks.apiFetch).toHaveBeenNthCalledWith(
      3,
      '/api/kellai/binding/follow-up-tasks/task-1/complete',
      expect.objectContaining({ method: 'POST', body: '{"outcome_result":"success"}' }),
    )
  })

  it('accepts the success-only disconnect response', async () => {
    apiBaseMocks.apiFetch.mockResolvedValueOnce(jsonResponse({ success: true }))
    await expect(kellaiBindingApi.disconnect()).resolves.toBeUndefined()
    expect(apiBaseMocks.apiFetch).toHaveBeenCalledWith('/api/kellai/binding/disconnect', expect.objectContaining({ method: 'POST' }))
  })

  it('surfaces backend errors without treating HTML or empty payloads as success', async () => {
    apiBaseMocks.apiFetch.mockResolvedValueOnce(
      jsonResponse(
        {
          success: false,
          detail: '客来来尚未连接',
        },
        409,
      ),
    )

    await expect(kellaiBindingApi.customers()).rejects.toThrow('客来来尚未连接')
  })
})
