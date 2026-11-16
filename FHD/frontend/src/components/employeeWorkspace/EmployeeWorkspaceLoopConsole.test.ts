import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import { ElInput, ElSelect } from 'element-plus'
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
async function setup() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useAgentTaskCenterStore()
  vi.spyOn(store, 'start').mockImplementation(() => {})
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div />' } }] })
  await router.push('/')
  await router.isReady()
  wrapper = mount(Workspace, {
    attachTo: document.body,
    global: { plugins: [pinia, router], stubs: { ElDialog: { template: '<div><slot /></div>' } } },
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
