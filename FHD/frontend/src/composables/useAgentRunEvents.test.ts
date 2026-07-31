import { describe, expect, it, vi, beforeEach } from 'vitest'

const agentRunsApiMock = vi.hoisted(() => ({
  listEvents: vi.fn(),
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

  it('skips task panel upsert for trivial legacy chat with no tools', async () => {
    agentRunsApiMock.listEvents.mockResolvedValueOnce({
      success: true,
      data: [
        { event_id: 'evt_1', run_id: 'run_chat', event_type: 'run.created', message: 'Legacy planner run 已创建' },
        { event_id: 'evt_2', run_id: 'run_chat', event_type: 'planner.started' },
        { event_id: 'evt_3', run_id: 'run_chat', event_type: 'planner.completed' },
        { event_id: 'evt_4', run_id: 'run_chat', event_type: 'run.completed', message: 'Legacy planner run 执行完成' },
      ],
    })
    const upsertTask = vi.fn()
    const sync = useAgentRunEventSync({ upsertTask })
    await sync.syncAgentRunFromPayload({ data: { run_id: 'run_chat' } }, '你可以做什么')
    expect(upsertTask).not.toHaveBeenCalled()
  })
})
