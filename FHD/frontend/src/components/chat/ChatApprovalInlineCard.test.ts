import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ChatApprovalInlineCard from './ChatApprovalInlineCard.vue'

const card = {
  approval_required: true,
  intent: 'print_shipment',
  reason: '打印前需要确认',
  blocking_nodes: ['printer-ready'],
  todo: ['核对订单', '确认打印'],
}

describe('ChatApprovalInlineCard', () => {
  it('renders approval as an inline flow instead of a dialog card', () => {
    const wrapper = mount(ChatApprovalInlineCard, { props: { card } })

    expect(wrapper.find('.approval-inline').exists()).toBe(true)
    expect(wrapper.find('.chat-approval-card').exists()).toBe(false)
    expect(wrapper.find('.approval-intent').text()).toBe('print_shipment')
    expect(wrapper.findAll('.approval-chip')).toHaveLength(1)
  })

  it('emits confirmation without changing the inline presentation', async () => {
    const wrapper = mount(ChatApprovalInlineCard, { props: { card } })

    await wrapper.find('.approval-btn--primary').trigger('click')
    expect(wrapper.emitted('confirm')).toHaveLength(1)
  })
})
