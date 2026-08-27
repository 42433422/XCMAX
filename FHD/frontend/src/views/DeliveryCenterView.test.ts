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
    listUsers.mockResolvedValue({ users: [{ id: 72, username: 'guosheng', company: '国圣化工' }] })
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
