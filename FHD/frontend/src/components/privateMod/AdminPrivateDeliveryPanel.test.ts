import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import AdminPrivateDeliveryPanel from './AdminPrivateDeliveryPanel.vue'

const mockGetUserPrivateDelivery = vi.fn()

vi.mock('@/api/xcmaxAdmin', () => ({
  xcmaxAdminApi: {
    getUserPrivateDelivery: (id: number) => mockGetUserPrivateDelivery(id),
  },
}))

describe('AdminPrivateDeliveryPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetUserPrivateDelivery.mockResolvedValue({ data: { projects: [] } })
  })

  it('shows empty state when user has no private delivery projects', async () => {
    const wrapper = mount(AdminPrivateDeliveryPanel, { props: { userId: 7 } })
    await flushPromises()
    expect(mockGetUserPrivateDelivery).toHaveBeenCalledWith(7)
    expect(wrapper.text()).toContain('该用户还没有客户私有 Mod 交付状态')
  })

  it('skips fetch when userId is null', async () => {
    const wrapper = mount(AdminPrivateDeliveryPanel, { props: { userId: null } })
    await flushPromises()
    expect(mockGetUserPrivateDelivery).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('该用户还没有客户私有 Mod 交付状态')
  })

  it('renders project tracks, stage labels, and timeline notes', async () => {
    mockGetUserPrivateDelivery.mockResolvedValue({
      data: {
        projects: [
          {
            mod_id: 'customer-mod',
            name: '客户 Mod',
            overall_status: 'rework',
            overall_label: '返工中',
            tracks: {
              business: {
                status: 'testing',
                updated_at: '2026-07-29T10:00:00Z',
                timeline: [],
              },
              employees: {
                status: 'rework',
                updated_at: 'not-a-date',
                timeline: [
                  { status: 'rework', at: '2026-07-29T12:00:00Z', note: '补充回归用例' },
                ],
              },
            },
          },
        ],
      },
    })
    const wrapper = mount(AdminPrivateDeliveryPanel, { props: { userId: 7 } })
    await flushPromises()
    expect(wrapper.find('.admin-private-delivery').exists()).toBe(true)
    expect(wrapper.text()).toContain('客户 Mod')
    expect(wrapper.text()).toContain('测试中')
    expect(wrapper.text()).toContain('返工中')
    expect(wrapper.text()).toContain('补充回归用例')
    expect(wrapper.text()).toContain('暂无确认或返工记录')
    expect(wrapper.text()).toContain('not-a-date')
  })

  it('shows error when private delivery fetch fails', async () => {
    mockGetUserPrivateDelivery.mockRejectedValue(new Error('network down'))
    const wrapper = mount(AdminPrivateDeliveryPanel, { props: { userId: 3 } })
    await flushPromises()
    expect(wrapper.text()).toContain('客户交付状态读取失败：network down')
  })

  it('reloads when refresh button is clicked', async () => {
    const wrapper = mount(AdminPrivateDeliveryPanel, { props: { userId: 9 } })
    await flushPromises()
    mockGetUserPrivateDelivery.mockClear()
    mockGetUserPrivateDelivery.mockResolvedValue({ data: { projects: [] } })
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(mockGetUserPrivateDelivery).toHaveBeenCalledWith(9)
  })

  it('reloads when userId prop changes', async () => {
    const wrapper = mount(AdminPrivateDeliveryPanel, { props: { userId: 1 } })
    await flushPromises()
    mockGetUserPrivateDelivery.mockClear()
    await wrapper.setProps({ userId: 2 })
    await flushPromises()
    expect(mockGetUserPrivateDelivery).toHaveBeenCalledWith(2)
  })

  it('covers custom stage labels, empty timestamps, and non-Error failures', async () => {
    mockGetUserPrivateDelivery.mockResolvedValueOnce({
      data: {
        projects: [
          {
            mod_id: 'm1',
            name: 'Mod A',
            overall_status: 'partial',
            overall_label: '部分完成',
            stage_labels: { business: { production: '定制制作中' } },
            tracks: {
              business: { status: 'production', timeline: [{ status: 'custom-x' }] },
              employees: { status: 'unknown-stage', timeline: [] },
            },
          },
        ],
      },
    })
    const wrapper = mount(AdminPrivateDeliveryPanel, { props: { userId: 4 } })
    await flushPromises()
    expect(wrapper.text()).toContain('定制制作中')
    expect(wrapper.text()).toContain('unknown-stage')
    expect(wrapper.text()).toContain('—')

    mockGetUserPrivateDelivery.mockRejectedValueOnce('plain-failure')
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('客户交付状态读取失败：plain-failure')
  })
})
