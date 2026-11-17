import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import { fetchEmployeeSsot } from '@/utils/platformShellApi'
import RuntimePanel from '@/components/chat/AgentTaskRuntimePanel.vue'
import { ElDialog, ElInput, ElSelect } from 'element-plus'
import Workspace from './EmployeeWorkspaceLoopConsole.vue'
import { useAgentTaskCenterStore } from '@/stores/agentTaskCenter'
const api = vi.hoisted(() => ({ listTasks: vi.fn(), getTaskRuntime: vi.fn(), getTask: vi.fn(), createTask: vi.fn() }))
vi.mock('@/api/agentRuns', () => ({ default: api }))
vi.mock('@/utils/platformShellApi', () => ({
  fetchEmployeeSsot: vi.fn(async () => ({
    contacts: [
      { employee_id: 'auditor', display_name: '巡检员', installed: true, runnable: true },
      { employee_id: 'planned', display_name: '未安装员工', installed: false, runnable: false },
    ],
  })),
}))
vi.mock('./TaskExecutionGraph.vue', () => ({ default: { template: '<div>真实执行图</div>' } }))
vi.mock('@/components/chat/AgentTaskRuntimePanel.vue', () => ({ default: { template: '<div>执行结果</div>' } }))
const task = {
  task_id: 'existing',
  user_id: '1',
  title: '已有巡检任务',
  status: 'failed',
  source: 'agent',
  task_type: 'agent',
  attempt: 1,
  run_count: 1,
  active_run_id: 'run-1',
  workspace_path: '/server/workspace',
  active_run: {
    run_id: 'run-1',
    user_id: '1',
    message: '巡检',
    status: 'failed',
    steps: [{ node_id: 'a', step_id: 'a', tool_id: 'employee', action: 'execute', status: 'failed' }],
  },
}
let wrapper: ReturnType<typeof mount>
async function setup(query: Record<string, string> = {}) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useAgentTaskCenterStore()
  vi.spyOn(store, 'start').mockImplementation(() => {})
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/', component: { template: '<div />' } },
    { path: '/task/:taskId', name: 'task-workspace', component: { template: '<div />' } },
    { path: '/employees', name: 'duty-roster-graph', component: { template: '<div />' } },
  ] })
  await router.push({ path: '/', query })
  await router.isReady()
  wrapper = mount(Workspace, {
    attachTo: document.body,
    global: { plugins: [pinia, router], stubs: { ElDialog: { props: ['modelValue'], template: '<div><slot /></div>' } } },
  })
  await flushPromises()
  return store
}
beforeEach(() => {
  vi.clearAllMocks()
  api.listTasks.mockResolvedValue({ success: true, data: [task] })
  api.getTaskRuntime.mockResolvedValue({
    success: true,
    data: {
      running: true,
      active_count: 0,
      max_workers: 4,
      executor: { host: 'worker-test', workspace_root: '/server/workspace', engine: 'langgraph' },
    },
  })
  api.getTask.mockResolvedValue({ success: true, data: task })
})
afterEach(() => {
  wrapper?.unmount()
  document.body.replaceChildren()
})
describe('employee task workspace', () => {
  it('reads durable task evidence and preserves failure status', async () => {
    await setup()
    expect(wrapper.text()).toContain('已有巡检任务')
    expect(wrapper.text()).toContain('失败')
    expect(wrapper.text()).toContain('/server/workspace')
    expect(wrapper.text()).toContain('真实执行图')
    expect(wrapper.text()).not.toContain('视觉态忙')
    expect(api.getTask).toHaveBeenCalledWith('existing')
  })
  it('dispatches through the durable employee tool and retries an uncertain submission with the same identity', async () => {
    await setup()
    await wrapper
      .findAll('button')
      .find((b) => b.text() === '新建任务')!
      .trigger('click')
    await flushPromises()
    const select = wrapper.findAllComponents(ElSelect).find((c) => c.props('ariaLabel') === '执行员工')!
    select.vm.$emit('update:modelValue', 'auditor')
    const input = wrapper.findAllComponents(ElInput).find((c) => c.props('type') === 'textarea')!
    input.vm.$emit('update:modelValue', '只读检查')
    await flushPromises()
    api.createTask.mockRejectedValueOnce(new Error('连接中断')).mockRejectedValueOnce(new Error('仍未确认'))
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    const first = api.createTask.mock.calls[0][0]
    const second = api.createTask.mock.calls[1][0]
    expect(second.task_id).toBe(first.task_id)
    expect(first).toMatchObject({ tool_id: 'employee', action: 'execute', params: { employee_id: 'auditor', task: '只读检查' } })
    expect(first.runtime_context.invoke_mode).toBeUndefined()
    expect(wrapper.text()).toContain('再次提交将核对同一任务')
  })
  it('does not dispatch an uninstalled employee', async () => {
    await setup()
    await wrapper
      .findAll('button')
      .find((b) => b.text() === '新建任务')!
      .trigger('click')
    await flushPromises()
    wrapper
      .findAllComponents(ElSelect)
      .find((c) => c.props('ariaLabel') === '执行员工')!
      .vm.$emit('update:modelValue', 'planned')
    wrapper
      .findAllComponents(ElInput)
      .find((c) => c.props('type') === 'textarea')!
      .vm.$emit('update:modelValue', '执行检查')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(api.createTask).not.toHaveBeenCalled()
  })
})
async function clickButton(label: string) {
  await wrapper.findAll('button').find(button => button.text() === label)!.trigger('click')
  await flushPromises()
}
async function composeTask(text = '核查业务记录') {
  await clickButton('新建任务')
  wrapper.findAllComponents(ElSelect).find(c => c.props('ariaLabel') === '执行员工')!.vm.$emit('update:modelValue', 'auditor')
  wrapper.findAllComponents(ElInput).find(c => c.props('type') === 'textarea')!.vm.$emit('update:modelValue', text)
  await flushPromises()
}
async function submitTask() {
  await wrapper.find('form').trigger('submit')
  await flushPromises()
}
describe('workspace submission and navigation boundaries', () => {
  it('selects the acknowledged task and clears its compose form', async () => {
    await setup({ employee: 'auditor' })
    await composeTask()
    api.createTask.mockResolvedValueOnce({ success: true, data: { run_id: 'new-run' } })
    await submitTask()
    const id = api.createTask.mock.calls[0][0].task_id
    expect(api.getTask).toHaveBeenLastCalledWith(id)
    expect(wrapper.vm.$route.query.task).toBe(id)
    expect(wrapper.findAllComponents(ElInput).find(c => c.props('type') === 'textarea')!.props('modelValue')).toBe('')
    expect(api.listTasks).toHaveBeenCalledTimes(2)
  })
  it('releases a definitively rejected submission, but preserves an unconfirmed receipt', async () => {
    await setup()
    await composeTask()
    api.createTask.mockRejectedValueOnce(Object.assign(new Error('禁止执行'), { status: 403 }))
    await submitTask()
    expect(wrapper.text()).toContain('禁止执行')
    expect(wrapper.text()).not.toContain('再次提交将核对同一任务')
    const rejectedId = api.createTask.mock.calls[0][0].task_id
    api.createTask.mockResolvedValueOnce({ success: false, message: '尚无回执' })
    await submitTask()
    expect(api.createTask.mock.calls[1][0].task_id).not.toBe(rejectedId)
    expect(wrapper.text()).toContain('尚无回执。再次提交将核对同一任务')
    wrapper.findAllComponents(ElInput).find(c => c.props('type') === 'textarea')!.vm.$emit('update:modelValue', '更换内容')
    await submitTask()
    expect(api.createTask).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('请勿更换内容后重复提交')
    await clickButton('关闭')
    expect(wrapper.findComponent(ElDialog).props('modelValue')).toBe(false)
    await clickButton('新建任务')
    expect(wrapper.findAllComponents(ElInput).find(c => c.props('type') === 'textarea')!.props('disabled')).toBe(true)
    wrapper.findComponent(ElDialog).vm.$emit('update:modelValue', false)
    await flushPromises()
    expect(wrapper.findComponent(ElDialog).props('modelValue')).toBe(false)
  })
  it('renders directory failures without allowing a new task', async () => {
    await setup()
    vi.mocked(fetchEmployeeSsot).mockRejectedValueOnce(new Error('offline'))
    await clickButton('新建任务')
    expect(wrapper.text()).toContain('员工目录读取失败')
    await submitTask()
    expect(api.createTask).not.toHaveBeenCalled()
  })
  it('filters actual task states and searches case-insensitively', async () => {
    api.listTasks.mockResolvedValue({ success: true, data: [
      ...['completed', 'paused', 'running', 'queued'].map(status => ({ ...task, task_id: status, title: `Task ${status}`, status, updated_at: '2026-11-16T12:00:00Z' })),
      { ...task, updated_at: 'invalid' },
    ] })
    await setup()
    const filter = wrapper.findAllComponents(ElSelect).find(c => c.props('ariaLabel') === '任务状态筛选')!
    for (const [value, expected] of [['active', 2], ['attention', 2], ['completed', 1], ['all', 5]] as const) {
      filter.vm.$emit('update:modelValue', value)
      await flushPromises()
      expect(wrapper.findAll('.workspace-task')).toHaveLength(expected)
    }
    const search = wrapper.findAllComponents(ElInput).find(c => c.props('ariaLabel') === '搜索任务')!
    search.vm.$emit('update:modelValue', ' TASK RUNNING ')
    await flushPromises()
    expect(wrapper.findAll('.workspace-task')).toHaveLength(1)
    expect(wrapper.find('.workspace-task').text()).toContain('Task running')
    search.vm.$emit('update:modelValue', 'missing')
    await flushPromises()
    expect(wrapper.text()).toContain('没有匹配任务')
  })
  it('refreshes after a persisted update or route selection and returns to the list', async () => {
    const store = await setup()
    api.getTask.mockClear()
    store.tasks = [{ ...task, updated_at: '2026-11-16T13:00:00Z' }]
    await flushPromises()
    expect(api.getTask).toHaveBeenCalledWith('existing')
    await wrapper.vm.$router.replace({ query: { task: 'other' } })
    await flushPromises()
    expect(api.getTask).toHaveBeenLastCalledWith('other')
    api.getTask.mockResolvedValue({ success: true, data: task })
    await wrapper.find('.workspace-task').trigger('click')
    await flushPromises()
    await clickButton('刷新')
    expect(api.listTasks).toHaveBeenCalledTimes(2)
    await clickButton('返回任务列表')
    expect(store.selectedTaskId).toBe('')
    expect(wrapper.vm.$route.query.task).toBeUndefined()
    expect(wrapper.text()).toContain('选择任务，查看工作空间与执行流程')
    await clickButton('员工图谱')
    expect(wrapper.vm.$route.name).toBe('duty-roster-graph')
  })
  it('routes a task conversation and forwards every runtime control to the selected task', async () => {
    api.getTask.mockResolvedValue({ success: true, data: { ...task, capabilities: { approve: true, pause: true, resume: true, cancel: true, retry: true } } })
    const store = await setup()
    const control = vi.spyOn(store, 'controlTask').mockResolvedValue(undefined)
    for (const [label, action] of [['审批并执行', 'approve'], ['暂停', 'pause'], ['恢复', 'resume'], ['取消', 'cancel'], ['重试', 'retry']]) {
      await clickButton(label)
      expect(control).toHaveBeenLastCalledWith('existing', action)
      wrapper.findComponent(RuntimePanel).vm.$emit(action)
      await flushPromises()
      expect(control).toHaveBeenLastCalledWith('existing', action)
    }
    wrapper.findComponent(RuntimePanel).vm.$emit('refresh')
    await flushPromises()
    expect(api.listTasks).toHaveBeenCalledTimes(2)
    await clickButton('任务对话')
    expect(wrapper.vm.$route.name).toBe('task-workspace')
    wrapper.findComponent(RuntimePanel).vm.$emit('open')
    await flushPromises()
    expect(wrapper.vm.$route.name).toBe('task-workspace')
    expect(wrapper.vm.$route.query.conversation).toBe('existing')
  })
  it('shows the assigned employee and persisted event history from a run fallback', async () => {
    api.getTask.mockResolvedValue({ success: true, data: { ...task, active_run: undefined, runs: [{ ...task.active_run,
      steps: [{ ...task.active_run.steps[0], params: { employee_id: 'auditor' } }],
      events: [{ event_id: 'event-1', event_type: 'finished', message: '实际执行完成', created_at: '2026-11-16T13:00:00Z' }],
    }] } })
    await setup()
    expect(wrapper.text()).toContain('执行员工 巡检员')
    expect(wrapper.text()).toContain('实际执行完成')
    expect(wrapper.text()).toContain('真实执行图')
  })
})
