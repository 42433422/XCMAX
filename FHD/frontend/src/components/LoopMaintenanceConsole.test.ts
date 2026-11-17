import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import Panel from '../../../admin-console/src/components/workflow/SelfEvolutionLoopRuntimePanel.vue'
const mocks = vi.hoisted(() => ({ status: vi.fn(), push: vi.fn() }))
vi.mock('@/api/xcmaxMarketProxy', () => ({ default: { selfMaintenanceRuntimeStatus: mocks.status } }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: mocks.push }) }))
const payload = () => ({
  ok: true,
  schema_version: 'self_maintenance_runtime.v1',
  generated_at: new Date().toISOString(),
  control_plane: { target: 'market', host: 'xiu-ci.com' },
  evidence: { open_run_ids: [] },
  memory: { open_items: [] },
  policy: { auto_dispatch_deploy: false },
  current_gate: { should_run: false },
  run_timelines: Array.from({ length: 12 }, (_, i) => ({
    run_id: `run-${i}`,
    open: false,
    items: [
      { phase: 'complete', label: `完成记录 ${i}`, created_at: new Date().toISOString(), para_task_id: `para-${i}`, qa_verdict: 'PASS' },
    ],
  })),
})
let wrapper: VueWrapper
beforeEach(() => {
  vi.useFakeTimers()
  mocks.status.mockReset().mockResolvedValue(payload())
  mocks.push.mockReset()
})
afterEach(() => {
  wrapper?.unmount()
  document.body.replaceChildren()
  vi.useRealTimers()
})
function render() {
  wrapper = mount(Panel, { attachTo: document.body, global: { stubs: { MaintenanceExecutionPanel: true } } })
  return wrapper
}

describe('native loop console', () => {
  it('uses the terminal result after a failed retry and hides heartbeat noise', async () => {
    const data = payload()
    data.run_timelines = [
      {
        run_id: 'recovered',
        open: false,
        items: [
          { phase: 'step', status: 'failed' },
          { phase: 'complete', status: 'success', created_at: new Date().toISOString() },
          { phase: 'kb_salvage', status: 'success' },
        ],
      },
      { run_id: 'heartbeat', open: false, items: [{ phase: 'heartbeat', status: 'success' }] },
    ] as typeof data.run_timelines
    mocks.status.mockResolvedValue(data)
    render()
    await flushPromises()
    expect(wrapper.findAll('.el-table__body tbody tr')).toHaveLength(1)
    expect(wrapper.text()).toContain('已结束，待验收')
    expect(wrapper.text()).not.toContain('执行异常')
    await wrapper.get('[role="switch"]').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.el-table__body tbody tr')).toHaveLength(2)
    expect(wrapper.text()).toContain('调度心跳')
  })
  it('does not turn missing pending evidence into zero pending work', async () => {
    const data = payload()
    mocks.status.mockResolvedValue({ ...data, memory: {} })
    render()
    await flushPromises()
    await wrapper.get('#tab-pending').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('待处理状态尚未核实')
    expect(wrapper.text()).not.toContain('暂无待处理事项')
  })
  it('links legacy pending items to the actual failure evidence', async () => {
    const at = new Date().toISOString()
    mocks.status.mockResolvedValue({
      ...payload(),
      memory: { open_items: [{ kind: 'failed_steps', run_id: 'broken', steps: ['code'] }] },
      evidence: {
        open_run_ids: [],
        recent_rows: [{ run_id: 'broken', phase: 'step', step: 'code', timestamp: at, error: 'Git 预检失败：工作目录已删除' }],
      },
      run_timelines: [{ run_id: 'broken', open: false, items: [{ phase: 'step', step: 'code', status: 'failed', created_at: at }] }],
    })
    render()
    await flushPromises()
    await wrapper.get('#tab-pending').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('执行步骤失败')
    expect(wrapper.text()).toContain('Git 预检失败：工作目录已删除')
    await wrapper.get('#pane-pending button.el-button--primary').trigger('click')
    await flushPromises()
    expect(document.body.textContent).toContain('维护任务详情')
    expect(document.body.textContent).toContain('尚未核实')
  })
  it('paginates real run records and keeps completion distinct from acceptance', async () => {
    render()
    await flushPromises()
    expect(wrapper.text()).toContain('监控已连接')
    expect(wrapper.text()).not.toMatch(/L4 READINESS|P0 未清|全部正常/)
    expect(wrapper.findAll('.el-table__body tbody tr')).toHaveLength(8)
    await wrapper.get('button[aria-label="Go to next page"]').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.el-table__body tbody tr')).toHaveLength(4)
    await wrapper.get('input[aria-label="搜索维护记录"]').setValue('run-11')
    await flushPromises()
    expect(wrapper.findAll('.el-table__body tbody tr')).toHaveLength(1)
    await wrapper
      .findAll('button')
      .find((button) => button.text() === '查看详情')!
      .trigger('click')
    await flushPromises()
    expect(document.body.textContent).toContain('para-11')
    expect(document.body.textContent).toContain('已结束，待验收')
    expect(document.body.textContent).toContain('尚未核实')
  })
  it('shows unknown metrics while the first request is pending', async () => {
    mocks.status.mockReturnValue(new Promise(() => {}))
    render()
    await flushPromises()
    expect(wrapper.text()).toContain('正在连接')
    expect(wrapper.text()).not.toContain('未触发')
    expect(wrapper.text()).not.toContain('已关闭')
  })
  it('retains evidence but clears current counts on disconnect', async () => {
    render()
    await flushPromises()
    mocks.status.mockRejectedValue(new Error('offline'))
    await wrapper
      .findAll('button')
      .find((button) => button.text() === '刷新')!
      .trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('连接异常')
    expect(wrapper.text()).toContain('保留上次记录')
    expect(wrapper.text()).toContain('待核实')
    expect(wrapper.text()).toContain('run-11')
    expect(wrapper.text()).not.toContain('暂无运行记录')
  })
  it('keeps cloud work and approvals inside the admin routes', async () => {
    render()
    await flushPromises()
    await wrapper
      .findAll('button')
      .find((button) => button.text() === '云端工作空间')!
      .trigger('click')
    expect(mocks.push).toHaveBeenCalledWith({ name: 'workflow-employee-space' })
    await wrapper.get('#tab-pending').trigger('click')
    await flushPromises()
    await wrapper
      .findAll('button')
      .find((button) => button.text() === '审批中心')!
      .trigger('click')
    expect(mocks.push).toHaveBeenCalledWith({ name: 'autonomy-approval-hub' })
  })
})
