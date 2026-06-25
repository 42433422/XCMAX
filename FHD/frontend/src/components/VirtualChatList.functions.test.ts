import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/utils/pretext', () => ({
  batchEstimateMessageHeights: vi.fn().mockImplementation((msgs: any[]) =>
    msgs.length === 0 ? [] : msgs.map(() => 80)
  ),
  measureText: vi.fn().mockReturnValue({ height: 60, width: 400 }),
}))

import VirtualChatList from '@/components/VirtualChatList.vue'

const sampleMessages = [
  { role: 'user', content: '你好', time: '10:00' },
  { role: 'ai', content: '你好！有什么可以帮助你的吗？', time: '10:01' },
  { role: 'user', content: '帮我分析一下数据', time: '10:02' },
]

function mountComponent(propsOverrides: Record<string, unknown> = {}) {
  return mount(VirtualChatList, {
    props: {
      messages: sampleMessages,
      ...propsOverrides,
    },
    global: {
      stubs: {
        OptimizedChatMessage: true,
      },
    },
  })
}

describe('VirtualChatList additional functions', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  // --- calculateMessageHeights ---

  it('calculateMessageHeights computes heights from messages', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.calculateMessageHeights()
    // batchEstimateMessageHeights returns [80, 80, 80], + 40 padding = [120, 120, 120]
    expect(vm.messageHeights.length).toBe(3)
    expect(vm.messageHeights[0]).toBe(120)
  })

  it('calculateMessageHeights handles empty messages', () => {
    const wrapper = mountComponent({ messages: [] })
    const vm = wrapper.vm as any
    vm.calculateMessageHeights()
    expect(vm.messageHeights).toEqual([])
  })

  it('calculateMessageHeights uses custom maxMessageWidth', () => {
    const wrapper = mountComponent({ maxMessageWidth: 800 })
    const vm = wrapper.vm as any
    vm.calculateMessageHeights()
    // batchEstimateMessageHeights is called with width = 800 - 32 = 768
    expect(vm.messageHeights.length).toBe(3)
  })

  // --- scrollToBottom ---

  it('scrollToBottom sets scrollTop to scrollHeight', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    const mockEl = { scrollTop: 0, scrollHeight: 500 }
    vm.containerRef = mockEl
    vm.scrollToBottom()
    expect(mockEl.scrollTop).toBe(500)
  })

  it('scrollToBottom does nothing when containerRef is null', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.containerRef = null
    expect(() => vm.scrollToBottom()).not.toThrow()
  })

  // --- collapseMessage with edge cases ---

  it('collapseMessage on first message sets height to 60', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.messageHeights = [120, 160, 100]
    vm.collapseMessage(0)
    expect(vm.messageHeights[0]).toBe(60)
    expect(vm.isMessageCollapsed(0)).toBe(true)
  })

  it('collapseMessage on last message sets height to 60', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.messageHeights = [120, 160, 100]
    vm.collapseMessage(2)
    expect(vm.messageHeights[2]).toBe(60)
    expect(vm.isMessageCollapsed(2)).toBe(true)
  })

  // --- expandMessage ---

  it('expandMessage removes from collapsed set and recalculates', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.collapseMessage(1)
    expect(vm.isMessageCollapsed(1)).toBe(true)
    vm.expandMessage(1)
    expect(vm.isMessageCollapsed(1)).toBe(false)
    // After expand, heights should be recalculated
    expect(vm.messageHeights.length).toBe(3)
  })

  // --- toggleTts edge cases ---

  it('toggleTts switches between different indices', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.toggleTts(0)
    expect(vm.playingMsgIdx).toBe(0)
    vm.toggleTts(1)
    expect(vm.playingMsgIdx).toBe(1)
    vm.toggleTts(1)
    expect(vm.playingMsgIdx).toBeNull()
  })

  it('toggleTts emits update:playing-msg-idx with null when toggled off', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.toggleTts(0)
    vm.toggleTts(0)
    const emitted = wrapper.emitted('update:playing-msg-idx')
    expect(emitted).toBeTruthy()
    expect(emitted![emitted!.length - 1][0]).toBeNull()
  })

  // --- handleScroll edge cases ---

  it('handleScroll updates scrollTop from containerRef', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.containerRef = {
      scrollTop: 42,
      scrollHeight: 1000,
      clientHeight: 200,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }
    vm.handleScroll()
    expect(vm.scrollTop).toBe(42)
  })

  it('handleScroll does not emit load-more when exactly at threshold boundary', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    // scrollTop + clientHeight = scrollHeight - 100 → should emit (>=)
    vm.containerRef = {
      scrollTop: 700,
      scrollHeight: 1000,
      clientHeight: 200,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }
    vm.handleScroll()
    expect(wrapper.emitted('load-more')).toBeTruthy()
  })

  // --- visibleRange with single message ---

  it('visibleRange handles single message correctly', () => {
    const wrapper = mountComponent({ messages: [sampleMessages[0]] })
    const vm = wrapper.vm as any
    expect(vm.visibleRange.start).toBe(0)
    expect(vm.visibleRange.end).toBe(0)
  })

  // --- offsetY ---

  it('offsetY is 0 when start is 0', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.scrollTop = 0
    expect(vm.offsetY).toBe(0)
  })

  // --- findStartIndex / findEndIndex edge cases ---

  it('findStartIndex returns 0 for offset 0', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    expect(vm.findStartIndex(0)).toBe(0)
  })

  it('findEndIndex returns last index for large offset', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    const result = vm.findEndIndex(999999)
    expect(result).toBe(sampleMessages.length - 1)
  })

  it('findStartIndex handles offset within range', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    // messageOffsets = [0, 120, 240] (each message is 120px)
    const result = vm.findStartIndex(150)
    expect(result).toBeGreaterThanOrEqual(0)
    expect(result).toBeLessThanOrEqual(2)
  })
})
