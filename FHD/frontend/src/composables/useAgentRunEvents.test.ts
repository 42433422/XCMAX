import { describe, expect, it, vi, beforeEach } from 'vitest'

const agentRunsApiMock = vi.hoisted(() => ({
  listEvents: vi.fn(),
  listRuns: vi.fn(),
  pauseRun: vi.fn(),
  resumeRun: vi.fn(),
  cancelRun: vi.fn(),
  retryRun: vi.fn(),
}))

vi.mock('@/api/agentRuns', () => ({
  default: agentRunsApiMock,
}))

import {
  buildAgentRunTaskUpdate,
  buildOrchestrationTrace,
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

  it('projects database changes and collapses started/completed into one activity row', () => {
    const events = [
      {
        event_id: 'evt_db_started',
        run_id: 'run_db',
        event_type: 'tool.started',
        data: {
          call_id: 'call_db',
          orchestration: {
            kind: 'database_write',
            label: '写入数据库',
            status: 'running',
            tool_id: 'business_db',
            action: 'write',
            databases: [{ database_id: 'products.db', database_name: '客户/产品主库', tables: 'products' }],
            changes: [],
            employees: [],
          },
        },
      },
      {
        event_id: 'evt_db_completed',
        run_id: 'run_db',
        event_type: 'tool.completed',
        data: {
          call_id: 'call_db',
          orchestration: {
            kind: 'database_write',
            label: '写入数据库',
            status: 'completed',
            tool_id: 'business_db',
            action: 'write',
            databases: [{ database_id: 'products.db', database_name: '客户/产品主库', runtime_database: 'products.db', tables: 'products' }],
            changes: [{
              database_name: '客户/产品主库',
              label: '新增产品',
              counts: { created: 1, updated: 0, deleted: 0 },
              items: [{ model_number: 'XG-5003', product_name: '测试产品' }],
            }],
            employees: [],
          },
        },
      },
    ]

    const trace = buildOrchestrationTrace(events)
    expect(trace).toHaveLength(1)
    expect(trace[0].status).toBe('completed')
    expect(trace[0].evidence.databases[0].runtime_database).toBe('products.db')
    expect(trace[0].evidence.changes[0].items?.[0].model_number).toBe('XG-5003')

    const update = buildAgentRunTaskUpdate({ runId: 'run_db', events })
    expect(update.payload?.orchestrationTrace).toEqual(trace)
  })

  it('shows an inconclusive business verification instead of claiming completion', () => {
    const events = [
      {
        event_id: 'evt_tool',
        run_id: 'run_unverified',
        event_type: 'tool.completed',
        data: {
          call_id: 'call_write',
          verification: {
            accepted: true,
            verified: false,
            status: 'inconclusive',
            verifier: 'business_write_receipt',
            reason: '没有返回业务记录 ID',
          },
          orchestration: {
            kind: 'database_write',
            status: 'completed',
            tool_id: 'business_db',
            action: 'write',
            databases: [],
            changes: [],
            employees: [],
          },
        },
      },
      {
        event_id: 'evt_verify',
        run_id: 'run_unverified',
        event_type: 'run.verification_inconclusive',
      },
      {
        event_id: 'evt_done',
        run_id: 'run_unverified',
        event_type: 'run.completed',
      },
    ]

    const trace = buildOrchestrationTrace(events)
    expect(trace[0].status).toBe('inconclusive')
    expect(trace[0].verification?.verified).toBe(false)

    const update = buildAgentRunTaskUpdate({ runId: 'run_unverified', events })
    expect(update.status).toBe('success')
    expect(update.summary).toBe('任务已执行，结果待核验')
    expect(update.payload?.needsVerification).toBe(true)
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

  it('keeps paused runs visible as resumable tasks', () => {
    const update = buildAgentRunTaskUpdate({
      runId: 'run_paused',
      runStatus: 'paused',
      events: [
        { event_id: 'evt_1', run_id: 'run_paused', event_type: 'tool.completed' },
        { event_id: 'evt_2', run_id: 'run_paused', event_type: 'run.paused' },
      ],
    })

    expect(update.status).toBe('paused')
    expect(update.summary).toContain('检查点')
    expect(update.payload?.terminal).toBe(false)
  })

  it('keeps polling after a failed tool is scheduled for retry', () => {
    const update = buildAgentRunTaskUpdate({
      runId: 'run_retrying',
      runStatus: 'retrying',
      events: [
        { event_id: 'evt_1', run_id: 'run_retrying', event_type: 'tool.failed' },
        { event_id: 'evt_2', run_id: 'run_retrying', event_type: 'step.retry_scheduled' },
      ],
    })

    expect(update.status).toBe('running')
    expect(update.progress).toBeLessThan(100)
    expect(update.error).toBe('')
    expect(update.payload?.terminal).toBe(false)
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
    const attachTrace = vi.fn()
    const sync = useAgentRunEventSync({
      upsertTask,
      getLastAiMessageRef: () => '5',
      attachOrchestrationTrace: attachTrace,
    })

    await sync.syncAgentRunFromPayload({ data: { run_id: 'run_1' } }, '查产品')

    expect(agentRunsApiMock.listEvents).toHaveBeenCalledWith('run_1', {})
    expect(upsertTask).toHaveBeenCalledWith(expect.objectContaining({
      id: 'agent_run_1',
      status: 'running',
      messageRef: '5',
    }))
    expect(attachTrace).toHaveBeenCalledWith([])
    sync.dispose()
  })

  it('calls the durable control endpoint and applies its returned snapshot', async () => {
    agentRunsApiMock.pauseRun.mockResolvedValueOnce({
      success: true,
      data: {
        run_id: 'run_control',
        user_id: 'u1',
        message: '后台任务',
        status: 'paused',
        events: [
          {
            event_id: 'evt_pause',
            run_id: 'run_control',
            event_type: 'run.paused',
            message: '后台任务已暂停',
          },
        ],
      },
    })
    const upsertTask = vi.fn()
    const sync = useAgentRunEventSync({ upsertTask })

    await sync.controlAgentRun('run_control', 'pause', 'u1')

    expect(agentRunsApiMock.pauseRun).toHaveBeenCalledWith(
      'run_control',
      { requested_by: 'u1' },
    )
    expect(upsertTask).toHaveBeenCalledWith(expect.objectContaining({
      id: 'agent_run_control',
      status: 'paused',
    }))
    sync.dispose()
  })

  it('reconciles persisted waiting tasks from terminal backend snapshots', async () => {
    const tasks = [
      {
        id: 'agent_run_done',
        title: '智能任务：删除产品',
        type: 'agent_run',
        source: 'agent',
        status: 'queued',
        progress: 85,
        startedAt: 1,
        updatedAt: 1,
        payload: {},
      },
      {
        id: 'plan_done',
        title: '工作流任务：删除产品',
        type: 'workflow',
        source: 'workflow',
        status: 'queued',
        progress: 10,
        startedAt: 1,
        updatedAt: 1,
        payload: {},
      },
    ]
    agentRunsApiMock.listRuns.mockResolvedValueOnce({
      success: true,
      data: [{
        run_id: 'run_done',
        user_id: 'u1',
        message: '删除产品',
        status: 'completed',
        plan_id: 'plan_done',
        events: [
          { event_id: 'evt_wait', run_id: 'run_done', event_type: 'step.waiting_user' },
          { event_id: 'evt_done', run_id: 'run_done', event_type: 'run.completed' },
        ],
      }],
    })
    const upsertTask = vi.fn()
    const sync = useAgentRunEventSync({
      upsertTask,
      getTasks: () => tasks as never,
    })

    await sync.restoreAgentRuns('u1')

    expect(upsertTask).toHaveBeenCalledWith(expect.objectContaining({
      id: 'agent_run_done',
      status: 'success',
      progress: 100,
    }))
    expect(upsertTask).toHaveBeenCalledWith(expect.objectContaining({
      id: 'plan_done',
      status: 'success',
      progress: 100,
      summary: '工作流执行完成',
    }))
    sync.dispose()
  })

  it('reconciles legacy workflow tasks by their original user message', async () => {
    const tasks = [{
      id: 'legacy_random_id',
      title: '工作流任务：删除产品 7',
      type: 'workflow',
      source: 'workflow',
      status: 'queued',
      progress: 10,
      startedAt: 1,
      updatedAt: 1,
      payload: {},
    }]
    agentRunsApiMock.listRuns.mockResolvedValueOnce({
      success: true,
      data: [{
        run_id: 'run_legacy_done',
        user_id: 'u1',
        message: '删除产品 7',
        status: 'completed',
        plan_id: 'different_plan_id',
        events: [
          { event_id: 'evt_done', run_id: 'run_legacy_done', event_type: 'run.completed' },
        ],
      }],
    })
    const upsertTask = vi.fn()
    const sync = useAgentRunEventSync({
      upsertTask,
      getTasks: () => tasks as never,
    })

    await sync.restoreAgentRuns('u1')

    expect(upsertTask).toHaveBeenCalledWith(expect.objectContaining({
      id: 'legacy_random_id',
      status: 'success',
      progress: 100,
    }))
    sync.dispose()
  })

  it('does not flood a fresh task panel with old terminal runs', async () => {
    agentRunsApiMock.listRuns.mockResolvedValueOnce({
      success: true,
      data: [{
        run_id: 'run_old',
        user_id: 'u1',
        message: '旧任务',
        status: 'completed',
        events: [{ event_id: 'evt_done', run_id: 'run_old', event_type: 'run.completed' }],
      }],
    })
    const upsertTask = vi.fn()
    const sync = useAgentRunEventSync({
      upsertTask,
      getTasks: () => [],
    })

    await sync.restoreAgentRuns('u1')

    expect(upsertTask).not.toHaveBeenCalled()
    sync.dispose()
  })
})
