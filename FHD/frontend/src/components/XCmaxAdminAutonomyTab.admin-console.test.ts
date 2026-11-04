import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import XCmaxAdminAutonomyTab from '../../../admin-console/src/components/admin/XCmaxAdminAutonomyTab.vue'
import { xcmaxAdminApi } from '@/api/xcmaxAdmin'

vi.mock('@/api/xcmaxAdmin', () => ({ xcmaxAdminApi: { fetchAutonomyOverview: vi.fn(), fetchAutonomyGithubItems: vi.fn(), fetchAutonomyCrossTierGate: vi.fn(), fetchAutonomyAuditCrossTier: vi.fn(), forceSelfMaintenanceRun: vi.fn() } }))
const overview = () => ({ pending: { count: 3 }, operating_metrics: { windows: { '30': { action_count: 10, blocked_count: 1, veto_rate: 10 } }, veto_rate_trend_30d: [{ veto_rate: 4 }, { veto_rate: 3 }] }, deploy_events: { items: [] }, audit: { items: [] } })
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(xcmaxAdminApi.fetchAutonomyOverview).mockResolvedValue(overview())
  vi.mocked(xcmaxAdminApi.fetchAutonomyGithubItems).mockResolvedValue({ items: [] })
  vi.mocked(xcmaxAdminApi.fetchAutonomyCrossTierGate).mockResolvedValue({ rules: [{ tier: 'server', action_type: 'deploy', label: '发布动作', allow: true }] })
  vi.mocked(xcmaxAdminApi.fetchAutonomyAuditCrossTier).mockResolvedValue({ ok: true, items: [], status: 'empty', exists: true })
})
it('replaces stale metrics with an unknown state while independent gate and audit sources remain readable', async () => {
  const wrapper = mount(XCmaxAdminAutonomyTab)
  await flushPromises()
  expect(wrapper.get('.kpi-value').text()).toBe('3')
  vi.mocked(xcmaxAdminApi.fetchAutonomyOverview).mockRejectedValueOnce(new Error('读取超时'))
  await wrapper.findAll('button').find(button => button.text() === '刷新')!.trigger('click')
  await flushPromises()
  expect(wrapper.get('.kpi-value').text()).toBe('待核实')
  expect(wrapper.get('[role="alert"]').text()).toContain('运营总览读取失败')
  expect(wrapper.text()).toContain('跨端门禁：已读取')
  expect(wrapper.text()).toContain('数据源已接入，但尚无审计记录')
  expect(wrapper.text()).toContain('部署记录尚未核实')
  expect(xcmaxAdminApi.forceSelfMaintenanceRun).not.toHaveBeenCalled()
  wrapper.unmount()
})
it('does not convert missing gate decisions or invalid trend samples into a pass or zero rate', async () => {
  vi.mocked(xcmaxAdminApi.fetchAutonomyCrossTierGate).mockResolvedValueOnce({ rules: [{ tier: 'server', action_type: 'deploy' }] })
  vi.mocked(xcmaxAdminApi.fetchAutonomyOverview).mockResolvedValueOnce({ ...overview(), operating_metrics: { veto_rate_trend_30d: [{}, { veto_rate: null }] } })
  const wrapper = mount(XCmaxAdminAutonomyTab)
  await flushPromises()
  expect(wrapper.get('.gate-list .badge').text()).toBe('待核实')
  expect(wrapper.find('.chart').exists()).toBe(false)
  expect(wrapper.findAll('.kpi-value').at(-1)?.text()).toBe('待核实')
  wrapper.unmount()
})
