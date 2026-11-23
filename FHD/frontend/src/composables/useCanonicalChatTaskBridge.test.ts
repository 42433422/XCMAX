import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import agentRunsApi, { type AgentRunResponse } from '@/api/agentRuns'
import { useCanonicalChatTaskBridge } from './useCanonicalChatTaskBridge'
import type { ShipmentTask } from './useShipmentTask'

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

  it.each(['running', 'unknown', 'cancelled'])('retains task identity until cancellation is confirmed: %s', async status => {
    vi.mocked(agentRunsApi.createTask).mockResolvedValue(receipt('waiting_user'))
    vi.mocked(agentRunsApi.cancelRun).mockResolvedValue(receipt(status))
    vi.mocked(agentRunsApi.getRun).mockResolvedValue(receipt(status))
    const api = bridge(), card = task()
    await api.stageCanonicalTask(card)
    api.invalidateStagedTask(card, 'changed-number')
    await new Promise(resolve => setTimeout(resolve, 0))
    if (status === 'cancelled') {
      expect(card).not.toHaveProperty('agentRunId')
    } else {
      expect(card).toHaveProperty('agentRunId', 'original-run')
      expect(await (await api.executeCanonicalTask(card))!.json()).toMatchObject({ execution_state: status, run_id: 'original-run' })
      expect(agentRunsApi.createTask).toHaveBeenCalledTimes(1)
      expect(agentRunsApi.continueRun).not.toHaveBeenCalled()
    }
  })
})
