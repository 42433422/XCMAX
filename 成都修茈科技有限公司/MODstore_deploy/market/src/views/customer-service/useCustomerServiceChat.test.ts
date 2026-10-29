import { defineComponent, h, ref } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import type { RouteLocationNormalizedLoaded } from 'vue-router'
import { useCustomerServiceChat, type CustomerServiceChat } from './useCustomerServiceChat'
const chat = vi.hoisted(() => vi.fn())
vi.mock('../../api', () => ({ api: { customerServiceChat: chat } }))

describe('customer ticket submission acknowledgement', () => {
  it.each(['Internal Server Error', 'HTTP 503', 'Failed to fetch'])(
    'reads back after %s without retrying or claiming a receipt', async (failure) => {
      const loadTickets = vi.fn().mockResolvedValue(undefined)
      let state!: CustomerServiceChat
      const wrapper = mount(defineComponent({ setup() {
        state = useCustomerServiceChat({
          route: { query: {} } as RouteLocationNormalizedLoaded,
          pendingImageDataUrl: ref(null), imagePicking: ref(false),
          clearPendingImage: vi.fn(), loadTickets, expandedTicketIds: ref(new Set<number>()),
        })
        return () => h('div')
      } }))
      chat.mockReset().mockRejectedValue(new Error(failure))
      await state.sendText('提交工单')
      expect(chat).toHaveBeenCalledTimes(1)
      expect(loadTickets).toHaveBeenCalledTimes(2) // mount + read-only reconciliation
      expect(state.error.value).toContain('暂无法确认')
      expect(state.error.value).toContain('勿重复提交')
      expect(state.loading.value).toBe(false)
      expect(state.messages.value.map(message => message.role)).toEqual(['user'])
      wrapper.unmount()
    },
  )
})
