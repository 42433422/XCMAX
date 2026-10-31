import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { setRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime'
import ApprovalWorkspace from '../../../mods/xcagi-approval-bridge/frontend/views/ApprovalWorkspaceView.vue'

const { get, validateSession } = vi.hoisted(() => ({ get: vi.fn(), validateSession: vi.fn() }))
vi.mock('@/api/core', () => ({ api: { get, post: vi.fn(), delete: vi.fn() } }))
vi.mock('@/api/auth', () => ({ authApi: { validateSession } }))
vi.mock('@/utils/approvalPaths', () => ({ resolveApprovalApiPath: (path: string) => path }))
vi.mock('@/utils/appDialog', () => ({ appAlert: vi.fn(), appPrompt: vi.fn(), appConfirm: vi.fn() }))
vi.mock('@/api/etl', () => ({ etlApi: { autoIngestBatches: vi.fn(async () => []), withdrawAutoIngestBatch: vi.fn(), autoIngestProgress: vi.fn() } }))

function response(type: string, page: number) {
  return { success: true, pagination: { page, page_size: 50, total: 101 }, data: [{
    id: page, request_no: `${type}-${page}`, title: `${type}第${page}页`, status: 'pending', business_type: 'expense', created_at: '',
  }] }
}

async function openWorkspace() {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/approval-hub/workspace', component: ApprovalWorkspace }] })
  await router.push('/approval-hub/workspace')
  await router.isReady()
  const wrapper = mount(ApprovalWorkspace, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}

describe('actual approval Mod complete lists', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setRuntimeTenantStorageScopeInput({ tenantId: 1, localUserId: 42 })
    validateSession.mockResolvedValue({ success: true, local_user_id: 42 })
    get.mockImplementation(async (_path, params) => response(params.approver_id ? '待审批' : '我发起', params.page))
  })
  afterEach(() => vi.restoreAllMocks())

  it.each([['pending', 0, '待审批', 'approver_id'], ['initiated', 1, '我发起', 'applicant_id']] as const)(
    'opens and pages the %s list using the authenticated user and returns to the workspace', async (_type, index, label, filter) => {
      const wrapper = await openWorkspace()
      const buttons = wrapper.findAll('button').filter(button => button.text() === '查看全部')
      expect(buttons).toHaveLength(2)
      await buttons[index].trigger('click')
      await flushPromises()
      expect(wrapper.get('[aria-label="完整审批列表"]').text()).toContain('第 1 / 3 页')
      expect(get).toHaveBeenLastCalledWith('/api/approval/requests', { [filter]: 42, page: 1, page_size: 50 }, { headers: { 'X-User-ID': '42' } })
      await wrapper.findAll('button').find(button => button.text() === '下一页')!.trigger('click')
      await flushPromises()
      expect(wrapper.text()).toContain(`${label}第2页`)
      expect(get).toHaveBeenLastCalledWith('/api/approval/requests', { [filter]: 42, page: 2, page_size: 50 }, { headers: { 'X-User-ID': '42' } })
      await wrapper.findAll('button').find(button => button.text() === '返回工作台')!.trigger('click')
      expect(wrapper.find('[aria-label="完整审批列表"]').exists()).toBe(false)
      expect(wrapper.findAll('button').filter(button => button.text() === '查看全部')).toHaveLength(2)
      expect(wrapper.text()).toContain('待审批第1页')
      expect(wrapper.text()).toContain('我发起第1页')
      wrapper.unmount()
    },
  )

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
