import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import DeliveryCenterView from '../../../admin-console/src/views/DeliveryCenterView.vue'

const listCustomDeliveries = vi.fn()
const listStandardDeliveries = vi.fn()
const listUsers = vi.fn()
const listTrialDeliveries = vi.fn()
const push = vi.fn()

vi.mock('@/api/xcmaxAdmin', () => ({
  xcmaxAdminApi: {
    listCustomDeliveries: (...args: unknown[]) => listCustomDeliveries(...args),
    listStandardDeliveries: (...args: unknown[]) => listStandardDeliveries(...args),
    listUsers: (...args: unknown[]) => listUsers(...args),
    listTrialDeliveries: (...args: unknown[]) => listTrialDeliveries(...args),
  },
}))
vi.mock('vue-router', () => ({ useRouter: () => ({ push }) }))
vi.mock('@/utils/appDialog', () => ({ appAlert: vi.fn(), appConfirm: vi.fn() }))

const delivery = {
  id: 9,
  user_id: 72,
  ticket_no: 'CD20260827001',
  title: '涂料质检 AI 员工',
  updated_at: '2026-08-27T06:00:00Z',
  custom_delivery: {
    kind: 'bundle',
    stage: 'acceptance',
    stage_label: '质量门通过，待您验收',
    gate_ok: true,
    runs: [{ attempt: 2, status: 'done', steps: [{ id: 'verify', status: 'done' }] }],
    artifacts: [{ kind: 'module', id: 'coating-quality-private' }],
    install_receipts: [],
    pricing_mode: 'initial_included',
    commerce_ready: true,
  },
}

const standardDeliveries = [
  {
    delivery_no: 'STD-ORDER-001',
    delivery_type: 'standard_desktop',
    status: 'pending_install',
    status_label: '账号已创建，待安装',
    account: { id: 72, username: 'guosheng', company: '国圣化工', is_enterprise: true },
    plan: { id: 'saas-permanent-growth', title: '企业成长版', account_tier: 'pro', license_type: 'permanent' },
    order: { order_no: 'ORDER-001', status: 'paid' },
    install: { ok: false, installed_devices: 0, latest_receipt: null },
    first_login: { ok: false, at: '' },
    completion_rule: 'installed_and_first_login',
    available_installers: ['macOS', 'Windows'],
  },
  {
    delivery_no: 'STD-ORDER-002',
    delivery_type: 'standard_desktop',
    status: 'completed',
    status_label: '安装并首次登录完成',
    account: { id: 81, username: 'standard-co', company: '标准交付企业', is_enterprise: true },
    plan: { id: 'saas-permanent-starter', title: '企业启航版', account_tier: 'normal', license_type: 'permanent' },
    order: { order_no: 'ORDER-002', status: 'paid' },
    install: { ok: true, installed_devices: 1, latest_receipt: null },
    first_login: { ok: true, at: '2026-08-27T07:00:00Z' },
    completion_rule: 'installed_and_first_login',
    available_installers: ['macOS', 'Windows'],
  },
]

const enterpriseUsers = [
  ...standardDeliveries.map((row) => row.account),
  { id: 90, username: 'enterprise-without-plan', company: '无套餐企业', is_enterprise: true },
]

const trialDeliveries = [
  {
    delivery_no: 'STD-ORDER-TRIAL-001',
    delivery_type: 'standard_desktop',
    license_type: 'trial',
    status: 'pending_install',
    status_label: '账号已创建，待安装',
    account: { id: 95, username: 'trial-user', company: '体验测试用户', is_enterprise: false },
    plan: { id: 'saas-trial-30', title: '30 天全功能体验', account_tier: 'normal', license_type: 'trial' },
    order: { order_no: 'ORDER-TRIAL-001', status: 'entitlement_granted' },
    install: { ok: false, installed_devices: 0, latest_receipt: null },
    first_login: { ok: false, at: '' },
    completion_rule: 'installed_and_first_login',
    available_installers: ['macOS', 'Windows'],
  },
]

describe('DeliveryCenterView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    listStandardDeliveries.mockResolvedValue({ items: structuredClone(standardDeliveries), total: 2 })
    listTrialDeliveries.mockResolvedValue({ items: structuredClone(trialDeliveries), total: 1 })
    listCustomDeliveries.mockResolvedValue({ items: [structuredClone(delivery)] })
    listUsers.mockResolvedValue({ users: structuredClone(enterpriseUsers), total: enterpriseUsers.length })
    push.mockResolvedValue(undefined)
  })

  it('keeps delivery tabs without a custom ticket tab and shows the real roster data', async () => {
    const wrapper = mount(DeliveryCenterView)
    await flushPromises()
    const tabs = wrapper.get('.delivery-tabs').text()
    expect(tabs).toContain('购买交付 2')
    expect(tabs).toContain('体验交付 1')
    expect(tabs).toContain('企业客户 3')
    expect(tabs).toContain('Mac 设备')
    expect(tabs).not.toContain('定制工单')
    expect(wrapper.find('#delivery-custom-orders').exists()).toBe(false)
    expect(wrapper.text()).toContain('企业客户交付台账')
    expect(wrapper.text()).toContain('国圣化工')
    expect(wrapper.text()).toContain('购买账户标准交付台账')
    expect(wrapper.text()).toContain('¥99 体验账户交付台账')
    expect(listStandardDeliveries).toHaveBeenCalledTimes(1)
    expect(listTrialDeliveries).toHaveBeenCalledTimes(1)
    expect(listUsers).toHaveBeenCalledWith(200, 0, true)
  })

  it('opens the customer service ticket list for enterprise custom work', async () => {
    const wrapper = mount(DeliveryCenterView)
    await flushPromises()
    const button = wrapper.findAll('button').find((row) => row.text().includes('查看定制工单'))!
    await button.trigger('click')
    expect(push).toHaveBeenCalledWith({ name: 'customer-service-tickets', query: { account_id: '72', type: 'delivery' } })
  })

  it('shows unknown counts on failure and recovers with retry', async () => {
    listStandardDeliveries.mockRejectedValueOnce(new Error('连接失败'))
    const wrapper = mount(DeliveryCenterView)
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('连接失败')
    expect(wrapper.findAll('.delivery-stats strong').map((row) => row.text())).toEqual(['—', '—', '—', '—'])
    expect(wrapper.find('#delivery-standard-roster').exists()).toBe(false)
    await wrapper.get('[role="alert"] button').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.get('#delivery-standard-roster').isVisible()).toBe(true)
    expect(wrapper.findAll('.delivery-stats strong').map((row) => row.text())).toEqual(['1', '0', '1', '1'])
    wrapper.unmount()
  })
})
