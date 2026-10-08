import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { ref } from 'vue'
import AwDetailModal from '../../../mods/xcagi-approval-bridge/frontend/views/approval-workspace/AwDetailModal.vue'

function render(items: Record<string, unknown>[], tool = 'sales') {
  const request = { id: 12, request_no: 'test-approval', title: '智能对话写操作：sales.create_order', status: 'pending', business_type: 'workflow_tool', records: [], description: JSON.stringify({ customer_name: '验收客户', items }), business_data: { tool_id: tool, action: 'create_order', params: { customer_name: '验收客户', items } } }
  const before = JSON.stringify(request)
  const approve = vi.fn()
  const wrapper = mount(AwDetailModal, {
    props: { tm: { selectedRequest: ref(request), showDetails: ref(true), canApprove: ref(true), approve, reject: vi.fn(), closeDetails: vi.fn(), getBusinessLabel: String, getStatusLabel: String, getActionIcon: String, formatTime: String, getWorkflowExecutionStatusLabel: String } as never },
    global: { stubs: { Modal: { template: '<section><slot/><slot name="footer"/></section>' } } },
  })
  return { wrapper, approve, request, before }
}

describe('sales approval details before execution', () => {
  it('shows the actual customer, item and total before approving the same request once', async () => {
    const f = render([{ product_name: '验收包装盒', model_number: 'BOX-1', quantity: 2, unit_price: 12.5 }])
    expect(f.wrapper.text()).toContain('验收客户')
    expect(f.wrapper.text()).toContain('验收包装盒')
    expect(f.wrapper.text()).toContain('BOX-1')
    expect(f.wrapper.get('[data-testid="sales-approval-total"]').text()).toContain('25.00 CNY')
    expect(f.approve).not.toHaveBeenCalled()
    await f.wrapper.get('.btn-approve').trigger('click')
    expect(f.approve).toHaveBeenCalledExactlyOnceWith(12)
    expect(JSON.stringify(f.request)).toBe(f.before)
    f.wrapper.unmount()
  })

  it.each([undefined, null, '', false, -1])('does not invent a price or total for %s', price => {
    const f = render([{ product_name: '验收商品', quantity: 2, unit_price: price }])
    expect(f.wrapper.get('[data-testid="sales-approval-total"]').text()).toContain('金额待确认')
    expect(f.approve).not.toHaveBeenCalled()
    f.wrapper.unmount()
  })

  it('adds decimal terms exactly, including an explicitly free item', () => {
    const f = render([{ quantity: 3, unit_price: '0.1' }, { quantity: 1, unit_price: '0.2' }, { quantity: 2, unit_price: 0 }])
    expect(f.wrapper.get('[data-testid="sales-approval-total"]').text()).toContain('0.50 CNY')
    f.wrapper.unmount()
  })

  it('does not derive a sales action from a forged title', () => {
    const f = render([{ quantity: 2, unit_price: 12.5 }], 'business_db')
    expect(f.wrapper.find('[data-testid="sales-approval-total"]').exists()).toBe(false)
    f.wrapper.unmount()
  })
})
