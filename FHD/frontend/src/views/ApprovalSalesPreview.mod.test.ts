import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { ref } from 'vue'
import AwDetailModal from '../../../mods/bridge/xcagi-approval-bridge/frontend/views/approval-workspace/AwDetailModal.vue'
import { formatRequestTitle } from '../../../mods/bridge/xcagi-approval-bridge/frontend/views/approval-workspace/awHelpers'

function render(items: Record<string, unknown>[], tool = 'sales', status = 'pending', runtime?: boolean, lineQuantities?: number[]) {
  const order = { customer_name: '验收客户', items }
  const sale = lineQuantities ? {
    action: 'execute_closed_loop',
    params: { payload: { order, fulfillment: { requested: true, line_quantities: lineQuantities } } },
  } : { action: 'create_order', params: order }
  const request = { id: 12, request_no: 'test-approval', title: '智能对话写操作：sales.create_order', status, runtime_available: runtime, business_type: 'workflow_tool', records: [], description: JSON.stringify({ customer_name: '验收客户', items }), business_data: { tool_id: tool, ...sale } }
  const before = JSON.stringify(request)
  const approve = vi.fn()
  const wrapper = mount(AwDetailModal, {
    props: { tm: { selectedRequest: ref(request), showDetails: ref(true), canApprove: ref(true), approve, reject: vi.fn(), closeDetails: vi.fn(), getBusinessLabel: String, getStatusLabel: String, getActionIcon: String, formatRequestTitle, formatTime: String, getWorkflowExecutionStatusLabel: String } as never },
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

  it('shows each proposed shipment quantity next to the original order quantity', () => {
    const f = render([
      { product_name: '商品甲', quantity: 10, unit_price: 2 },
      { product_name: '商品乙', quantity: 5, unit_price: 3 },
    ], 'sales', 'pending', undefined, [3, 5])
    expect(f.wrapper.get('thead').text()).toContain('本次交付')
    expect(f.wrapper.findAll('tbody tr').map(row => row.findAll('td').slice(2, 4).map(cell => cell.text())))
      .toEqual([['10', '3'], ['5', '5']])
    expect(f.approve).not.toHaveBeenCalled()
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


it.each(['approved', 'rejected', 'withdrawn', 'cancelled', 'completed'])(
  'does not present terminal %s requests as expired or actionable even with stale runtime flags', status => {
    const f = render([], 'sales', status, false)
    expect(f.wrapper.find('.expired-hint').exists()).toBe(false)
    expect(f.wrapper.find('.btn-reject').exists()).toBe(false)
    expect(f.wrapper.find('.btn-approve').exists()).toBe(false)
    f.wrapper.unmount()
  },
)

it.each(['pending', 'in_progress'])('retains rejection guidance for confirmed expired %s requests', status => {
  const f = render([], 'sales', status, false)
  expect(f.wrapper.find('.expired-hint').exists()).toBe(true)
  expect(f.wrapper.find('.btn-reject').exists()).toBe(true)
  expect(f.wrapper.find('.btn-approve').exists()).toBe(false)
  f.wrapper.unmount()
})
