import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const customerDeliveryList = vi.fn()
const customerDeliveryCreate = vi.fn()
const customerDeliveryDecision = vi.fn()
const customerDeliveryDownload = vi.fn()
const customerDeliveryInstalled = vi.fn()
const customerDeliveryCheckout = vi.fn()

vi.mock('../api', () => ({
  api: {
    customerDeliveryList: (...args: unknown[]) => customerDeliveryList(...args),
    customerDeliveryCreate: (...args: unknown[]) => customerDeliveryCreate(...args),
    customerDeliveryDecision: (...args: unknown[]) => customerDeliveryDecision(...args),
    customerDeliveryDownload: (...args: unknown[]) => customerDeliveryDownload(...args),
    customerDeliveryInstalled: (...args: unknown[]) => customerDeliveryInstalled(...args),
    customerDeliveryCheckout: (...args: unknown[]) => customerDeliveryCheckout(...args),
  },
}))

import CustomerDeliveriesView from './CustomerDeliveriesView.vue'

function ticket(overrides: Record<string, unknown> = {}) {
  return {
    id: 21,
    ticket_no: 'CSD-PYTEST-21',
    title: '合同审核员工',
    custom_delivery: {
      kind: 'bundle',
      title: '合同审核员工',
      requirements: '分析合同并输出风险结果。',
      acceptance_criteria: '真实样本通过。',
      stage: 'acceptance',
      stage_label: '质量门通过，待您验收',
      gate_ok: true,
      gate_message: '质量门通过',
      acceptance_status: 'internal_approved',
      pricing_mode: 'initial_included',
      pricing_label: '首次交付内含，交付前开发免费',
      commerce_ready: true,
      artifacts: [],
      ...overrides,
    },
  }
}

describe('CustomerDeliveriesView', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.clearAllMocks()
    localStorage.clear()
    customerDeliveryDecision.mockResolvedValue(ticket())
    customerDeliveryCreate.mockResolvedValue(ticket())
    customerDeliveryInstalled.mockResolvedValue(ticket({ stage: 'delivered' }))
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:delivery')
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
  })

  it('显示首次内含规则并由客户本人验收', async () => {
    customerDeliveryList.mockResolvedValue({ items: [ticket()] })
    const wrapper = mount(CustomerDeliveriesView)
    await flushPromises()

    expect(wrapper.text()).toContain('首次交付内含，交付前开发免费')
    expect(wrapper.text()).toContain('请由购买账户本人验收')
    const accept = wrapper.findAll('button').find((button) => button.text().includes('本人确认验收'))
    expect(accept).toBeTruthy()
    await accept!.trigger('click')
    await flushPromises()
    expect(customerDeliveryDecision).toHaveBeenCalledWith(21, 'accept', '客户本人确认产物符合验收标准')
  })

  it('将下载令牌与客户安装回执绑定', async () => {
    const artifact = { kind: 'employee' as const, id: 'contract-review-pack' }
    const installing = ticket({
      stage: 'delivering',
      stage_label: '验收通过，待安装回执',
      acceptance_status: 'accepted',
      artifacts: [artifact],
    })
    customerDeliveryList.mockResolvedValue({ items: [installing] })
    customerDeliveryDownload.mockResolvedValue({
      blob: new Blob(['delivery']),
      filename: 'contract-review-pack.xcemp',
      receiptToken: 'receipt-token-1234567890',
    })
    const wrapper = mount(CustomerDeliveriesView)
    await flushPromises()

    const download = wrapper.findAll('button').find((button) => button.text().includes('下载产物'))
    await download!.trigger('click')
    await flushPromises()
    const installed = wrapper.findAll('button').find((button) => button.text().includes('确认桌面端已安装'))
    expect(installed?.attributes('disabled')).toBeUndefined()
    await installed!.trigger('click')
    await flushPromises()
    expect(customerDeliveryInstalled).toHaveBeenCalledWith(
      21,
      expect.objectContaining({
        artifact_kind: 'employee',
        artifact_id: 'contract-review-pack',
        receipt_token: 'receipt-token-1234567890',
      }),
    )
  })

  it('交付后新增开发只在确认报价后显示支付入口', async () => {
    customerDeliveryList.mockResolvedValue({
      items: [
        ticket({
          stage: 'commerce',
          pricing_mode: 'post_delivery_addon',
          pricing_label: '交付后新增，报价付款后生产',
          commerce_ready: false,
          crm: {
            quote: { status: 'accepted', quote_no: 'QT-001', amount: 3000, currency: 'CNY' },
            payment: { status: 'unpaid' },
          },
        }),
      ],
    })
    customerDeliveryCheckout.mockRejectedValue(new Error('支付服务测试拦截'))
    const wrapper = mount(CustomerDeliveriesView)
    await flushPromises()

    expect(wrapper.text()).toContain('报价 CNY 3,000.00')
    const pay = wrapper.findAll('button').find((button) => button.text().includes('支付已确认报价'))
    expect(pay).toBeTruthy()
    await pay!.trigger('click')
    await flushPromises()
    expect(customerDeliveryCheckout).toHaveBeenCalledWith(21, 'alipay')
    expect(wrapper.text()).toContain('支付服务测试拦截')
  })
})
