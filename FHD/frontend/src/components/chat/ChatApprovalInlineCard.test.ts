import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import ChatApprovalInlineCard from './ChatApprovalInlineCard.vue'

const push = vi.fn()

vi.mock('vue-router', () => ({
  useRouter: () => ({ push }),
}))

const card = {
  approval_required: true,
  intent: 'print_shipment',
  reason: '打印前需要确认',
  blocking_nodes: ['printer-ready'],
  todo: ['核对订单', '确认打印'],
}

describe('ChatApprovalInlineCard', () => {
  beforeEach(() => {
    push.mockReset()
  })

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

  it('shows the persisted request number and uses SPA navigation to open the approval workspace', async () => {
    const persistedCard = {
      ...card,
      approval_request_ids: ['req-crud-1'],
      approval_path: '/mod/xcagi-approval-bridge/approval-hub/workspace?request_no=req-crud-1',
    }
    const wrapper = mount(ChatApprovalInlineCard, { props: { card: persistedCard } })

    expect(wrapper.text()).toContain('req-crud-1')
    expect(wrapper.text()).toContain('前往审批')
    expect(wrapper.text()).not.toContain('取消')
    expect(wrapper.find('.approval-btn--primary').attributes('href')).toBe(persistedCard.approval_path)
    await wrapper.find('.approval-btn--primary').trigger('click')
    expect(push).toHaveBeenCalledWith(persistedCard.approval_path)
    expect(wrapper.emitted('confirm')).toBeUndefined()
  })

  it('does not navigate while busy', async () => {
    const wrapper = mount(ChatApprovalInlineCard, {
      props: {
        card: {
          ...card,
          approval_request_ids: ['req-crud-2'],
          approval_path: '/mod/xcagi-approval-bridge/approval-hub/workspace?request_no=req-crud-2',
        },
        busy: true,
      },
    })

    await wrapper.find('.approval-btn--primary').trigger('click')
    expect(push).not.toHaveBeenCalled()
  })
})
