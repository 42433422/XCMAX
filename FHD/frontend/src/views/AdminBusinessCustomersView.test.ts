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
  it.each([
    [mockListUsers, '平台客户读取失败', 'ERP业务客户'],
    [mockGetUserProfiles, '账号档位读取失败', '平台注册客户'],
    [mockListWallets, '钱包读取失败', '余额查询失败'],
    [mockApiGet, 'ERP客户读取失败', '平台注册客户'],
  ])('preserves available customer data when a source fails, then clears the warning on retry', async (source, label, retained) => {
    source.mockRejectedValueOnce(new Error('offline'))
    const wrapper = mount(AdminBusinessCustomersView)
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain(label)
    expect(wrapper.get('tbody').text()).toContain(retained)
    await wrapper.get('.admin-business-customers-head button').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.get('tbody').text()).toContain('平台注册客户')
    expect(wrapper.get('tbody').text()).toContain('ERP业务客户')
    wrapper.unmount()
  })

  it('renders alternate customer identifiers, tiers, and missing or invalid balances', async () => {
    mockListUsers.mockResolvedValue({ data: { users: [
      { user_id: 2, name: '管理员', is_admin: true, plan_tier: 'vip', mobile: '123' },
      { id: 'local', company_name: '个人客户', membership: { label: 'free' }, account_tier: 'custom' },
      { id: 3, username: '余额异常', membership_tier: 'bespoke' }, {},
    ] } })
    mockGetUserProfiles.mockResolvedValue(null)
    mockListWallets.mockResolvedValue({ data: { items: [{ user_id: 2, balance: '' }, { user_id: 3, balance: 'invalid' }, null] } })
    mockApiGet.mockResolvedValue({ customers: [{ customer_name: '客户别名', address: '杭州' }, { unit_name: '单位别名' }, {}] })
    const wrapper = mount(AdminBusinessCustomersView)
    await flushPromises()
    const rows = wrapper.findAll('tbody tr')
    expect(rows).toHaveLength(7)
    for (const [index, expected] of [[0, '管理员'], [0, '余额 ¥0.00'], [1, '个人'], [1, 'custom'], [2, '余额 -'], [2, 'BESPOKE'], [3, '客户 4'], [4, '杭州'], [5, '单位别名']] as const) expect(rows[index].text()).toContain(expected)
    wrapper.unmount()
  })

  it.each([null, { data: 'unavailable' }])('keeps malformed list responses empty and retryable: %j', async (response) => {
    mockListUsers.mockResolvedValue(response)
    mockListWallets.mockResolvedValue(response)
    mockApiGet.mockResolvedValue(response)
    const wrapper = mount(AdminBusinessCustomersView)
    await flushPromises()
    expect(wrapper.get('tbody').text()).toBe('暂无客户数据')
    expect(wrapper.get('.admin-business-customers-head button').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

})
