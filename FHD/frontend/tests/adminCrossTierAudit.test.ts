import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
const api = vi.hoisted(() => ({ fetchAutonomyOverview: vi.fn(), fetchAutonomyGithubItems: vi.fn(), fetchAutonomyCrossTierGate: vi.fn(), fetchAutonomyAuditCrossTier: vi.fn() }))
vi.mock('@/api/xcmaxAdmin', () => ({ xcmaxAdminApi: api }))
vi.mock('@/utils/appDialog', () => ({ appConfirm: vi.fn() }))
import Tab from '../../admin-console/src/components/admin/XCmaxAdminAutonomyTab.vue'
beforeEach(() => { vi.clearAllMocks(); api.fetchAutonomyOverview.mockResolvedValue({}); api.fetchAutonomyGithubItems.mockResolvedValue({}); api.fetchAutonomyCrossTierGate.mockResolvedValue({}) })
describe('cross-tier audit actual display contract', () => {
  it.each([
    ['ready', '已加载审计记录'], ['stale', '数据已过期'], ['not_connected', '数据源未接入'], ['error', '加载失败'],
  ])('shows explicit %s state', async (status, message) => {
    api.fetchAutonomyAuditCrossTier.mockResolvedValue({ status, items: [], path: '/synthetic/audit.jsonl' })
    const wrapper = mount(Tab); await flushPromises(); expect(wrapper.text()).toContain(message); wrapper.unmount()
  })
  it.each([{}, null, { items: [null], status: 'ready' }, { items: [], status: 'made_up' }])('rejects malformed response %j', async (payload) => {
    api.fetchAutonomyAuditCrossTier.mockResolvedValue(payload)
    const wrapper = mount(Tab); await flushPromises(); expect(wrapper.text()).toContain('加载失败'); wrapper.unmount()
  })
  it('summarizes actual action reasons and execution results without expanding raw JSON', async () => {
    api.fetchAutonomyAuditCrossTier.mockResolvedValue({ status: 'ready', items: [{ action: { type: 'restart', reasons: ['synthetic reason'] }, result: { ok: false, detail: 'synthetic failure' } }] })
    const wrapper = mount(Tab); await flushPromises()
    expect(wrapper.get('.data-table').text()).toContain('失败：synthetic reason')
    expect(wrapper.find('details').attributes('open')).toBeUndefined(); wrapper.unmount()
  })
})
