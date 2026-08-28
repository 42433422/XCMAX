import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ApprovalHubView from '../../../admin-console/src/views/ApprovalHubView.vue'

const fetchPendingAutonomyActions = vi.fn()
const fetchAutonomyAuditLog = vi.fn()
const resumeAutonomyAction = vi.fn()
const rejectAutonomyAction = vi.fn()
const appAlert = vi.fn().mockResolvedValue(undefined)
const appConfirm = vi.fn().mockResolvedValue(true)
const appPrompt = vi.fn().mockResolvedValue(null)

vi.mock('@/api/xcmaxAdmin', () => ({
  xcmaxAdminApi: {
    fetchPendingAutonomyActions: (...args: unknown[]) => fetchPendingAutonomyActions(...args),
    fetchAutonomyAuditLog: (...args: unknown[]) => fetchAutonomyAuditLog(...args),
    resumeAutonomyAction: (...args: unknown[]) => resumeAutonomyAction(...args),
    rejectAutonomyAction: (...args: unknown[]) => rejectAutonomyAction(...args),
  },
}))

vi.mock('@/utils/appDialog', () => ({
  appAlert: (...args: unknown[]) => appAlert(...args),
  appConfirm: (...args: unknown[]) => appConfirm(...args),
  appPrompt: (...args: unknown[]) => appPrompt(...args),
}))

const actionable = {
  action_id: 'action-ready',
  action: 'rollback_release',
  state: 'pending_approval',
  source: 'runtime',
  admin_execution_ready: true,
  execution_mode: 'registered_executor',
  execution_guidance: '通过后立即执行并记录结果。',
  risk_decision: { risk_level: 'HIGH', decision: 'confirm' },
}

const workflowRelease = {
  action_id: `release:${'a'.repeat(40)}`,
  action: 'apply_release_to_cvm',
  state: 'pending_approval',
  source: 'fhd_auto_update.cron',
  executor_name: 'github_deploy',
  admin_execution_ready: false,
  execution_mode: 'external_dispatch_required',
  execution_guidance: '该发布必须由正式发布工作流审批并执行，管理端不能直接放行。',
  risk_decision: { risk_level: 'HIGH', decision: 'confirm' },
}

describe('ApprovalHubView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    fetchPendingAutonomyActions.mockResolvedValue({
      ok: true,
      count: 2,
      items: [actionable, workflowRelease],
      summary: {
        waiting: 2,
        actionable: 1,
        states: { pending_approval: 2, executed: 11, approved: 2, execution_failed: 1, superseded: 21 },
        execution_modes: { registered_executor: 1, external_dispatch_required: 1 },
      },
    })
    fetchAutonomyAuditLog.mockResolvedValue({
      items: [{ action: 'rollback_release', decision: 'approved', approver: 'market-admin:42' }],
    })
    resumeAutonomyAction.mockResolvedValue({
      ok: true,
      execution_dispatched: true,
      action: { ...actionable, state: 'executed' },
    })
    appConfirm.mockResolvedValue(true)
  })

  it('separates actionable work from formal-workflow releases and shows terminal counts', async () => {
    const wrapper = mount(ApprovalHubView)
    await flushPromises()

    expect(wrapper.text()).toContain('可在此执行1')
    expect(wrapper.text()).toContain('正式流程 / 外部回调1')
    expect(wrapper.text()).toContain('已执行11')
    expect(wrapper.text()).toContain('异常 / 未闭环3')
    expect(wrapper.text()).toContain('已自动归档21')
    expect(wrapper.text()).toContain('需正式发布工作流')
    expect(wrapper.text()).toContain('管理端不能直接放行')

    await wrapper.findAll('.pending-item')[1].trigger('click')
    const workflowButton = wrapper.find('.drawer .btn-primary')
    expect(workflowButton.text()).toContain('需正式发布工作流')
    expect(workflowButton.attributes('disabled')).toBeDefined()
  })

  it('requires a high-risk confirmation before approving and reports the real terminal state', async () => {
    const wrapper = mount(ApprovalHubView)
    await flushPromises()

    await wrapper.findAll('.pending-item')[0].trigger('click')
    await wrapper.find('.drawer .btn-primary').trigger('click')
    await flushPromises()

    expect(appConfirm).toHaveBeenCalledWith(
      expect.stringContaining('action-ready'),
      { title: '高风险动作确认' },
    )
    expect(resumeAutonomyAction).toHaveBeenCalledWith('action-ready')
    expect(appAlert).toHaveBeenCalledWith('审批与执行均已完成，动作终态：executed')
  })

  it('keeps the pending list usable when only the audit stream fails', async () => {
    fetchAutonomyAuditLog.mockRejectedValue(new Error('audit timeout'))

    const wrapper = mount(ApprovalHubView)
    await flushPromises()

    expect(wrapper.text()).toContain('rollback_release')
    expect(wrapper.text()).toContain('审计日志暂时不可用：audit timeout')
    expect(wrapper.text()).not.toContain('待办刷新失败')
  })
})
