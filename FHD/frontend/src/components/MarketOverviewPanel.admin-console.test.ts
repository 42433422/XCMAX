import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import MarketOverviewPanel from '../../../admin-console/src/components/admin/MarketOverviewPanel.vue'
import { xcmaxMarketProxy } from '@/api/xcmaxMarketProxy'

vi.mock('@/api/xcmaxMarketProxy', () => ({
  xcmaxMarketProxy: { adminMarketStatus: vi.fn() },
  default: { adminMarketStatus: vi.fn() },
}))

beforeEach(() => {
  vi.clearAllMocks()
})

it('renders market business metrics from admin status', async () => {
  vi.mocked(xcmaxMarketProxy.adminMarketStatus).mockResolvedValue({
    ok: true,
    total_catalog_items: 532,
    total_users: 21,
  })
  const wrapper = mount(MarketOverviewPanel, {
    global: {
      stubs: {
        RouterLink: { template: '<a><slot /></a>', props: ['to'] },
      },
    },
  })
  await flushPromises()
  expect(wrapper.text()).toContain('智能生态市场总览')
  expect(wrapper.text()).toContain('市场商品总数')
  expect(wrapper.text()).toContain('532')
  expect(wrapper.text()).toContain('注册用户')
  expect(wrapper.text()).toContain('21')
  expect(wrapper.text()).toContain('非 Full-Pipeline')
  expect(wrapper.find('iframe').exists()).toBe(false)
  wrapper.unmount()
})

it('shows error when market status fails', async () => {
  vi.mocked(xcmaxMarketProxy.adminMarketStatus).mockRejectedValue(new Error('服务暂不可用'))
  const wrapper = mount(MarketOverviewPanel, {
    global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })
  await flushPromises()
  expect(wrapper.text()).toContain('市场指标暂未能加载')
  expect(wrapper.text()).toContain('服务暂不可用')
  wrapper.unmount()
})
