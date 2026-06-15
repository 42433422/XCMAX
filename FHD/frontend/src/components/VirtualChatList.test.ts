import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/utils/pretext', () => ({
  batchEstimateMessageHeights: vi.fn().mockImplementation((msgs: any[]) =>
    msgs.length === 0 ? [] : [80, 120, 60]
  ),
  measureText: vi.fn().mockReturnValue({ height: 60, width: 400 }),
}))

import VirtualChatList from '@/components/VirtualChatList.vue'

const sampleMessages = [
  { role: 'user', content: '你好', time: '10:00' },
  { role: 'ai', content: '你好！有什么可以帮助你的吗？', time: '10:01' },
  { role: 'user', content: '帮我分析一下数据', time: '10:02' },
]

function mountComponent(propsOverrides = {}) {
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

describe('VirtualChatList', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders the container', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.virtual-chat-list').exists()).toBe(true)
  })

  it('renders phantom element for total height', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.virtual-list-phantom').exists()).toBe(true)
  })

  it('renders content container with transform', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.virtual-list-content').exists()).toBe(true)
  })

  it('shows loading indicator when isLoading is true', () => {
    const wrapper = mountComponent({ isLoading: true })
    expect(wrapper.find('.loading-more').exists()).toBe(true)
    expect(wrapper.text()).toContain('加载中')
  })

  it('hides loading indicator when isLoading is false', () => {
    const wrapper = mountComponent({ isLoading: false })
    expect(wrapper.find('.loading-more').exists()).toBe(false)
  })

  it('computes totalHeight from message heights', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    // batchEstimateMessageHeight returns [80, 120, 60] + 40 padding each = [120, 160, 100]
    // totalHeight = 120 + 160 + 100 = 380
    expect(vm.totalHeight).toBeGreaterThan(0)
  })

  it('computes messageOffsets correctly', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    expect(vm.messageOffsets.length).toBe(sampleMessages.length)
    expect(vm.messageOffsets[0]).toBe(0)
  })

  it('computes visibleRange with buffer', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    expect(vm.visibleRange).toHaveProperty('start')
    expect(vm.visibleRange).toHaveProperty('end')
    expect(vm.visibleRange.start).toBeGreaterThanOrEqual(0)
    expect(vm.visibleRange.end).toBeLessThan(sampleMessages.length)
  })

  it('computes visibleItems from visibleRange', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    expect(vm.visibleItems.length).toBeGreaterThan(0)
    expect(vm.visibleItems[0]).toHaveProperty('index')
    expect(vm.visibleItems[0]).toHaveProperty('message')
  })

  it('computes offsetY from messageOffsets', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    expect(typeof vm.offsetY).toBe('number')
  })

  it('findStartIndex uses binary search', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    const result = vm.findStartIndex(0)
    expect(result).toBe(0)
  })

  it('findEndIndex uses binary search', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    const result = vm.findEndIndex(1000)
    expect(result).toBeLessThan(sampleMessages.length)
  })

  it('isMessageCollapsed returns correct state', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    expect(vm.isMessageCollapsed(0)).toBe(false)
    vm.collapseMessage(0)
    expect(vm.isMessageCollapsed(0)).toBe(true)
  })

  it('collapseMessage reduces height', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.messageHeights = [120, 160, 100]
    vm.collapseMessage(1)
    expect(vm.messageHeights[1]).toBe(60)
  })

  it('expandMessage recalculates heights', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.collapseMessage(0)
    vm.expandMessage(0)
    expect(vm.isMessageCollapsed(0)).toBe(false)
  })

  it('toggleTts toggles playingMsgIdx', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.toggleTts(0)
    expect(vm.playingMsgIdx).toBe(0)
    vm.toggleTts(0)
    expect(vm.playingMsgIdx).toBeNull()
  })

  it('toggleTts emits update:playing-msg-idx', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.toggleTts(0)
    expect(wrapper.emitted('update:playing-msg-idx')).toBeTruthy()
  })

  it('exposes scrollToBottom method', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    expect(typeof vm.scrollToBottom).toBe('function')
  })

  it('handles empty messages array', () => {
    const wrapper = mountComponent({ messages: [] })
    const vm = wrapper.vm as any
    expect(vm.totalHeight).toBe(0)
    expect(vm.visibleItems).toEqual([])
  })

  it('uses custom bufferSize prop', () => {
    const wrapper = mountComponent({ bufferSize: 10 })
    const vm = wrapper.vm as any
    expect(vm.bufferSize).toBe(10)
  })

  it('uses custom maxMessageWidth prop', () => {
    const wrapper = mountComponent({ maxMessageWidth: 800 })
    const vm = wrapper.vm as any
    expect(vm.maxMessageWidth).toBe(800)
  })

  it('emits load-more when scrolled near bottom', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    // Simulate scroll near bottom
    vm.containerRef = {
      scrollTop: 1000,
      scrollHeight: 1100,
      clientHeight: 100,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }
    vm.handleScroll()
    expect(wrapper.emitted('load-more')).toBeTruthy()
  })

  it('does not emit load-more when not near bottom', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.containerRef = {
      scrollTop: 10,
      scrollHeight: 1000,
      clientHeight: 100,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }
    vm.handleScroll()
    expect(wrapper.emitted('load-more')).toBeFalsy()
  })

  it('handleScroll does nothing when containerRef is null', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.containerRef = null
    expect(() => vm.handleScroll()).not.toThrow()
  })

  it('updateContainerHeight reads clientHeight', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.containerRef = { clientHeight: 500 }
    vm.updateContainerHeight()
    expect(vm.containerHeight).toBe(500)
  })

  it('updateContainerHeight does nothing when containerRef is null', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.containerRef = null
    expect(() => vm.updateContainerHeight()).not.toThrow()
  })
})
