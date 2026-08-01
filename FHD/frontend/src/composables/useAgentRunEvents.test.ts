import { describe, expect, it, vi, beforeEach } from 'vitest'

const agentRunsApiMock = vi.hoisted(() => ({
  listEvents: vi.fn(),
  listRuns: vi.fn(),
}))

vi.mock('@/api/agentRuns', () => ({
  default: agentRunsApiMock,
}))

import {
  buildAgentRunTaskUpdate,
  extractAgentRunId,
  useAgentRunEventSync,
} from './useAgentRunEvents'

describe('useAgentRunEvents', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('extracts run id from common response shapes', () => {
    expect(extractAgentRunId({ run_id: 'run_root' })).toBe('run_root')
    expect(extractAgentRunId({ data: { run_id: 'run_data' } })).toBe('run_data')
    expect(extractAgentRunId({ data: { agent_run: { run_id: 'run_nested' } } })).toBe('run_nested')
    expect(extractAgentRunId({})).toBe('')
  })

  it('maps completed events to a successful task update', () => {
    const update = buildAgentRunTaskUpdate({
      runId: 'run_1',
      userText: '查数据库产品 XG-5003',
      messageRef: '2',
      events: [
        { event_id: 'evt_1', run_id: 'run_1', event_type: 'planner.started' },
        { event_id: 'evt_2', run_id: 'run_1', event_type: 'run.completed', message: '完成' },
      ],
    })

    expect(update.id).toBe('agent_run_1')
    expect(update.source).toBe('agent')
    expect(update.status).toBe('success')
    expect(update.progress).toBe(100)
    expect(update.payload?.lastAgentEventId).toBe('evt_2')
    expect(update.title).toContain('智能任务')
    expect(update.summary).toBe('智能任务执行完成')
    expect(String(update.title)).not.toContain('Agent')
  })

  it('maps cancelled events to a cancelled task update', () => {
    const update = buildAgentRunTaskUpdate({
      runId: 'run_cancelled',
      userText: '删除客户候雪梅',
      events: [
        { event_id: 'evt_1', run_id: 'run_cancelled', event_type: 'step.waiting_user' },
        { event_id: 'evt_2', run_id: 'run_cancelled', event_type: 'run.cancelled' },
      ],
    })

    expect(update.status).toBe('cancelled')
    expect(update.progress).toBe(100)
    expect(update.payload?.terminal).toBe(true)
  })

  it('keeps a completed run successful after a duplicate continue is ignored', () => {
    const update = buildAgentRunTaskUpdate({
      runId: 'run_completed',
      events: [
        { event_id: 'evt_1', run_id: 'run_completed', event_type: 'run.completed' },
        { event_id: 'evt_2', run_id: 'run_completed', event_type: 'run.continue_ignored' },
      ],
    })

    expect(update.status).toBe('success')
    expect(update.payload?.terminal).toBe(true)
    expect(update.stage).toBe('当前没有等待确认的步骤')
  })

  it('maps budget exhaustion to a terminal failed task', () => {
    const update = buildAgentRunTaskUpdate({
      runId: 'run_budget',
      events: [
        { event_id: 'evt_1', run_id: 'run_budget', event_type: 'planner.started' },
        { event_id: 'evt_2', run_id: 'run_budget', event_type: 'budget.exceeded' },
      ],
    })

    expect(update.status).toBe('failed')
    expect(update.progress).toBe(100)
    expect(update.payload?.terminal).toBe(true)
    expect(update.error).toBe('任务预算已超限')
  })

  it('restores durable non-trivial runs after reload', async () => {
    agentRunsApiMock.listRuns.mockResolvedValueOnce({
      success: true,
      data: [{
        run_id: 'run_waiting',
        message: '删除客户候雪梅',
        events: [
          { event_id: 'evt_1', run_id: 'run_waiting', event_type: 'planner.completed' },
          {
            event_id: 'evt_2',
            run_id: 'run_waiting',
            event_type: 'step.waiting_user',
            data: { node_id: 'delete_customer', tool_id: 'customers', action: 'delete' },
          },
        ],
      }],
    })
    const upsertTask = vi.fn()
    const sync = useAgentRunEventSync({ upsertTask })

    const activeRunIds = await sync.restoreRecentAgentRuns('u1')

    expect(agentRunsApiMock.listRuns).toHaveBeenCalledWith({ user_id: 'u1', limit: 20 })
    expect(activeRunIds).toEqual(['run_waiting'])
    expect(upsertTask).toHaveBeenCalledWith(expect.objectContaining({
      id: 'agent_run_waiting',
      status: 'queued',
    }))
  })

  it('sanitizes legacy backend event messages before showing them to users', () => {
    const update = buildAgentRunTaskUpdate({
      runId: 'run_legacy',
      events: [{
        event_id: 'evt_legacy',
        run_id: 'run_legacy',
        event_type: 'run.completed',
        message: 'Legacy planner run 执行完成',
      }],
    })
    expect(update.stage).toBe('智能任务 执行完成')
    expect(String(update.stage)).not.toContain('Legacy')
  })

  it('fetches run events and upserts a task panel row', async () => {
    agentRunsApiMock.listEvents.mockResolvedValueOnce({
      success: true,
      data: [
        { event_id: 'evt_1', run_id: 'run_1', event_type: 'planner.completed' },
        { event_id: 'evt_2', run_id: 'run_1', event_type: 'tool.started', message: '开始执行工具' },
      ],
    })
    const upsertTask = vi.fn()
    const sync = useAgentRunEventSync({
      upsertTask,
      getLastAiMessageRef: () => '5',
    })

    await sync.syncAgentRunFromPayload({ data: { run_id: 'run_1' } }, '查产品')

    expect(agentRunsApiMock.listEvents).toHaveBeenCalledWith('run_1', {})
    expect(upsertTask).toHaveBeenCalledWith(expect.objectContaining({
      id: 'agent_run_1',
      status: 'running',
      messageRef: '5',
    }))
  })
})
