import { describe, expect, it, vi, beforeEach } from 'vitest'

const agentRunsApiMock = vi.hoisted(() => ({
  listEvents: vi.fn(),
  getRun: vi.fn(),
}))

vi.mock('@/api/agentRuns', () => ({
  default: agentRunsApiMock,
}))

import { buildAgentRunTaskUpdate, extractAgentRunId, useAgentRunEventSync } from './useAgentRunEvents'
import { isFirstAiTaskPending, queueFirstAiTaskPrompt, readProductFlowCompleted } from '@/constants/productFlow'

describe('useAgentRunEvents', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    agentRunsApiMock.getRun.mockRejectedValue(new Error('not configured'))
  })

  it('extracts run id from common response shapes', () => {
    expect(extractAgentRunId({ run_id: 'run_root' })).toBe('run_root')
    expect(extractAgentRunId({ data: { run_id: 'run_data' } })).toBe('run_data')
    expect(extractAgentRunId({ data: { agent_run: { run_id: 'run_nested' } } })).toBe('run_nested')
    expect(extractAgentRunId({})).toBe('')
  })

  it('does not turn an ordinary chat lifecycle into a task', () => {
    expect(
      buildAgentRunTaskUpdate({
        runId: 'run_chat_only',
        events: [
          { event_id: 'evt_1', run_id: 'run_chat_only', event_type: 'planner.started' },
          {
            event_id: 'evt_2',
            run_id: 'run_chat_only',
            event_type: 'run.completed',
            message: '完成',
          },
        ],
      }),
    ).toBeNull()
  })

  it('maps a confirmed tool result to a successful task update', () => {
    const update = buildAgentRunTaskUpdate({
      runId: 'run_1',
      userText: '查数据库产品 XG-5003',
      messageRef: '2',
      events: [
        { event_id: 'evt_1', run_id: 'run_1', event_type: 'planner.started' },
        { event_id: 'evt_2', run_id: 'run_1', event_type: 'tool.completed', message: '查询完成' },
        { event_id: 'evt_3', run_id: 'run_1', event_type: 'run.completed', message: '完成' },
      ],
    })

    expect(update).toMatchObject({
      id: 'agent_run_1',
      source: 'agent',
      status: 'success',
      progress: 100,
      title: expect.stringContaining('智能任务'),
      summary: '智能任务执行完成',
    })
    expect(update?.payload?.lastAgentEventId).toBe('evt_3')
    expect(String(update?.title)).not.toContain('Agent')
  })

  it('sanitizes legacy backend event messages before showing them to users', () => {
    const update = buildAgentRunTaskUpdate({
      runId: 'run_legacy',
      events: [
        {
          event_id: 'evt_legacy',
          run_id: 'run_legacy',
          event_type: 'run.completed',
          message: 'Legacy planner run 执行完成',
        },
      ],
    })
    expect(update).toBeNull()
  })

  it('fetches run events and upserts a task panel row for multi-tool runs', async () => {
    agentRunsApiMock.listEvents.mockResolvedValueOnce({
      success: true,
      data: [
        { event_id: 'evt_1', run_id: 'run_1', event_type: 'planner.completed' },
        {
          event_id: 'evt_2',
          run_id: 'run_1',
          event_type: 'tool.started',
          message: '开始执行工具',
          data: { node_id: 'n1', tool_id: 't1' },
        },
        {
          event_id: 'evt_3',
          run_id: 'run_1',
          event_type: 'tool.started',
          message: '开始执行工具',
          data: { node_id: 'n2', tool_id: 't2' },
        },
      ],
    })
    const upsertTask = vi.fn()
    const sync = useAgentRunEventSync({
      upsertTask,
      getLastAiMessageRef: () => '5',
    })

    await sync.syncAgentRunFromPayload({ data: { run_id: 'run_1' } }, '查产品')

    expect(agentRunsApiMock.listEvents).toHaveBeenCalledWith('run_1', {})
    expect(upsertTask).toHaveBeenCalledWith(
      expect.objectContaining({
        id: 'agent_run_1',
        status: 'running',
        messageRef: '5',
      }),
    )
  })

  it('keeps prior tool evidence when later polling returns only terminal events', async () => {
    agentRunsApiMock.listEvents
      .mockResolvedValueOnce({
        success: true,
        data: [{ event_id: 'evt_tool', run_id: 'run_1', event_type: 'tool.completed' }],
      })
      .mockResolvedValueOnce({
        success: true,
        data: [{ event_id: 'evt_done', run_id: 'run_1', event_type: 'run.completed' }],
      })
    const upsertTask = vi.fn()
    const sync = useAgentRunEventSync({ upsertTask })

    await sync.syncAgentRunEvents('run_1', '查产品')
    await sync.syncAgentRunEvents('run_1', '查产品')

    expect(agentRunsApiMock.listEvents).toHaveBeenLastCalledWith('run_1', {
      after_event_id: 'evt_tool',
    })
    expect(upsertTask).toHaveBeenLastCalledWith(
      expect.objectContaining({
        status: 'success',
        payload: expect.objectContaining({ lastAgentEventId: 'evt_done' }),
      }),
    )
  })

  it('removes a stale task row when a run has no execution evidence', async () => {
    agentRunsApiMock.listEvents.mockResolvedValueOnce({
      success: true,
      data: [{ event_id: 'evt_done', run_id: 'run_plain', event_type: 'run.completed' }],
    })
    const upsertTask = vi.fn()
    const removeTask = vi.fn()
    const sync = useAgentRunEventSync({ upsertTask, removeTask })

    await sync.syncAgentRunEvents('run_plain', '删除侯雪梅')

    expect(upsertTask).not.toHaveBeenCalled()
    expect(removeTask).toHaveBeenCalledWith('agent_run_plain')
  })

  it('skips task panel upsert for single successful customers.query tool', async () => {
    agentRunsApiMock.listEvents.mockResolvedValueOnce({
      success: true,
      data: [
        {
          event_id: 'evt_1',
          run_id: 'run_c',
          event_type: 'run.created',
          message: 'Legacy planner 工具调用已进入 AgentRun 追踪',
        },
        {
          event_id: 'evt_2',
          run_id: 'run_c',
          event_type: 'tool.started',
          data: { node_id: 'n1', tool_id: 'customers', action: 'query' },
        },
        {
          event_id: 'evt_3',
          run_id: 'run_c',
          event_type: 'tool.completed',
          data: { node_id: 'n1', tool_id: 'customers' },
        },
        {
          event_id: 'evt_4',
          run_id: 'run_c',
          event_type: 'run.completed',
          message: 'Legacy planner 工具调用追踪完成',
        },
      ],
    })
    const upsertTask = vi.fn()
    const sync = useAgentRunEventSync({ upsertTask })
    await sync.syncAgentRunFromPayload({ data: { run_id: 'run_c' } }, '查客户')
    expect(upsertTask).not.toHaveBeenCalled()
  })

  it('closes the seeded onboarding only after the bound run returns all three completed tools', async () => {
    queueFirstAiTaskPrompt('这是我的新手第一单，请创建演示出货单')
    agentRunsApiMock.listEvents.mockResolvedValueOnce({
      success: true,
      data: [{ event_id: 'evt_done', run_id: 'run_first', event_type: 'run.completed' }],
    })
    agentRunsApiMock.getRun.mockResolvedValueOnce({
      success: true,
      data: {
        run_id: 'run_first',
        user_id: '7',
        message: '新手第一单',
        status: 'completed',
        intent: 'onboarding_first_order',
        steps: [
          {
            step_id: 's1',
            node_id: 'n1',
            tool_id: 'business_db',
            action: 'read',
            status: 'completed',
            params: { entity: 'customers' },
            output: { success: true },
          },
          {
            step_id: 's2',
            node_id: 'n2',
            tool_id: 'business_db',
            action: 'read',
            status: 'completed',
            params: { entity: 'products' },
            output: { success: true },
          },
          {
            step_id: 's3',
            node_id: 'n3',
            tool_id: 'business_db',
            action: 'write',
            status: 'completed',
            params: { entity: 'shipment_records' },
            output: { success: true },
          },
        ],
      },
    })
    const sync = useAgentRunEventSync({ upsertTask: vi.fn() })

    await sync.syncAgentRunFromPayload(
      { data: { run_id: 'run_first' } },
      '这是我的新手第一单，请创建演示出货单',
    )

    expect(readProductFlowCompleted()).toBe(true)
    expect(isFirstAiTaskPending()).toBe(false)
  })
})
