import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const applyLabelPrintBridge = vi.fn()
const applyReceiptBridge = vi.fn()
const applyWechatMsgBridge = vi.fn()
const applyWechatStarFeedPolledBridge = vi.fn()

vi.mock('@/stores/workflowEmployeeSpace', () => ({
  useWorkflowEmployeeSpaceStore: () => ({
    applyLabelPrintBridge,
    applyReceiptBridge,
    applyWechatMsgBridge,
    applyWechatStarFeedPolledBridge,
  }),
}))

import WorkflowEmployeeSpaceBridge from './WorkflowEmployeeSpaceBridge.vue'

describe('WorkflowEmployeeSpaceBridge', () => {
  let wrappers: Array<{ unmount: () => void }> = []

  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
    wrappers = []
  })

  afterEach(() => {
    wrappers.forEach((w) => w.unmount())
    wrappers = []
  })

  function mountComponent() {
    const wrapper = mount(WorkflowEmployeeSpaceBridge)
    wrappers.push(wrapper)
    return wrapper
  }

  it('mounts and renders hidden span', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('span[aria-hidden="true"]').exists()).toBe(true)
    expect(wrapper.find('span').attributes('style')).toContain('display: none')
  })

  it('listens for workflow-label-print-signal event', async () => {
    mountComponent()
    const detail = { labelId: 'L1' }
    window.dispatchEvent(new CustomEvent('xcagi:workflow-label-print-signal', { detail }))
    await new Promise((r) => setTimeout(r, 0))
    expect(applyLabelPrintBridge).toHaveBeenCalledWith(detail)
  })

  it('listens for workflow-receipt-feedback-signal event', async () => {
    mountComponent()
    const detail = { receiptId: 'R1' }
    window.dispatchEvent(new CustomEvent('xcagi:workflow-receipt-feedback-signal', { detail }))
    await new Promise((r) => setTimeout(r, 0))
    expect(applyReceiptBridge).toHaveBeenCalledWith(detail)
  })

  it('listens for wechat-ai-task-enqueue event', async () => {
    mountComponent()
    const detail = { taskId: 'T1' }
    window.dispatchEvent(new CustomEvent('xcagi:wechat-ai-task-enqueue', { detail }))
    await new Promise((r) => setTimeout(r, 0))
    expect(applyWechatMsgBridge).toHaveBeenCalledWith(detail)
  })

  it('listens for wechat-star-feed-polled event', async () => {
    mountComponent()
    const detail = { starId: 'S1' }
    window.dispatchEvent(new CustomEvent('xcagi:wechat-star-feed-polled', { detail }))
    await new Promise((r) => setTimeout(r, 0))
    expect(applyWechatStarFeedPolledBridge).toHaveBeenCalledWith(detail)
  })

  it('passes empty object when event has no detail', async () => {
    mountComponent()
    window.dispatchEvent(new CustomEvent('xcagi:workflow-label-print-signal'))
    await new Promise((r) => setTimeout(r, 0))
    expect(applyLabelPrintBridge).toHaveBeenCalledWith({})
  })

  it('removes event listeners on unmount', async () => {
    const wrapper = mountComponent()
    wrapper.unmount()
    applyLabelPrintBridge.mockClear()
    window.dispatchEvent(new CustomEvent('xcagi:workflow-label-print-signal', { detail: { x: 1 } }))
    await new Promise((r) => setTimeout(r, 0))
    expect(applyLabelPrintBridge).not.toHaveBeenCalled()
  })
})
