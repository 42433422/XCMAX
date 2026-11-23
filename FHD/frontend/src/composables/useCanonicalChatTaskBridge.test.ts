import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import agentRunsApi, { type AgentRunResponse } from '@/api/agentRuns'
import { useCanonicalChatTaskBridge } from './useCanonicalChatTaskBridge'
import { useShipmentTask, type ShipmentTask } from './useShipmentTask'

vi.mock('@/api/agentRuns', () => ({ default: { createTask: vi.fn(), getRun: vi.fn(), continueRun: vi.fn(), cancelRun: vi.fn() } }))

const receipt = (status: string, final_output = {}): AgentRunResponse => ({
  success: true, data: { run_id: 'original-run', user_id: 'u1', message: '发货', status, final_output },
})
const task = (): ShipmentTask => ({ type: 'shipment_generate', title: '发货', payload: { tool_id: 'shipment_orders', action: 'generate', params: {} } })
const bridge = () => useCanonicalChatTaskBridge({ sessionId: ref('session'), createTaskId: () => 'original-task', refreshTasks: vi.fn().mockResolvedValue(undefined) })

beforeEach(() => { vi.resetAllMocks() })

describe('canonical task receipts', () => {
  it('declines an API-only card without inventing a task identity or making a request', async () => {
    const card: ShipmentTask = { type: 'custom', api_url: '/api/unregistered', method: 'POST', payload: {} }
    const api = bridge()
    expect(api.hasCanonicalTarget(card)).toBe(false)
    expect(await api.stageCanonicalTask(card)).toBeNull()
    expect(await api.executeCanonicalTask(card)).toBeNull()
    expect(card).not.toHaveProperty('agentTaskId')
    expect(agentRunsApi.createTask).not.toHaveBeenCalled()
    expect(agentRunsApi.getRun).not.toHaveBeenCalled()
    expect(agentRunsApi.continueRun).not.toHaveBeenCalled()
  })

  it('only reads a legacy original run when its capability contract is missing', async () => {
    vi.mocked(agentRunsApi.getRun).mockResolvedValue({ ...receipt('waiting_user'), approval: { grant: 'real-grant' } })
    const card: ShipmentTask = { type: 'custom', agentRunId: 'original-run', api_url: '/api/unregistered' }
    const api = bridge()
    expect(api.hasCanonicalTarget(card)).toBe(true)
    const result = await api.executeCanonicalTask(card)
    expect(await result!.json()).toMatchObject({ run_id: 'original-run', success: false, execution_state: 'waiting_user' })
    expect(agentRunsApi.getRun).toHaveBeenCalledExactlyOnceWith('original-run')
    expect(agentRunsApi.createTask).not.toHaveBeenCalled()
    expect(agentRunsApi.continueRun).not.toHaveBeenCalled()
    expect(card).not.toHaveProperty('agentTaskId')
  })

  it('does not translate a retired import capability into another execution alias', async () => {
    vi.mocked(agentRunsApi.createTask).mockRejectedValue(new Error('unknown_tool'))
    const card: ShipmentTask = {
      type: 'custom', payload: { tool_id: 'import_excel_to_database', action: 'execute', params: {} },
    }
    await expect(bridge().executeCanonicalTask(card)).rejects.toThrow('unknown_tool')
    expect(agentRunsApi.createTask).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({
      tool_id: 'import_excel_to_database', action: 'execute',
    }))
    expect(agentRunsApi.continueRun).not.toHaveBeenCalled()
  })

  it('deduplicates concurrent preview and confirmation and reads the original run thereafter', async () => {
    let resolve!: (value: AgentRunResponse) => void
    vi.mocked(agentRunsApi.createTask).mockReturnValue(new Promise(done => { resolve = done }))
    vi.mocked(agentRunsApi.getRun).mockResolvedValue(receipt('completed', { node_outputs: { write: { success: true, order_id: 41 } } }))
    const api = bridge(), card = task()
    const staged = api.stageCanonicalTask(card)
    const executing = api.executeCanonicalTask(card)
    resolve(receipt('queued'))
    await staged
    expect(await (await executing)!.json()).toMatchObject({ execution_state: 'queued', success: false, run_id: 'original-run' })
    const completed = await api.executeCanonicalTask(card)
    expect(completed?.ok).toBe(true)
    expect(await completed!.json()).toMatchObject({ execution_state: 'completed', order_id: 41 })
    expect(agentRunsApi.createTask).toHaveBeenCalledTimes(1)
    expect(agentRunsApi.getRun).toHaveBeenCalledExactlyOnceWith('original-run')
  })

  it.each(['queued', 'running', 'waiting_user', 'paused', 'blocked', 'unknown'])('preserves %s without claiming failure or completion', async status => {
    vi.mocked(agentRunsApi.createTask).mockResolvedValue(receipt(status))
    const response = await bridge().executeCanonicalTask(task())
    expect(response?.ok).toBe(false)
    expect(await response!.json()).toMatchObject({ success: false, execution_state: status, run_id: 'original-run', task_id: 'original-task' })
    expect(agentRunsApi.continueRun).not.toHaveBeenCalled()
  })

  it('does not trust completed when the write receipt requires reconciliation', async () => {
    vi.mocked(agentRunsApi.createTask).mockResolvedValue(receipt('completed', { node_outputs: { write: { success: true, requires_reconciliation: true } } }))
    const response = await bridge().executeCanonicalTask(task())
    expect(response?.ok).toBe(false)
    expect(await response!.json()).toMatchObject({ execution_state: 'unknown', requires_reconciliation: true, success: false })
  })

  it('rejects another run receipt instead of replacing the original execution', async () => {
    vi.mocked(agentRunsApi.createTask).mockResolvedValue(receipt('queued'))
    vi.mocked(agentRunsApi.getRun).mockResolvedValue({ ...receipt('completed'), data: { ...receipt('completed').data!, run_id: 'other-run' } })
    const api = bridge(), card = task()
    await api.stageCanonicalTask(card)
    await expect(api.executeCanonicalTask(card)).rejects.toThrow('原任务回执不匹配')
    expect(agentRunsApi.createTask).toHaveBeenCalledTimes(1)
  })

  it.each(['staged', 'in-flight'])('does not approve the %s quantity after the user edits the shipment preview', async mode => {
    const waiting = { ...receipt('waiting_user'), approval: { grant: 'original-grant' } } as AgentRunResponse
    let release!: (value: AgentRunResponse) => void
    vi.mocked(agentRunsApi.createTask).mockReturnValueOnce(mode === 'in-flight' ? new Promise(resolve => { release = resolve }) : Promise.resolve(waiting))
      .mockRejectedValueOnce(Object.assign(new Error('任务状态冲突'), { status: 409 }))
    vi.mocked(agentRunsApi.getRun).mockResolvedValue(waiting)
    vi.mocked(agentRunsApi.continueRun).mockResolvedValue(receipt('completed'))
    const card = task(), api = bridge()
    card.payload!.params = { unit_name: '客户甲', products: [{ model_number: '9803', quantity_tins: 1, tin_spec: 28, unit_price: 10 }] }
    const staged = api.stageCanonicalTask(card)
    if (mode === 'staged') await staged
    const shipment = useShipmentTask({ addAndSaveMessage: vi.fn().mockResolvedValue(undefined) }, ref(card))
    expect(await shipment.handleModifyCommand('改成 9803 2桶 规格 28')).toBe(true)

    const confirming = api.executeCanonicalTask(card, card.payload!.params)
    if (mode === 'in-flight') release(waiting)
    const response = await confirming

    expect(card.items?.[0]).toMatchObject({ 桶数: 2, 总价: '560.00' })
    expect(agentRunsApi.continueRun).not.toHaveBeenCalled()
    expect(agentRunsApi.createTask).toHaveBeenLastCalledWith(expect.objectContaining({
      task_id: 'original-task', params: expect.objectContaining({ products: [expect.objectContaining({ quantity_tins: 2 })] }),
    }))
    expect(await response!.json()).toMatchObject({ success: false, execution_state: 'waiting_user', message: expect.stringContaining('重新预演') })
    expect(card).toMatchObject({ agentTaskId: 'original-task', agentRunId: 'original-run' })
    expect(agentRunsApi.cancelRun).not.toHaveBeenCalled()
  })

  it('uses the same server fingerprint check for a changed purchase request', async () => {
    const waiting = { ...receipt('waiting_user'), approval: { grant: 'purchase-grant' } } as AgentRunResponse
    vi.mocked(agentRunsApi.createTask).mockResolvedValueOnce(waiting)
      .mockRejectedValueOnce(Object.assign(new Error('任务状态冲突'), { status: 409 }))
    vi.mocked(agentRunsApi.getRun).mockResolvedValue(waiting)
    vi.mocked(agentRunsApi.continueRun).mockResolvedValue(receipt('completed'))
    const card: ShipmentTask = { type: 'custom', payload: { tool_id: 'purchase', action: 'create_order', params: {} } }
    const api = bridge()
    await api.stageCanonicalTask(card, { supplier_id: 1, items: [{ material_id: 8, quantity: 1 }] })

    const response = await api.executeCanonicalTask(card, { supplier_id: 2, items: [{ material_id: 8, quantity: 4 }] })

    expect(agentRunsApi.continueRun).not.toHaveBeenCalled()
    expect(agentRunsApi.createTask).toHaveBeenLastCalledWith(expect.objectContaining({
      task_id: 'original-task', tool_id: 'purchase', action: 'create_order', params: { supplier_id: 2, items: [{ material_id: 8, quantity: 4 }] },
    }))
    expect(await response!.json()).toMatchObject({ success: false, execution_state: 'waiting_user' })
    expect(card).toMatchObject({ agentTaskId: 'original-task', agentRunId: 'original-run' })
  })

  it('recovers the original task ID and only approves with its freshly revalidated grant', async () => {
    const waiting = { ...receipt('waiting_user'), approval: { grant: 'old-grant' } } as AgentRunResponse
    waiting.data!.metadata = { task_context: { task_id: 'saved-task' } }
    vi.mocked(agentRunsApi.getRun).mockResolvedValue(waiting)
    vi.mocked(agentRunsApi.createTask).mockResolvedValue({ ...waiting, deduplicated: true, approval: { grant: 'fresh-grant' } } as AgentRunResponse)
    vi.mocked(agentRunsApi.continueRun).mockResolvedValue(receipt('completed'))
    const card = Object.assign(task(), { agentRunId: 'original-run' })

    expect((await bridge().executeCanonicalTask(card))!.ok).toBe(true)

    expect(agentRunsApi.createTask).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ task_id: 'saved-task' }))
    expect(agentRunsApi.continueRun).toHaveBeenCalledExactlyOnceWith('original-run', {
      approval_grant: 'fresh-grant', runtime_context: { source: 'chat_task_card_approval' },
    })
    expect(card).toMatchObject({ agentTaskId: 'saved-task', agentRunId: 'original-run' })
  })

  it.each(['missing', 'mismatched'])('does not invent an identity for a %s original task ID', async mode => {
    const waiting = { ...receipt('waiting_user'), approval: { grant: 'real-grant' } } as AgentRunResponse
    if (mode === 'mismatched') waiting.data!.metadata = { task_context: { task_id: 'actual-task' } }
    vi.mocked(agentRunsApi.getRun).mockResolvedValue(waiting)
    const card = Object.assign(task(), { agentRunId: 'original-run', ...(mode === 'mismatched' ? { agentTaskId: 'wrong-task' } : {}) })

    const response = await bridge().executeCanonicalTask(card)

    expect(await response!.json()).toMatchObject({ success: false, execution_state: 'waiting_user', message: expect.stringContaining('原任务标识') })
    expect(agentRunsApi.createTask).not.toHaveBeenCalled()
    expect(agentRunsApi.continueRun).not.toHaveBeenCalled()
    expect(card.agentRunId).toBe('original-run')
  })

  it('retains the original waiting task when fingerprint readback is unavailable', async () => {
    const waiting = { ...receipt('waiting_user'), approval: { grant: 'real-grant' } } as AgentRunResponse
    vi.mocked(agentRunsApi.getRun).mockResolvedValue(waiting)
    vi.mocked(agentRunsApi.createTask).mockRejectedValue(new Error('network lost'))
    const card = Object.assign(task(), { agentRunId: 'original-run', agentTaskId: 'original-task' })

    const response = await bridge().executeCanonicalTask(card)

    expect(await response!.json()).toMatchObject({ success: false, message: expect.stringContaining('无法核对') })
    expect(agentRunsApi.continueRun).not.toHaveBeenCalled()
    expect(card).toMatchObject({ agentRunId: 'original-run', agentTaskId: 'original-task' })
  })

  it('rejects a different run returned by the same-task fingerprint request', async () => {
    const waiting = { ...receipt('waiting_user'), approval: { grant: 'real-grant' } } as AgentRunResponse
    vi.mocked(agentRunsApi.getRun).mockResolvedValue(waiting)
    vi.mocked(agentRunsApi.createTask).mockResolvedValue({ ...waiting, data: { ...waiting.data!, run_id: 'other-run' } })
    const card = Object.assign(task(), { agentRunId: 'original-run', agentTaskId: 'original-task' })

    await expect(bridge().executeCanonicalTask(card)).rejects.toThrow('原任务回执不匹配')

    expect(agentRunsApi.continueRun).not.toHaveBeenCalled()
    expect(card.agentRunId).toBe('original-run')
  })

  it('does not approve a waiting receipt with unresolved effects even if a grant is present', async () => {
    vi.mocked(agentRunsApi.getRun).mockResolvedValue({ ...receipt('waiting_user', { requires_reconciliation: true }), approval: { grant: 'real-grant' } } as AgentRunResponse)
    const card = Object.assign(task(), { agentRunId: 'original-run', agentTaskId: 'original-task' })

    expect(await (await bridge().executeCanonicalTask(card))!.json()).toMatchObject({ execution_state: 'unknown', success: false })

    expect(agentRunsApi.createTask).not.toHaveBeenCalled()
    expect(agentRunsApi.continueRun).not.toHaveBeenCalled()
  })

  it.each(['replace', 'nested'])('does not approve a %s edit while the server checks the original request', async mode => {
    const waiting = { ...receipt('waiting_user'), approval: { grant: 'real-grant' } } as AgentRunResponse
    vi.mocked(agentRunsApi.getRun).mockResolvedValue(waiting)
    let release!: (value: AgentRunResponse) => void
    vi.mocked(agentRunsApi.createTask).mockReturnValue(new Promise(resolve => { release = resolve }))
    const card = Object.assign(task(), { agentRunId: 'original-run', agentTaskId: 'original-task' })
    card.payload!.params = { products: [{ quantity_tins: 1 }] }
    const pending = bridge().executeCanonicalTask(card)
    await vi.waitFor(() => expect(agentRunsApi.createTask).toHaveBeenCalledOnce())
    if (mode === 'replace') card.payload = { ...card.payload, params: { products: [{ quantity_tins: 3 }] } }
    else card.payload!.params!.products![0].quantity_tins = 3
    release(waiting)

    expect(await (await pending)!.json()).toMatchObject({ success: false, message: expect.stringContaining('确认期间已变化') })
    expect(agentRunsApi.continueRun).not.toHaveBeenCalled()
  })

  it.each(['running', 'unknown', 'cancelled'])('retains task identity until cancellation is confirmed: %s', async status => {
    vi.mocked(agentRunsApi.createTask).mockResolvedValue(receipt('waiting_user'))
    const cancelled = receipt(status)
    cancelled.data!.steps = [{ step_id: 'write', node_id: 'write', tool_id: 'shipment_orders', action: 'generate', status: 'skipped', output: {}, attempt_count: 0 }]
    cancelled.data!.tool_calls = []
    vi.mocked(agentRunsApi.cancelRun).mockResolvedValue(cancelled)
    vi.mocked(agentRunsApi.getRun).mockResolvedValue(receipt(status))
    const api = bridge(), card = task()
    await api.stageCanonicalTask(card)
    api.invalidateStagedTask(card, 'changed-number')
    await new Promise(resolve => setTimeout(resolve, 0))
    if (status === 'cancelled') {
      expect(card).not.toHaveProperty('agentRunId')
      card.customOrderNumber = 'changed-number'
      await api.stageCanonicalTask(card)
      expect(agentRunsApi.createTask).toHaveBeenLastCalledWith(expect.objectContaining({ params: { order_number: 'changed-number' } }))
      expect(agentRunsApi.createTask).toHaveBeenCalledTimes(2)
    } else {
      expect(card).toHaveProperty('agentRunId', 'original-run')
      expect(await (await api.executeCanonicalTask(card))!.json()).toMatchObject({ execution_state: status, run_id: 'original-run' })
      expect(agentRunsApi.createTask).toHaveBeenCalledTimes(1)
      expect(agentRunsApi.continueRun).not.toHaveBeenCalled()
    }
  })

  it.each(['missing-evidence', 'tool-call', 'completed-step', 'started-step'])('does not restage a cancelled run with %s', async evidence => {
    const cancelled = receipt('cancelled')
    if (evidence !== 'missing-evidence') {
      cancelled.data!.steps = [{ step_id: 'write', node_id: 'write', tool_id: 'shipment_orders', action: 'generate', status: evidence === 'completed-step' ? 'completed' : 'skipped', ...(evidence === 'started-step' ? { started_at: '2026-11-23T10:00:00Z' } : {}) }]
      cancelled.data!.tool_calls = evidence === 'tool-call' ? [{ call_id: 'write-call', status: 'completed' }] : []
    }
    vi.mocked(agentRunsApi.createTask).mockResolvedValue(receipt('waiting_user'))
    vi.mocked(agentRunsApi.cancelRun).mockResolvedValue(cancelled)
    vi.mocked(agentRunsApi.getRun).mockResolvedValue(cancelled)
    const api = bridge(), card = task()
    await api.stageCanonicalTask(card)
    api.invalidateStagedTask(card, 'changed-number')
    await new Promise(resolve => setTimeout(resolve, 0))

    await api.executeCanonicalTask(card)

    expect(card).toMatchObject({ agentRunId: 'original-run', agentTaskId: 'original-task' })
    expect(agentRunsApi.createTask).toHaveBeenCalledTimes(1)
    expect(agentRunsApi.continueRun).not.toHaveBeenCalled()
  })
})
