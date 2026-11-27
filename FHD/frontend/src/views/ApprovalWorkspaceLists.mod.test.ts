import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { setRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime'
import { appAlert, appPrompt } from '@/utils/appDialog'
import { invalidateEnterpriseSessionCache } from '@/utils/authSessionCache'
import ApprovalWorkspace from '../../../mods/bridge/xcagi-approval-bridge/frontend/views/ApprovalWorkspaceView.vue'

const { get, post, validateSession } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), validateSession: vi.fn() }))
vi.mock('@/api/core', () => ({ api: { get, post, delete: vi.fn() } }))
vi.mock('@/api/auth', () => ({ authApi: { validateSession } }))
vi.mock('@/utils/approvalPaths', () => ({ resolveApprovalApiPath: (path: string) => path }))
vi.mock('@/utils/appDialog', () => ({ appAlert: vi.fn(), appPrompt: vi.fn(), appConfirm: vi.fn() }))
vi.mock('@/api/elt', () => ({ eltApi: { autoIngestBatches: vi.fn(async () => []), withdrawAutoIngestBatch: vi.fn(), autoIngestProgress: vi.fn() } }))

function response(type: string, page: number) {
  return { success: true, pagination: { page, page_size: 50, total: 101 }, data: [{
    id: page, request_no: `${type}-${page}`, title: `${type}第${page}页`, status: 'pending', business_type: 'expense', created_at: '',
  }] }
}

async function openWorkspace() {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/approval-hub/workspace', component: ApprovalWorkspace }] })
  await router.push('/approval-hub/workspace')
  await router.isReady()
  const wrapper = mount(ApprovalWorkspace, { global: { plugins: [router], stubs: { teleport: true } } })
  await flushPromises()
  return wrapper
}

async function selectQueue(wrapper: Awaited<ReturnType<typeof openWorkspace>>, label: string) {
  const tab = wrapper.findAll('[role="tab"]').find(item => item.text().startsWith(label))
  if (!tab) throw new Error(`Missing approval queue ${label}`)
  await tab.trigger('keydown', { key: 'Enter' })
  expect(tab.attributes('aria-selected')).toBe('true')
}

describe('actual approval Mod complete lists', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    post.mockReset()
    setRuntimeTenantStorageScopeInput({ tenantId: 1, localUserId: 42 })
    validateSession.mockResolvedValue({ success: true, local_user_id: 42 })
    get.mockImplementation(async (_path, params) => response(params.approver_id ? '待审批' : '我发起', params.page))
  })
  afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers() })

  function pendingExecution(state: string = 'queued') {
    return { id: 12, request_no: 'customer-approval-12', title: '智能对话写操作：sales.execute_closed_loop',
      status: 'approved', business_type: 'workflow_tool', created_at: '', records: [],
      workflow_execution: { agent_run_id: 'original-sales-run', workflow_executed: false, success: false,
        execution_state: state, execution_accepted: state === 'queued', code: state === 'unknown' ? 'outcome_unknown' : state,
        requires_reconciliation: state === 'unknown', retryable: false,
        nodes_executed: 0, nodes_total: 3, message: state === 'unknown' ? '请核对原任务，勿重复提交。' : '审批已通过，原任务尚未完成。' } }
  }

  it.each(['queued', 'unknown'] as const)('reads back the original %s execution after a real 202 approval envelope', async state => {
    vi.useFakeTimers()
    let current = pendingExecution(state)
    let submitted = false
    get.mockImplementation(async (path, params) => path.endsWith('/12')
      ? { success: true, data: current }
      : { success: true, data: params.approver_id && submitted ? [] : [{ ...current, status: submitted ? 'approved' : 'pending' }] })
    post.mockImplementation(async () => { submitted = true; return { success: false, accepted: true, data: current, message: current.workflow_execution.message } })
    vi.mocked(appPrompt).mockResolvedValue('确认本次销售范围')
    const wrapper = await openWorkspace()
    await wrapper.get('.btn-approve').trigger('click'); await flushPromises()
    expect(post).toHaveBeenCalledExactlyOnceWith('/api/approval/requests/12/approve', { approver_id: 42, opinion: '确认本次销售范围' }, { headers: { 'X-User-ID': '42' } })
    expect(get).toHaveBeenCalledWith('/api/approval/requests/12')
    const details = wrapper.get('[data-tutorial-id="approval-detail"]')
    expect(details.text()).toContain(state === 'queued' ? '等待执行' : '结果待核对')
    expect(details.text()).not.toContain('未触发执行')
    expect(wrapper.find('.workflow-execution-panel.failed').exists()).toBe(false)
    expect(wrapper.find('[data-tutorial-id="approval-approve-action"]').exists()).toBe(false)
    const detailReads = () => get.mock.calls.filter(([path]) => path === '/api/approval/requests/12').length
    const reads = detailReads()
    if (state === 'queued') {
      current = { ...current, workflow_execution: { ...current.workflow_execution, execution_state: 'completed', workflow_executed: true, execution_accepted: false, success: true, nodes_executed: 3, message: '业务结果核对完成。' } }
      await vi.advanceTimersByTimeAsync(2000); await flushPromises()
      expect(detailReads()).toBe(reads + 1)
      expect(wrapper.get('[data-tutorial-id="approval-detail"]').text()).toContain('执行完成')
    } else {
      await vi.advanceTimersByTimeAsync(2000); await flushPromises()
      expect(detailReads()).toBe(reads)
      await wrapper.findAll('button').find(button => button.text() === '刷新执行结果')!.trigger('click'); await flushPromises()
      expect(detailReads()).toBe(reads + 1)
    }
    expect(post).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('counts 202 approval acknowledgements as awaiting results instead of failed or completed business', async () => {
    post.mockResolvedValue({ success: false, accepted: true, data: pendingExecution(), message: '原任务已入队' })
    vi.mocked(appPrompt).mockResolvedValue('确认批准范围')
    const wrapper = await openWorkspace()
    await (wrapper.vm as any).tm.approveMany([12])
    expect(appAlert).toHaveBeenLastCalledWith(expect.stringContaining('已受理待核对 1 条'))
    expect(appAlert).not.toHaveBeenLastCalledWith(expect.stringContaining('失败 1 条'))
    wrapper.unmount()
  })

  it('retires a pending approval prompt after the same account changes session', async () => {
    let finish!: (opinion: string) => void
    vi.mocked(appPrompt).mockImplementation(() => new Promise(resolve => { finish = resolve }))
    post.mockResolvedValue({ success: false, accepted: true, data: pendingExecution() })
    const wrapper = await openWorkspace()
    const approving = (wrapper.vm as any).tm.approve(12)
    invalidateEnterpriseSessionCache()
    finish('旧会话中确认的范围')
    await approving
    expect(post).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it.each(['account', 'session', 'close', 'unmount'])('does not reopen a stale approval detail after %s', async change => {
    const wrapper = await openWorkspace()
    let finish!: (result: unknown) => void
    get.mockImplementation((path, params) => path.endsWith('/12') ? new Promise(resolve => { finish = resolve }) : Promise.resolve(response('当前账号', params.page)))
    const tm = (wrapper.vm as any).tm
    const reading = tm.viewDetails(12)
    if (change === 'account') productReadAccountEpoch.value++
    if (change === 'session') invalidateEnterpriseSessionCache()
    if (change === 'close') tm.closeDetails()
    if (change === 'unmount') wrapper.unmount()
    finish({ success: true, data: pendingExecution() })
    await reading; await flushPromises()
    expect(tm.showDetails.value).toBe(false)
    expect(tm.selectedRequest.value).toBeNull()
    if (change !== 'unmount') wrapper.unmount()
  })

  it.each([
    ['待我审批', '待审批', 'approver_id', '我发起'],
    ['我发起的', '我发起', 'applicant_id', '待审批'],
  ] as const)(
    'opens and pages the %s list using the authenticated user and restores the selected queue', async (tabLabel, label, filter, otherLabel) => {
      const wrapper = await openWorkspace()
      await selectQueue(wrapper, tabLabel)
      expect(wrapper.text()).toContain(`${label}第1页`)
      expect(wrapper.text()).not.toContain(`${otherLabel}第1页`)
      const buttons = wrapper.findAll('button').filter(button => button.text() === '查看全部')
      expect(buttons).toHaveLength(1)
      await buttons[0].trigger('click')
      await flushPromises()
      expect(wrapper.get('[aria-label="完整审批列表"]').text()).toContain('第 1 / 3 页')
      expect(get).toHaveBeenLastCalledWith('/api/approval/requests', { [filter]: 42, page: 1, page_size: 50 }, { headers: { 'X-User-ID': '42' } })
      await wrapper.findAll('button').find(button => button.text() === '下一页')!.trigger('click')
      await flushPromises()
      expect(wrapper.text()).toContain(`${label}第2页`)
      expect(get).toHaveBeenLastCalledWith('/api/approval/requests', { [filter]: 42, page: 2, page_size: 50 }, { headers: { 'X-User-ID': '42' } })
      await wrapper.findAll('button').find(button => button.text() === '返回工作台')!.trigger('click')
      expect(wrapper.find('[aria-label="完整审批列表"]').exists()).toBe(false)
      expect(wrapper.get('[role="tab"][aria-selected="true"]').text()).toContain(tabLabel)
      expect(wrapper.findAll('button').filter(button => button.text() === '查看全部')).toHaveLength(1)
      expect(wrapper.text()).toContain(`${label}第1页`)
      expect(wrapper.text()).not.toContain(`${otherLabel}第1页`)
      wrapper.unmount()
    },
  )

  it.each([
    ['已通过', 'approved', '通过的采购单', '拒绝的报销单'],
    ['已拒绝', 'rejected', '拒绝的报销单', '通过的采购单'],
  ] as const)('filters the %s preview and passes the status through pagination', async (tabLabel, status, title, otherTitle) => {
    get.mockImplementation(async (_path, params) => {
      if (params.page_size === 50) {
        const page = response(title, params.page)
        return { ...page, data: page.data.map(item => ({ ...item, status })) }
      }
      const item = response('事项', 1).data[0]
      return { success: true, data: params.approver_id ? [] : [
        { ...item, id: 10, title: '通过的采购单', status: 'approved' },
        { ...item, id: 11, title: '拒绝的报销单', status: 'rejected' },
      ] }
    })
    const wrapper = await openWorkspace()
    await selectQueue(wrapper, tabLabel)
    expect(wrapper.get('[data-tutorial-id="approval-initiated-list"]').text()).toContain(title)
    expect(wrapper.text()).not.toContain(otherTitle)
    await wrapper.findAll('button').find(button => button.text() === '查看全部')!.trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '下一页')!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain(`${title}第2页`)
    expect(get).toHaveBeenLastCalledWith('/api/approval/requests', { applicant_id: 42, status, page: 2, page_size: 50 }, { headers: { 'X-User-ID': '42' } })
    wrapper.unmount()
  })

  it('shows localized AI operation titles and Chinese status labels', async () => {
    get.mockResolvedValue({ success: true, pagination: { page: 1, page_size: 50, total: 2 }, data: [
      { id: 1, request_no: 'r1', title: '智能对话写操作：elt_import.preview', status: 'cancelled', business_type: 'workflow_tool', created_at: '', business_data: { tool_id: 'elt_import', action: 'preview' } },
      { id: 2, request_no: 'r2', title: `${'超长自定义标题'.repeat(10)}`, status: 'withdrawn', business_type: 'expense', created_at: '' },
    ] })
    const wrapper = await openWorkspace()
    await selectQueue(wrapper, '我发起的')
    expect(wrapper.text()).toContain('数据导入 · 预演')
    expect(wrapper.text()).not.toContain('智能对话写操作')
    expect(wrapper.text()).toContain('已取消')
    expect(wrapper.text()).not.toContain('cancelled')
    expect(wrapper.text()).toContain('已撤回')
    expect(wrapper.text()).toContain('超长自定义标题')
    wrapper.unmount()
  })

  it('keeps a list failure distinct from an empty list and retries the same scope', async () => {
    const wrapper = await openWorkspace()
    get.mockResolvedValueOnce({ success: false, message: '暂时无法读取审批', data: [] })
    await wrapper.findAll('button').find(button => button.text() === '查看全部')!.trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('暂时无法读取审批')
    expect(wrapper.text()).not.toContain('暂无待审批事项')
    await wrapper.get('[role="alert"] button').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('待审批第1页')
    wrapper.unmount()
  })

  it('discards an in-flight full-list response after returning to the workspace', async () => {
    const wrapper = await openWorkspace()
    let finish!: (value: unknown) => void
    get.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    await wrapper.findAll('button').find(button => button.text() === '查看全部')!.trigger('click')
    expect(wrapper.get('[role="status"]').text()).toContain('正在读取')
    await wrapper.findAll('button').find(button => button.text() === '返回工作台')!.trigger('click')
    finish(response('过期响应', 2))
    await flushPromises()
    expect(wrapper.text()).not.toContain('过期响应')
    expect(wrapper.text()).toContain('待审批第1页')
    wrapper.unmount()
  })

  it.each(['identity', 'epoch'])('retires the old full list when the account %s changes and reloads the current session', async (change) => {
    const wrapper = await openWorkspace()
    let finish!: (value: unknown) => void
    get.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    await wrapper.findAll('button').find(button => button.text() === '查看全部')!.trigger('click')
    const userId = change === 'identity' ? 99 : 42
    validateSession.mockResolvedValue({ success: true, local_user_id: userId })
    get.mockImplementation(async (_path, params) => response(`账号${params.approver_id || params.applicant_id}`, params.page))
    if (change === 'identity') setRuntimeTenantStorageScopeInput({ tenantId: 2, localUserId: userId })
    else { productReadAccountEpoch.value++; productReadAccountEpoch.value++ }
    await flushPromises()
    expect(wrapper.find('[aria-label="完整审批列表"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('待审批第1页')
    expect(wrapper.text()).toContain(`账号${userId}第1页`)
    finish(response('旧账号慢响应', 2))
    await flushPromises()
    expect(wrapper.text()).not.toContain('旧账号慢响应')
    await wrapper.findAll('button').find(button => button.text() === '查看全部')!.trigger('click')
    await flushPromises()
    expect(get).toHaveBeenLastCalledWith('/api/approval/requests', { approver_id: userId, page: 1, page_size: 50 }, { headers: { 'X-User-ID': String(userId) } })
    wrapper.unmount()
  })

  it('does not restore a user ID from session validation started before an account switch', async () => {
    let finish!: (value: unknown) => void
    validateSession.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const wrapper = await openWorkspace()
    validateSession.mockResolvedValue({ success: true, local_user_id: 99 })
    setRuntimeTenantStorageScopeInput({ tenantId: 2, localUserId: 99 })
    await flushPromises()
    finish({ success: true, local_user_id: 42 })
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '查看全部')!.trigger('click')
    await flushPromises()
    expect(get.mock.calls.every(([, , options]) => options.headers['X-User-ID'] === '99')).toBe(true)
    wrapper.unmount()
  })

  it.each(['success', 'error'])('ignores a full-list %s received after unmount', async (outcome) => {
    const wrapper = await openWorkspace()
    let finish!: (value: unknown) => void, fail!: (error: Error) => void
    get.mockImplementationOnce(() => new Promise((resolve, reject) => { finish = resolve; fail = reject }))
    await wrapper.findAll('button').find(button => button.text() === '查看全部')!.trigger('click')
    const state = (wrapper.vm as any).tm
    wrapper.unmount()
    if (outcome === 'success') finish(response('页面已关闭', 2))
    else fail(new Error('页面已关闭'))
    await flushPromises()
    expect(state.visiblePendingRequests.value).toEqual([])
    expect(state.fullListError.value).toBe('')
    expect(state.fullListPageCount.value).toBe(1)
  })
})
