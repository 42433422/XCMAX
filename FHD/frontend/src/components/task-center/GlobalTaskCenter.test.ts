import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import GlobalTaskCenter from './GlobalTaskCenter.vue'

const apiMock = vi.hoisted(() => ({
  listTasks: vi.fn(),
  getTaskRuntime: vi.fn(),
  getTask: vi.fn(),
  getRun: vi.fn(),
  continueRun: vi.fn(),
  pauseRun: vi.fn(),
  cancelRun: vi.fn(),
  resumeRun: vi.fn(),
  retryRun: vi.fn(),
  archiveTask: vi.fn(),
  markTaskRead: vi.fn(),
  taskEventStreamPath: vi.fn(() => '/api/agent/tasks/events/stream'),
}))
vi.mock('@/api/agentRuns', () => ({ default: apiMock }))
vi.mock('@/api/core', () => ({ buildFullApiUrl: (path: string) => path }))

const approvalWorkspace = {
  task_id: 'task-approval', user_id: 'owner', title: '客户B销售开票', source: 'agent', task_type: 'agent',
  status: 'waiting_user', attention_state: 'approval_required', approval_required: true, unread_count: 0,
  attempt: 1, run_count: 1, active_run_id: 'run-approval', conversation_id: 'chat-approval',
  progress: { percent: 45, completed_units: 1, settled_units: 1, total_units: 2, current_unit: 2, stage: '等待审批', detail: '确认开票', status: 'waiting_user', attempt: 1, indeterminate: false, basis: 'steps' },
}
const unreadWorkspace = {
  task_id: 'task-result', user_id: 'owner', title: '月度经营报告', source: 'agent', task_type: 'agent',
  status: 'completed', attention_state: 'result_unread', approval_required: false, unread_count: 1,
  attempt: 1, run_count: 1, active_run_id: 'run-result', conversation_id: 'chat-result',
  progress: { percent: 100, completed_units: 2, settled_units: 2, total_units: 2, current_unit: 2, stage: '任务完成', detail: '', status: 'completed', attempt: 1, indeterminate: false, basis: 'steps' },
}

describe('GlobalTaskCenter', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMock.listTasks.mockResolvedValue({ success: true, data: [approvalWorkspace, unreadWorkspace] })
    apiMock.getTaskRuntime.mockResolvedValue({
      success: true,
      data: { running: true, max_workers: 4, active_count: 0 },
    })
    apiMock.markTaskRead.mockResolvedValue({
      success: true,
      data: { ...unreadWorkspace, attention_state: '', unread_count: 0 },
    })
  })

  it('renders the task center as a workspace list with status, progress, unread and approval', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', name: 'chat', component: { template: '<div />' } },
        { path: '/workspaces/:taskId', name: 'task-workspace', component: { template: '<div />' } },
      ],
    })
    await router.push('/')
    await router.isReady()
    const wrapper = mount(GlobalTaskCenter, {
      global: { plugins: [createPinia(), router], stubs: { Teleport: true } },
    })
    await flushPromises()

    await wrapper.get('.task-center-trigger').trigger('click')
    expect(wrapper.text()).toContain('工作区')
    expect(wrapper.text()).toContain('2 个工作区')
    expect(wrapper.text()).toContain('客户B销售开票')
    expect(wrapper.text()).toContain('月度经营报告')
    expect(wrapper.text()).toContain('待审批')
    expect(wrapper.text()).toContain('1 未读')
    expect(wrapper.get('[aria-label="客户B销售开票工作区进度"]').attributes('aria-valuenow')).toBe('45')

    const unreadFilter = wrapper.findAll('.task-center-filters button').find((button) => button.text().includes('未读'))
    await unreadFilter!.trigger('click')
    expect(wrapper.findAll('.task-center-item')).toHaveLength(1)

    await wrapper.get('.task-center-item').trigger('click')
    await flushPromises()
    expect(apiMock.markTaskRead).toHaveBeenCalledWith('task-result')
    expect(router.currentRoute.value.name).toBe('task-workspace')
    expect(router.currentRoute.value.params.taskId).toBe('task-result')
    expect(router.currentRoute.value.query.conversation).toBe('chat-result')
    expect(wrapper.find('.task-center-drawer').exists()).toBe(false)

    wrapper.unmount()
  })
})
