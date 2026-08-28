import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import DeliveryCenterView from '../../../admin-console/src/views/DeliveryCenterView.vue'

const listCustomDeliveries = vi.fn()
const listUsers = vi.fn()
const decideCustomDelivery = vi.fn()
const appAlert = vi.fn().mockResolvedValue(undefined)
const appConfirm = vi.fn().mockResolvedValue(true)

vi.mock('@/api/xcmaxAdmin', () => ({
  xcmaxAdminApi: {
    listCustomDeliveries: (...args: unknown[]) => listCustomDeliveries(...args),
    listUsers: (...args: unknown[]) => listUsers(...args),
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
  },
}

describe('DeliveryCenterView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    listUsers.mockResolvedValue({
      users: [
        { id: 72, username: 'guosheng', company: '国圣化工', is_enterprise: true },
        { id: 81, username: 'standard-co', company: '标准交付企业', is_enterprise: true },
      ],
      total: 2,
    })
    listCustomDeliveries.mockResolvedValue({ items: [structuredClone(delivery)] })
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
    expect(wrapper.text()).toContain('企业客户交付台账')
    expect(wrapper.text()).toContain('标准交付企业')
    expect(wrapper.text()).toContain('标准企业交付')
    expect(wrapper.text()).toContain('定制交付')
    expect(listUsers).toHaveBeenCalledWith(200, 0, true)
  })

  it('loads every enterprise-user page before rendering the delivery roster', async () => {
    listCustomDeliveries.mockResolvedValue({ items: [] })
    listUsers.mockImplementation((_limit: number, offset: number) => {
      if (offset === 0) {
        return Promise.resolve({
          users: [{ id: 101, username: 'enterprise-a', is_enterprise: true }],
          total: 2,
        })
      }
      return Promise.resolve({
        users: [{ id: 102, username: 'enterprise-b', is_enterprise: true }],
        total: 2,
      })
    })

    const wrapper = mount(DeliveryCenterView)
    await flushPromises()

    expect(listUsers).toHaveBeenNthCalledWith(1, 200, 0, true)
    expect(listUsers).toHaveBeenNthCalledWith(2, 200, 1, true)
    expect(wrapper.text()).toContain('enterprise-a')
    expect(wrapper.text()).toContain('enterprise-b')
    expect(wrapper.text()).toContain('暂无定制交付工单')
    expect(wrapper.text()).toContain('仍在上方“标准企业交付”台账中')
  })

  it('writes an audited acceptance decision through the real delivery endpoint', async () => {
    const wrapper = mount(DeliveryCenterView)
    await flushPromises()
    const accept = wrapper.findAll('button').find((button) => button.text().includes('管理员代验收'))
    expect(accept).toBeTruthy()
    await accept!.trigger('click')
    await flushPromises()
    expect(appConfirm).toHaveBeenCalled()
    expect(decideCustomDelivery).toHaveBeenCalledWith(
      9,
      'accept',
      '管理员在客户交付中心代为验收',
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
})
