import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import RefundApplyView from './RefundApplyView.vue'

vi.mock('../api', () => ({
  api: {
    refundsMy: vi.fn(),
    refundsApply: vi.fn(),
  },
}))

import { api } from '../api'

describe('RefundApplyView', () => {
  let router: ReturnType<typeof createRouter>

  beforeEach(() => {
    vi.clearAllMocks()
    router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', name: 'refunds', component: { template: '<div />' } },
      ],
    })
  })

  it('renders title and form', async () => {
    vi.mocked(api.refundsMy).mockResolvedValue({ refunds: [] })
    router.push('/')
    await router.isReady()

    const wrapper = mount(RefundApplyView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('退款申请')
    expect(wrapper.find('input[placeholder]').exists()).toBe(true)
    expect(wrapper.find('textarea').exists()).toBe(true)
  })

  it('shows empty refund list', async () => {
    vi.mocked(api.refundsMy).mockResolvedValue({ refunds: [] })
    router.push('/')
    await router.isReady()

    const wrapper = mount(RefundApplyView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('暂无记录')
  })

  it('renders refund records in table', async () => {
    vi.mocked(api.refundsMy).mockResolvedValue({
      refunds: [
        { id: 1, order_no: 'ORD-001', amount: 99.9, reason: '不想要了', status: 'pending', created_at: '2026-01-01' },
      ],
    })
    router.push('/')
    await router.isReady()

    const wrapper = mount(RefundApplyView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('ORD-001')
    expect(wrapper.text()).toContain('99.90')
    expect(wrapper.text()).toContain('待审核')
  })

  it('disables submit button when form is invalid', async () => {
    vi.mocked(api.refundsMy).mockResolvedValue({ refunds: [] })
    router.push('/')
    await router.isReady()

    const wrapper = mount(RefundApplyView, { global: { plugins: [router] } })
    await flushPromises()

    const btn = wrapper.find('button.btn-primary')
    expect(btn.attributes('disabled')).toBeDefined()
  })

  it('shows loading state for refund list', async () => {
    vi.mocked(api.refundsMy).mockReturnValue(new Promise(() => {}))
    router.push('/')
    await router.isReady()

    const wrapper = mount(RefundApplyView, { global: { plugins: [router] } })
    expect(wrapper.text()).toContain('加载中')
  })

  it('pre-fills order number from query param', async () => {
    vi.mocked(api.refundsMy).mockResolvedValue({ refunds: [] })
    router.push('/?order_no=ORD-123')
    await router.isReady()

    const wrapper = mount(RefundApplyView, { global: { plugins: [router] } })
    await flushPromises()

    const input = wrapper.find('input[placeholder]')
    expect((input.element as HTMLInputElement).value).toBe('ORD-123')
  })

  it('submits refund and shows success message', async () => {
    vi.mocked(api.refundsMy).mockResolvedValue({ refunds: [] })
    vi.mocked(api.refundsApply).mockResolvedValue({ ok: true })
    router.push('/')
    await router.isReady()

    const wrapper = mount(RefundApplyView, { global: { plugins: [router] } })
    await flushPromises()

    const inputs = wrapper.findAll('input')
    const orderInput = inputs[0]
    await orderInput.setValue('ORD-001')

    const textarea = wrapper.find('textarea')
    await textarea.setValue('这是一个有效的退款原因说明文字')

    const btn = wrapper.find('button.btn-primary')
    expect(btn.attributes('disabled')).toBeUndefined()

    await btn.trigger('click')
    await flushPromises()

    expect(api.refundsApply).toHaveBeenCalledWith('ORD-001', '这是一个有效的退款原因说明文字')
    expect(wrapper.text()).toContain('已提交申请')
  })

  it('shows error on submit failure', async () => {
    vi.mocked(api.refundsMy).mockResolvedValue({ refunds: [] })
    vi.mocked(api.refundsApply).mockRejectedValue(new Error('申请失败'))
    router.push('/')
    await router.isReady()

    const wrapper = mount(RefundApplyView, { global: { plugins: [router] } })
    await flushPromises()

    const inputs = wrapper.findAll('input')
    await inputs[0].setValue('ORD-001')
    await wrapper.find('textarea').setValue('这是一个有效的退款原因说明文字')

    await wrapper.find('button.btn-primary').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('申请失败')
  })

  it('disables submit button when reason is too short', async () => {
    vi.mocked(api.refundsMy).mockResolvedValue({ refunds: [] })
    router.push('/')
    await router.isReady()

    const wrapper = mount(RefundApplyView, { global: { plugins: [router] } })
    await flushPromises()

    const inputs = wrapper.findAll('input')
    await inputs[0].setValue('ORD-001')
    await wrapper.find('textarea').setValue('短')

    const btn = wrapper.find('button.btn-primary')
    expect(btn.attributes('disabled')).toBeDefined()
  })
})
