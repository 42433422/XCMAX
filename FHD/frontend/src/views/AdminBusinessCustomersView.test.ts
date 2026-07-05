import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import AdminBusinessCustomersView from './AdminBusinessCustomersView.vue'

const mockListUsers = vi.fn()
const mockGetUserProfiles = vi.fn()
const mockListWallets = vi.fn()
const mockApiGet = vi.fn()

vi.mock('@/api/xcmaxAdmin', () => ({
  xcmaxAdminApi: {
    listUsers: () => mockListUsers(),
    getUserProfiles: () => mockGetUserProfiles(),
    listWallets: (limit: number, offset: number) => mockListWallets(limit, offset),
  },
}))

vi.mock('@/api/core', () => ({
  api: {
    get: (...args: unknown[]) => mockApiGet(...args),
  },
  default: {
    get: (...args: unknown[]) => mockApiGet(...args),
  },
}))

describe('AdminBusinessCustomersView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockListUsers.mockResolvedValue({
      users: [
        {
          id: 1,
          username: 'market-user',
          company: '平台注册客户',
          email: 'market@test.com',
          is_enterprise: true,
          mod_ids: ['mod-a', 'mod-b'],
          market_membership_tier: 'vip_plus',
        },
      ],
    })
    mockGetUserProfiles.mockResolvedValue({
      data: {
        'market-user': {
          tier: 'enterprise',
          industry_id: '涂料',
          account_tier: 'pro',
          budget_range: '5–10 万',
        },
      },
    })
    mockListWallets.mockResolvedValue({
      items: [{ user_id: 1, balance: 88 }],
    })
    mockApiGet.mockResolvedValue({
      data: [
        {
          id: 'erp-1',
          name: 'ERP业务客户',
          contact_person: '张三',
          contact_phone: '13800000000',
          contact_address: '成都',
        },
      ],
    })
  })

  it('renders platform customers and ERP customers together', async () => {
    const wrapper = mount(AdminBusinessCustomersView)
    await flushPromises()

    expect(wrapper.text()).toContain('平台注册客户')
    expect(wrapper.text()).toContain('ERP业务客户')
    expect(wrapper.text()).toContain('VIP+')
    expect(wrapper.text()).toContain('Pro')
    expect(wrapper.text()).toContain('2 个 Mod')
    expect(wrapper.text()).toContain('余额 ¥88.00')
  })

  it('filters across merged customer fields', async () => {
    const wrapper = mount(AdminBusinessCustomersView)
    await flushPromises()

    await wrapper.find('.admin-business-customers-search').setValue('张三')
    await flushPromises()

    const bodyText = wrapper.find('tbody').text()
    expect(bodyText).toContain('ERP业务客户')
    expect(bodyText).not.toContain('平台注册客户')
  })
})
