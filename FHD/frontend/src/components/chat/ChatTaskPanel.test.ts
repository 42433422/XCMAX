import { afterEach, describe, expect, it } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import ChatTaskPanel from './ChatTaskPanel.vue'
import type { TaskItem } from '@/composables/useChatPersistence'

let wrapper: VueWrapper | undefined
const task: TaskItem = { id: 'task-1', type: 'workflow', title: '验收任务', source: 'workflow', status: 'running', startedAt: 1, updatedAt: 2 }
async function open(overrides: Partial<InstanceType<typeof ChatTaskPanel>['$props']> = {}) {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/', component: { template: '<div />' } },
    { path: '/tasks/:taskId', name: 'task-workspace', component: { template: '<div />' } },
  ] })
  await router.push('/')
  wrapper = mount(ChatTaskPanel, { props: {
    currentTask: null, taskList: [], filteredTaskList: [], activeTaskId: '', expandedTaskIds: [], taskFilter: 'all',
    latestAssistantPush: null, pushCopied: false, orderNumberFetching: false, isExecuting: false,
    taskTableColumns: [], taskTableItems: [], taskOrderNumber: '',
    formatTaskTime: (value) => `time:${value}`, formatTaskSourceLabel: (value) => `source:${value}`,
    workflowTaskDotStatusClass: (item) => item.status, workflowTaskDotTitle: (item) => item.status,
    ...overrides,
  }, global: { plugins: [router] } })
  await flushPromises()
  return { view: wrapper, router }
}
afterEach(() => { wrapper?.unmount(); wrapper = undefined })

describe('Visible Mac conversation task panel', () => {
  it('shows an empty state, or the assistant push with copy and open actions', async () => {
    const { view } = await open()
    expect(view.get('.empty-state').text()).not.toBe('')
    await view.setProps({ latestAssistantPush: { title: '库存提醒', description: '包装盒库存不足' } })
    expect(view.text()).toContain('包装盒库存不足')
    await view.findAll('.task-actions button')[0].trigger('click')
    await view.findAll('.task-actions button')[1].trigger('click')
    expect(view.emitted('copy-assistant-push')).toEqual([[]])
    expect(view.emitted('open-assistant-float')).toEqual([[]])
    await view.setProps({ pushCopied: true, latestAssistantPush: { title: '', description: '' } })
    expect(view.text()).toContain('已复制')
    expect(view.get('.task-header').text()).not.toBe('')
  })

  it('lets the user edit the shipment number and refresh it before confirming the displayed business data', async () => {
    const { view } = await open({ currentTask: { type: 'shipment_generate', title: '创建发货单', description: 'Mac验收客户', customOrderNumber: 'SO-OLD', items: [{}] },
      taskTableColumns: ['客户', '数量', '金额'], taskTableItems: [{ 客户: 'Mac验收客户', 数量: 2, 金额: 19.8 }] })
    expect(view.get('input').element.value).toBe('SO-OLD')
    await view.get('input').setValue('SO-MAC-001')
    expect(view.emitted('set-custom-order-number')).toEqual([['SO-MAC-001']])
    await view.get('.task-order-number-row button').trigger('click')
    expect(view.emitted('refetch-order-number')).toEqual([[]])
    expect(view.get('tbody').text()).toContain('19.8')
    await view.get('[data-action=confirm-task]').trigger('click')
    await view.get('[data-action=cancel-task]').trigger('click')
    expect(view.emitted('confirm-task')).toEqual([[]])
    expect(view.emitted('cancel-task')).toEqual([[]])
  })

  it('disables duplicate execution and order-number refresh during an active write', async () => {
    const { view } = await open({ currentTask: { type: 'shipment_generate' }, isExecuting: true, orderNumberFetching: true })
    for (const selector of ['[data-action=confirm-task]', '[data-action=cancel-task]', '.task-order-number-row button']) {
      expect(view.get(selector).attributes('disabled')).toBeDefined()
      await view.get(selector).trigger('click')
    }
    expect(view.emitted('confirm-task')).toBeUndefined()
    expect(view.emitted('cancel-task')).toBeUndefined()
    expect(view.emitted('refetch-order-number')).toBeUndefined()
  })

  it('shows completed shipment download and print actions with the actual order number', async () => {
    const { view } = await open({ currentTask: { type: 'shipment_generate', completed: true, downloadUrl: '/api/reports/mac.xlsx' }, taskOrderNumber: 'SO-MAC-001' })
    expect(view.text()).toContain('SO-MAC-001')
    expect(view.find('[data-action=confirm-task]').exists()).toBe(false)
    expect(view.get('a[download]').attributes('href')).toBe('/api/reports/mac.xlsx')
    view.get('a[download]').element.addEventListener('click', (event) => event.preventDefault(), { once: true })
    await view.get('a[download]').trigger('click')
    await view.get('[data-action=start-print]').trigger('click')
    await view.get('[data-action=close-task]').trigger('click')
    expect(view.emitted('shipment-download-click')).toEqual([[]])
    expect(view.emitted('start-print')).toEqual([[]])
    expect(view.emitted('cancel-task')).toEqual([[]])
  })

  it('shows the import record count before execution and offers products only after completion', async () => {
    const { view } = await open({ currentTask: { type: 'excel_import', payload: { params: { record_count: 12 } } } })
    expect(view.get('.stat-value').text()).toContain('12')
    expect(view.find('[data-action=view-products]').exists()).toBe(false)
    await view.setProps({ currentTask: { type: 'excel_import', completed: true } })
    expect(view.find('.excel-import-preview').exists()).toBe(false)
    await view.get('[data-action=view-products]').trigger('click')
    expect(view.emitted('switch-view')).toEqual([['products']])
  })

  it('lets the user filter persisted tasks and clear history, while selecting the clicked task', async () => {
    const { view } = await open({ taskList: [task], filteredTaskList: [task], activeTaskId: task.id })
    for (const button of view.findAll('.task-filter-btn')) await button.trigger('click')
    expect(view.emitted('set-task-filter')).toEqual([['all'], ['running'], ['blocked'], ['success'], ['failed']])
    await view.get('.task-toolbar > button').trigger('click')
    await view.get('.task-list-main').trigger('click')
    expect(view.emitted('clear-task-history')).toEqual([[]])
    expect(view.emitted('select-task')).toEqual([[task]])
    expect(view.get('.task-list-item').classes()).toContain('task-list-item-active')
    expect(view.text()).toContain('time:2')
  })

  it.each(['failed', 'cancelled'] as const)('does not display a success-like percentage for a %s task', async (status) => {
    const failed = { ...task, status, progress: 100, error: '模型服务不可用', summary: '没有创建订单' }
    const { view } = await open({ taskList: [failed], filteredTaskList: [failed], expandedTaskIds: [failed.id] })
    expect(view.get('.task-list-meta').text()).not.toContain('100')
    expect(view.get('.task-error').text()).toBe('模型服务不可用')
    expect(view.text()).toContain('没有创建订单')
    await view.get('.task-list-detail button').trigger('click')
    expect(view.emitted('jump-to-task-message')).toEqual([[failed]])
    expect(view.text()).toContain('不提供伪控制')
  })

  it('opens shipment records from a persisted audit hint', async () => {
    const audit = { ...task, type: 'shipment_audit_hint' }
    const { view } = await open({ taskList: [audit], filteredTaskList: [audit], expandedTaskIds: [audit.id] })
    await view.findAll('.task-list-detail button')[0].trigger('click')
    expect(view.emitted('open-shipment-records')).toEqual([[]])
  })

  it.each([false, true])('keeps workflow progress honest when started=%s', async (started) => {
    const employee = { ...task, type: 'workflow_employee', progress: 50, payload: {
      workflowProgressPct: 50, workflowProgressStarted: started, workflowProgressLabel: '等待业务消息',
      workflowMonitorLine: '监听已就绪', workflowCurrentHint: '等待客户下达任务', workflowSteps: [
        { id: 'receive', label: '接收', status: 'done' }, { id: 'approve', label: '审批', status: 'active' }, { id: 'write', label: '写入', status: 'pending' },
      ],
    } }
    const { view } = await open({ taskList: [employee], filteredTaskList: [employee], expandedTaskIds: [employee.id] })
    expect(view.get('[role=progressbar]').attributes('aria-valuenow')).toBe(started ? '50' : '0')
    expect(view.get('.task-wf-progress-fill').attributes('style')).toContain(started ? '50%' : '0%')
    expect(view.get('.task-wf-monitor-text').text()).toBe('监听已就绪')
    expect(view.get('.task-workflow-hint').text()).toBe('等待客户下达任务')
    expect(view.findAll('.task-workflow-step')).toHaveLength(3)
    await view.setProps({ expandedTaskIds: [] })
    expect(view.find('.task-workflow-body').exists()).toBe(false)
    expect(view.get('.task-list-main').attributes('aria-expanded')).toBe('false')
  })

  it('does not invent an independent workspace for a local task snapshot', async () => {
    const local = { ...task, type: 'agent_task', payload: { taskId: 'durable-1', serverBacked: false } }
    const { view, router } = await open({ taskList: [local], filteredTaskList: [local], expandedTaskIds: [local.id] })
    expect(view.find('.task-workspace-action').exists()).toBe(false)
    await view.get('.agent-task-runtime .task-actions button').trigger('click')
    expect(view.emitted('select-task')).toEqual([[local]])
    expect(router.currentRoute.value.path).toBe('/')
  })

  it.each(['conversation', 'workspace', 'task'])('routes a durable waiting task using its %s identity', async (identity) => {
    const durable = { ...task, type: 'agent_task', status: 'blocked' as const, payload: {
      taskId: ' durable-1 ', serverBacked: true, rawRunStatus: 'waiting_user',
      conversationId: identity === 'conversation' ? ' original-chat ' : '', workspaceId: identity === 'workspace' ? ' business-space ' : '',
    } }
    const { view, router } = await open({ taskList: [durable], filteredTaskList: [durable], expandedTaskIds: [durable.id] })
    const target = view.get('.task-workspace-action a')
    expect(target.text()).toBe('前往确认')
    await view.get('.agent-task-runtime .task-actions button').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.params.taskId).toBe('durable-1')
    expect(router.currentRoute.value.query.conversation).toBe(identity === 'conversation' ? 'original-chat' : identity === 'workspace' ? 'business-space' : 'durable-1')
  })
})
