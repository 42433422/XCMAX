import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import DeliveryCenterView from '../../../admin-console/src/views/DeliveryCenterView.vue'

const listCustomDeliveries = vi.fn()
const listStandardDeliveries = vi.fn()
const listUsers = vi.fn()
const listEntitlementFastLanePlans = vi.fn()
const getEntitlementFastLaneAccount = vi.fn()
const mutateEntitlementFastLane = vi.fn()
const listTrialDeliveries = vi.fn()
const decideCustomDelivery = vi.fn()
const appAlert = vi.fn().mockResolvedValue(undefined)
const appConfirm = vi.fn().mockResolvedValue(true)

vi.mock('@/api/xcmaxAdmin', () => ({
  xcmaxAdminApi: {
    listCustomDeliveries: (...args: unknown[]) => listCustomDeliveries(...args),
    listStandardDeliveries: (...args: unknown[]) => listStandardDeliveries(...args),
    listUsers: (...args: unknown[]) => listUsers(...args),
    listEntitlementFastLanePlans: (...args: unknown[]) => listEntitlementFastLanePlans(...args),
    getEntitlementFastLaneAccount: (...args: unknown[]) => getEntitlementFastLaneAccount(...args),
    mutateEntitlementFastLane: (...args: unknown[]) => mutateEntitlementFastLane(...args),
    listTrialDeliveries: (...args: unknown[]) => listTrialDeliveries(...args),
    decideCustomDelivery: (...args: unknown[]) => decideCustomDelivery(...args),
  },
}))

vi.mock('@/utils/appDialog', () => ({
  appAlert: (...args: unknown[]) => appAlert(...args),
  appConfirm: (...args: unknown[]) => appConfirm(...args),
}))

const delivery = {
  id: 9,
  user_id: 72,
  ticket_no: 'CD20260827001',
  title: '涂料质检 AI 员工',
  updated_at: '2026-08-27T06:00:00Z',
  custom_delivery: {
    kind: 'bundle',
    requirements: '读取质检单并核对批次、颜色与检验结论。',
    acceptance_criteria: '沙箱和真实执行用例全部通过。',
    stage: 'acceptance',
    stage_label: '质量门通过，待您验收',
    gate_ok: true,
    gate_message: '产物和质量门已通过',
    runs: [{ attempt: 2, status: 'done', steps: [{ id: 'verify', status: 'done' }] }],
    artifacts: [{ kind: 'module', id: 'coating-quality-private' }],
    install_receipts: [],
    pricing_mode: 'initial_included',
    pricing_label: '首次交付内含，交付前开发免费',
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
    install: { ok: true, installed_devices: 1, latest_receipt: { platform: 'win32', status: 'installed' } },
    first_login: { ok: true, at: '2026-08-27T07:00:00Z' },
    completion_rule: 'installed_and_first_login',
    available_installers: ['macOS', 'Windows'],
  },
]

const trialDeliveries = [
  {
    delivery_no: 'STD-ORDER-TRIAL-001',
    delivery_type: 'standard_desktop',
    license_type: 'trial',
    expires_at: '2026-09-29T09:05:00+00:00',
    status: 'pending_install',
    status_label: '账号已创建，待安装',
    account: { id: 95, username: 'trial-user', company: '体验测试用户', is_enterprise: false },
    plan: {
      id: 'saas-trial-30',
      title: '30 天全功能体验',
      account_tier: 'normal',
      license_type: 'trial',
      amount_cents: 9900,
    },
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
    listUsers.mockResolvedValue({ users: standardDeliveries.map((row) => row.account) })
    listEntitlementFastLanePlans.mockResolvedValue({
      items: [
        { id: 'saas-trial-30', title: '30 天全功能体验', catalog: 'account_license', license_type: 'trial', duration_days: 30 },
        { id: 'saas-permanent-starter', title: '企业启航版', catalog: 'account_license', license_type: 'permanent', account_tier: 'normal' },
        { id: 'saas-permanent-growth', title: '企业成长版', catalog: 'account_license', license_type: 'permanent', account_tier: 'pro' },
        { id: 'saas-permanent-max', title: '集团协同版', catalog: 'account_license', license_type: 'permanent', account_tier: 'max' },
        { id: 'saas-permanent-ultra', title: '企业旗舰版', catalog: 'account_license', license_type: 'permanent', account_tier: 'ultra' },
        { id: 'plan_svip', title: 'SVIP', catalog: 'membership', license_type: 'membership', duration_days: 30 },
      ],
    })
    getEntitlementFastLaneAccount.mockResolvedValue({ account: { username: 'guosheng' }, active_plans: [] })
    mutateEntitlementFastLane.mockResolvedValue({
      ok: true,
      account: { username: 'guosheng' },
      active_plans: [{ user_plan_id: 901, plan_id: 'saas-permanent-ultra', title: '企业旗舰版', catalog: 'account_license' }],
      audit: { idempotency_key: 'fast-lane-ui-test' },
      commerce: { order_generated: false, payment_generated: false, transaction_generated: false },
    })
    decideCustomDelivery.mockResolvedValue({ success: true })
    appConfirm.mockResolvedValue(true)
  })

  it('renders the real customer, quality gate, artifact, and receipt state', async () => {
    const wrapper = mount(DeliveryCenterView)
    await flushPromises()
    expect(wrapper.text()).toContain('客户交付中心')
    expect(wrapper.text()).toContain('国圣化工')
    expect(wrapper.text()).toContain('生产质量门已通过')
    expect(wrapper.text()).toContain('coating-quality-private')
    expect(wrapper.text()).toContain('0/1 已安装')
    expect(wrapper.text()).toContain('待客户安装回执')
    expect(wrapper.text()).toContain('购买账户标准交付台账')
    expect(wrapper.text()).toContain('标准交付企业')
    expect(wrapper.text()).toContain('企业成长版')
    expect(wrapper.text()).toContain('安装并首次登录完成')
    expect(wrapper.text()).toContain('首次交付内含，交付前开发免费')
    expect(wrapper.text()).toContain('权益快速通道')
    expect(wrapper.text()).toContain('企业旗舰版')
    expect(wrapper.text()).toContain('终端同源快捷模式')
    expect(wrapper.text()).toContain('¥99 体验账户交付台账')
    expect(wrapper.text()).toContain('体验测试用户')
    expect(wrapper.text()).toContain('30 天全功能体验')
    expect(wrapper.text()).toContain('30 天体验')
    expect(listStandardDeliveries).toHaveBeenCalledTimes(1)
    expect(listTrialDeliveries).toHaveBeenCalledTimes(1)
  })

  it('shows the trial summary card and keeps trial accounts out of the permanent roster', async () => {
    const wrapper = mount(DeliveryCenterView)
    await flushPromises()

    const trialCard = wrapper.findAll('.delivery-stats article').find((card) => card.text().includes('体验账户'))
    expect(trialCard).toBeTruthy()
    expect(trialCard!.text()).toContain('¥99 · 30 天全功能体验')

    const rosters = wrapper.findAll('.enterprise-roster')
    expect(rosters.length).toBe(2)
    expect(rosters[0].text()).not.toContain('体验测试用户')
    expect(rosters[1].text()).toContain('体验测试用户')
    expect(rosters[1].text()).toContain('1 个体验账户')
  })

  it('does not treat enterprise flags without a permanent purchase as deliveries', async () => {
    listCustomDeliveries.mockResolvedValue({ items: [] })
    listStandardDeliveries.mockResolvedValue({ items: [], total: 0, ssot: 'active_permanent_user_plan' })
    listTrialDeliveries.mockResolvedValue({ items: [], total: 0, ssot: 'active_trial_user_plan' })

    const wrapper = mount(DeliveryCenterView)
    await flushPromises()

    expect(wrapper.text()).toContain('尚无有效的永久购买账户')
    expect(wrapper.text()).toContain('尚无有效的体验账户')
    expect(wrapper.text()).toContain('暂无定制交付工单')
    expect(wrapper.text()).toContain('首次定制交付前的开发免费')
  })

  it('writes an audited acceptance decision through the real delivery endpoint', async () => {
    const wrapper = mount(DeliveryCenterView)
    await flushPromises()
    const accept = wrapper.findAll('button').find((button) => button.text().includes('内部质量确认'))
    expect(accept).toBeTruthy()
    await accept!.trigger('click')
    await flushPromises()
    expect(appConfirm).toHaveBeenCalled()
    expect(decideCustomDelivery).toHaveBeenCalledWith(
      9,
      'accept',
      '管理员仅完成内部质量确认，等待客户本人验收',
    )
  })

  it('requires a concrete rework reason before restarting production', async () => {
    const wrapper = mount(DeliveryCenterView)
    await flushPromises()
    const rework = wrapper.findAll('button').find((button) => button.text().includes('发起返工'))
    await rework!.trigger('click')
    expect(appAlert).toHaveBeenCalledWith('请填写至少 4 个字的具体返工原因')
    expect(decideCustomDelivery).not.toHaveBeenCalled()

    await wrapper.find('.delivery-actions__controls input').setValue('颜色比对用例缺失')
    await rework!.trigger('click')
    await flushPromises()
    expect(decideCustomDelivery).toHaveBeenCalledWith(9, 'rework', '颜色比对用例缺失')
  })

  it('binds any selected tier through the audited non-commerce fast lane', async () => {
    const wrapper = mount(DeliveryCenterView)
    await flushPromises()
    const panel = wrapper.get('section[aria-label="权益快速通道"]')
    await panel.get('input[placeholder="用户 ID、用户名或邮箱"]').setValue('guosheng')
    await panel.get('select').setValue('saas-permanent-ultra')
    await panel.get('input[placeholder*="创始人确认"]').setValue('创始人确认旗舰版授权')
    const bind = panel.findAll('button').find((button) => button.text().includes('绑定 / 替换权益'))
    await bind!.trigger('click')
    await flushPromises()

    expect(appConfirm).toHaveBeenCalled()
    expect(mutateEntitlementFastLane).toHaveBeenCalledTimes(1)
    const payload = mutateEntitlementFastLane.mock.calls[0][0]
    expect(payload).toEqual(expect.objectContaining({
      account: 'guosheng',
      action: 'assign',
      plan_id: 'saas-permanent-ultra',
      reason: '创始人确认旗舰版授权',
      idempotency_key: expect.stringMatching(/^fast-lane-ui-assign-/),
    }))
    expect(payload).not.toHaveProperty('order_no')
    expect(payload).not.toHaveProperty('payment')
    expect(payload).not.toHaveProperty('wallet')
    expect(panel.text()).toContain('企业旗舰版')
  })

  it('does not block the fast lane when the optional account suggestions are slow', async () => {
    let resolveUsers: (value: { users: unknown[] }) => void = () => undefined
    listUsers.mockReturnValueOnce(new Promise((resolve) => {
      resolveUsers = resolve
    }))

    const wrapper = mount(DeliveryCenterView)
    await flushPromises()
    const panel = wrapper.get('section[aria-label="权益快速通道"]')
    expect(panel.text()).toContain('企业旗舰版')
    expect(panel.get('select').attributes('disabled')).toBeUndefined()

    resolveUsers({ users: [] })
    await flushPromises()
  })
})
