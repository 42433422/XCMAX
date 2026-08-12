import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import GlobalTaskCenter from './GlobalTaskCenter.vue'

const apiMock = vi.hoisted(() => ({
  listTasks: vi.fn(), getTaskRuntime: vi.fn(), getTask: vi.fn(), getRun: vi.fn(),
  continueRun: vi.fn(), pauseRun: vi.fn(), cancelRun: vi.fn(), resumeRun: vi.fn(),
  retryRun: vi.fn(), archiveTask: vi.fn(),
  taskEventStreamPath: vi.fn(() => '/api/agent/tasks/events/stream'),
}))
vi.mock('@/api/agentRuns', () => ({ default: apiMock }))
vi.mock('@/api/core', () => ({ buildFullApiUrl: (path: string) => path }))

const task = {
  task_id: 'task-1', user_id: 'owner', title: '独立工作任务', source: 'agent', task_type: 'agent',
  status: 'waiting_user', attention_state: 'approval_required', attempt: 1, run_count: 1,
  active_run_id: 'run-1', conversation_id: 'chat-1',
  progress: { percent: 0, completed_units: 0, settled_units: 0, total_units: 1, current_unit: 1, stage: '等待审批或用户确认', detail: '查询产品', status: 'waiting_user', attempt: 1, indeterminate: false, basis: 'steps' },
  capabilities: { approve: true, pause: true, cancel: true, retry: false, resume: false, evidence: true },
  execution: { run_id: 'run-1', task_id: 'task-1', user_id: 'owner', state: 'blocked', priority: 100, execution_count: 1, recovery_count: 0 },
  active_run: {
    run_id: 'run-1', user_id: 'owner', message: '执行任务', status: 'waiting_user',
    steps: [{ step_id: 'step-1', node_id: 'query', tool_id: 'products', action: 'query', status: 'waiting_user', idempotent: true }],
    tool_calls: [], artifacts: [], events: [{ event_id: 'event-1', run_id: 'run-1', event_type: 'step.waiting_user', message: '等待确认' }],
  },
}

describe('GlobalTaskCenter', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMock.listTasks.mockResolvedValue({ success: true, data: [task] })
    apiMock.getTaskRuntime.mockResolvedValue({ success: true, data: { running: true, max_workers: 4, active_count: 0, progress: { task_count: 1, active_count: 0, attention_count: 1, completed_count: 0, overall_percent: 0 } } })
    apiMock.getTask.mockResolvedValue({ success: true, data: { ...task, runs: [task.active_run] } })
    apiMock.getRun.mockResolvedValue({ success: true, data: task.active_run, approval: { grant: 'grant-1' } })
    apiMock.continueRun.mockResolvedValue({ success: true, data: { ...task.active_run, status: 'queued' } })
  })

  it('opens globally, shows evidence and performs a real approval action', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/chat', name: 'chat', component: { template: '<div />' } }],
    })
    await router.push('/chat')
    await router.isReady()
    const wrapper = mount(GlobalTaskCenter, {
      global: { plugins: [createPinia(), router], stubs: { Teleport: true } },
    })
    await flushPromises()

    await wrapper.get('.task-center-trigger').trigger('click')
    expect(wrapper.text()).toContain('并发 0/4')
    expect(wrapper.text()).toContain('总进度 0%')
    expect(wrapper.text()).toContain('独立工作任务')
    expect(wrapper.get('[aria-label="独立工作任务进度"]').attributes('aria-valuenow')).toBe('0')

    await wrapper.get('.task-center-item').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('结果证据')
    expect(wrapper.text()).toContain('统一进度')
    expect(wrapper.text()).toContain('已完成 0 / 1 个步骤')
    expect(wrapper.text()).toContain('可安全恢复')

    const approval = wrapper.findAll('.task-center-actions button').find((button) => button.text() === '批准并执行')
    expect(approval).toBeDefined()
    await approval!.trigger('click')
    await flushPromises()
    expect(apiMock.continueRun).toHaveBeenCalledWith('run-1', { approval_grant: 'grant-1' })

    wrapper.unmount()
  })
})
