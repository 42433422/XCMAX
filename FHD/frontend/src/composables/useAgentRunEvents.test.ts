import { describe, expect, it, vi, beforeEach } from 'vitest'

const agentRunsApiMock = vi.hoisted(() => ({
  listEvents: vi.fn(),
  getRun: vi.fn(),
}))

vi.mock('@/api/agentRuns', () => ({
  default: agentRunsApiMock,
}))

import { buildAgentRunTaskUpdate, extractAgentRunId, useAgentRunEventSync, waitForAgentRunTerminal } from './useAgentRunEvents'
import { isFirstAiTaskPending, queueFirstAiTaskPrompt, readProductFlowCompleted } from '@/constants/productFlow'
import { setRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime'

describe('useAgentRunEvents', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    setRuntimeTenantStorageScopeInput({ tenantId: 1, localUserId: 1 })
    agentRunsApiMock.listEvents.mockReset()
    agentRunsApiMock.getRun.mockReset().mockRejectedValue(new Error('not configured'))
  })

  it('extracts run id from common response shapes', () => {
    expect(extractAgentRunId({ run_id: 'run_root' })).toBe('run_root')
    expect(extractAgentRunId({ data: { run_id: 'run_data' } })).toBe('run_data')
    expect(extractAgentRunId({ data: { agent_run: { run_id: 'run_nested' } } })).toBe('run_nested')
    expect(extractAgentRunId({})).toBe('')
  })

  it('retains the durable event cursor across a transient read failure', async () => {
    vi.useFakeTimers()
    const terminal = { run_id: 'original', status: 'paused' }
    agentRunsApiMock.listEvents
      .mockResolvedValueOnce({ data: [{ event_id: 'e1' }] })
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({ data: [{ event_id: 'e2' }] })
    agentRunsApiMock.getRun
      .mockResolvedValueOnce({ data: { run_id: 'original', status: 'running' } })
      .mockResolvedValueOnce({ data: terminal })
    try {
      const pending = waitForAgentRunTerminal(' original ')
      await vi.advanceTimersByTimeAsync(4000)
      await expect(pending).resolves.toEqual(terminal)
      expect(agentRunsApiMock.listEvents.mock.calls).toEqual([
        ['original', {}], ['original', { after_event_id: 'e1' }], ['original', { after_event_id: 'e1' }],
      ])
    } finally { vi.useRealTimers() }
  })

  it.each(['events', 'detail'])('stops following when ownership ends during %s', async stage => {
    let current = true
    agentRunsApiMock.listEvents.mockImplementationOnce(async () => {
      if (stage === 'events') current = false
      return { data: [] }
    })
    agentRunsApiMock.getRun.mockImplementationOnce(async () => {
      current = false
      return { data: { run_id: 'original', status: 'completed' } }
    })
    await expect(waitForAgentRunTerminal('original', () => current)).resolves.toBeNull()
    if (stage === 'events') expect(agentRunsApiMock.getRun).not.toHaveBeenCalled()
  })

  it('does not project missing text or attach another run’s terminal receipt', async () => {
    vi.useFakeTimers()
    agentRunsApiMock.listEvents.mockResolvedValueOnce({ data: [] })
    agentRunsApiMock.getRun.mockResolvedValueOnce({ data: { run_id: 'unrelated', status: 'completed' } })
    try {
      const pending = waitForAgentRunTerminal('original', () => true, 100)
      await vi.advanceTimersByTimeAsync(2000)
      await expect(pending).resolves.toBeNull()
      await expect(waitForAgentRunTerminal(' ')).resolves.toBeNull()
    } finally { vi.useRealTimers() }
  })

  it.each(['events', 'run', 'error', 'generation'])('does not apply a late %s result to the next owner or generation', async stage => {
    let current = true
    const switchOwner = () => {
      if (stage === 'generation') current = false
      else setRuntimeTenantStorageScopeInput({ tenantId: 1, localUserId: 2 })
    }
    agentRunsApiMock.listEvents.mockImplementation(async () => {
      if (stage !== 'run') switchOwner()
      if (stage === 'error') throw new Error('old account unavailable')
      return { data: [{ event_id: 'e', run_id: 'r', event_type: 'tool.completed' }] }
    })
    agentRunsApiMock.getRun.mockImplementation(async () => { switchOwner(); return { data: undefined } })
    const upsertTask = vi.fn(), removeTask = vi.fn()
    await useAgentRunEventSync({ upsertTask, removeTask }).syncAgentRunEvents('r', '', () => current)
    expect(upsertTask).not.toHaveBeenCalled()
    expect(removeTask).not.toHaveBeenCalled()
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

  it.each([
    ['completed', 'success', true], ['failed', 'failed', true], ['blocked', 'blocked', false],
    ['waiting_user', 'queued', false], ['paused', 'paused', false], ['cancelled', 'cancelled', true],
    ['rejected', 'blocked', true], ['', 'running', false],
  ])('uses explicit observed status %s in the event-only fallback', (status, expected, terminal) => {
    const update = buildAgentRunTaskUpdate({ runId: 'run-observed', events: [
      { event_id: 'tool', run_id: 'run-observed', event_type: 'tool.completed' },
      { event_id: 'observation', run_id: 'run-observed', event_type: 'run.observed', data: { status } },
    ] })
    expect(update).toMatchObject({ status: expected, payload: { terminal } })
  })

  it('keeps terminal evidence after an observation and clears resolved failure on a successful retry', () => {
    const events = [
      { event_id: 'failed', run_id: 'run-1', event_type: 'tool.failed', message: '第一次超时' },
      { event_id: 'tool', run_id: 'run-1', event_type: 'tool.completed' },
      { event_id: 'done', run_id: 'run-1', event_type: 'run.completed' },
      { event_id: 'observation', run_id: 'run-1', event_type: 'run.observed', data: { status: 'completed' } },
    ]
    expect(buildAgentRunTaskUpdate({ runId: 'run-1', events })).toMatchObject({ status: 'success', error: '', payload: { terminal: true } })
    expect(buildAgentRunTaskUpdate({ runId: 'run-1', events: events.slice(0, 3) }))
      .toMatchObject({ status: 'success', progress: 100, error: '', payload: { terminal: true } })
    expect(buildAgentRunTaskUpdate({ runId: 'run-1', events: [...events.slice(0, 3),
      { ...events[3], event_type: 'run.failed', message: '重试后仍失败' },
    ] })).toMatchObject({ status: 'failed', error: '重试后仍失败', payload: { terminal: true } })
    expect(buildAgentRunTaskUpdate({ runId: 'run-1', events: [events[1], events[2], { ...events[3], data: {} }] }))
      .toMatchObject({ status: 'success', payload: { terminal: true } })
    expect(buildAgentRunTaskUpdate({ runId: 'run-1', events: [events[0], events[3]] }))
      .toMatchObject({ status: 'failed', stage: '未确认执行结果' })
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
    let messageRef = '5'
    const sync = useAgentRunEventSync({
      upsertTask,
      getLastAiMessageRef: () => messageRef,
    })

    const pending = sync.syncAgentRunFromPayload({ data: { run_id: 'run_1' } }, '查产品')
    messageRef = 'next-message'
    await pending

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
