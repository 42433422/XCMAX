import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('dompurify', () => ({
  default: {
    sanitize: (html: string) => html.replace(/<script[^>]*>.*?<\/script>/gi, ''),
  },
}))
vi.mock('@/utils/pretext', () => ({
  measureText: vi.fn().mockReturnValue({ height: 60, width: 400 }),
}))
vi.mock('@/components/chat/ContextSummaryPills.vue', () => ({
  default: { name: 'ContextSummaryPills', template: '<div class="mock-pills" />' },
}))
vi.mock('@/components/chat/CollapsedMessagePreview.vue', () => ({
  default: {
    name: 'CollapsedMessagePreview',
    props: ['preview', 'expandLabel'],
    template: '<div class="mock-collapsed" @click="$emit(\'expand\')">{{ preview }}</div>',
    emits: ['expand'],
  },
}))
vi.mock('@/components/chat/MessageCollapseLink.vue', () => ({
  default: {
    name: 'MessageCollapseLink',
    props: ['label'],
    template: '<button class="mock-collapse-link" @click="$emit(\'collapse\')">{{ label }}</button>',
    emits: ['collapse'],
  },
}))

import OptimizedChatMessage from '@/components/OptimizedChatMessage.vue'

const baseMessage = {
  role: 'ai',
  content: '<p>Hello world</p>',
  time: '10:00',
}

function mountComponent(propsOverrides: Record<string, unknown> = {}) {
  return mount(OptimizedChatMessage, {
    props: {
      message: baseMessage,
      maxWidth: 600,
      ...propsOverrides,
    },
  })
}

describe('OptimizedChatMessage additional functions', () => {
  let originalRIC: any
  let originalCancelRIC: any

  beforeEach(() => {
    setActivePinia(createPinia())
    // jsdom reports 'requestIdleCallback' in window === true but it's not a function.
    // Install a working implementation that runs the callback synchronously.
    originalRIC = (window as any).requestIdleCallback
    originalCancelRIC = (window as any).cancelIdleCallback
    ;(window as any).requestIdleCallback = (cb: () => void) => {
      cb()
      return 0
    }
    ;(window as any).cancelIdleCallback = () => {}
  })

  afterEach(() => {
    ;(window as any).requestIdleCallback = originalRIC
    ;(window as any).cancelIdleCallback = originalCancelRIC
  })

  // --- contextSummaryText computed ---

  it('contextSummaryText returns empty string when contextSummary is null', () => {
    const wrapper = mountComponent({ message: { ...baseMessage, contextSummary: null } })
    const vm = wrapper.vm as any
    expect(vm.contextSummaryText).toBe('')
  })

  it('contextSummaryText returns empty string when contextSummary is undefined', () => {
    const wrapper = mountComponent({ message: { ...baseMessage } })
    const vm = wrapper.vm as any
    expect(vm.contextSummaryText).toBe('')
  })

  it('contextSummaryText returns trimmed string for string contextSummary', () => {
    const wrapper = mountComponent({ message: { ...baseMessage, contextSummary: '  hello world  ' } })
    const vm = wrapper.vm as any
    expect(vm.contextSummaryText).toBe('hello world')
  })

  it('contextSummaryText joins items array with + separator', () => {
    const wrapper = mountComponent({ message: { ...baseMessage, contextSummary: { items: ['item1', 'item2', 'item3'] } } })
    const vm = wrapper.vm as any
    expect(vm.contextSummaryText).toBe('item1 + item2 + item3')
  })

  it('contextSummaryText filters empty items from array', () => {
    const wrapper = mountComponent({ message: { ...baseMessage, contextSummary: { items: ['item1', '', '  ', 'item2'] } } })
    const vm = wrapper.vm as any
    expect(vm.contextSummaryText).toBe('item1 + item2')
  })

  it('contextSummaryText handles object without items', () => {
    const wrapper = mountComponent({ message: { ...baseMessage, contextSummary: { foo: 'bar' } } })
    const vm = wrapper.vm as any
    expect(vm.contextSummaryText).toBe('[object Object]')
  })

  it('contextSummaryText handles array contextSummary', () => {
    const wrapper = mountComponent({ message: { ...baseMessage, contextSummary: [1, 2, 3] } })
    const vm = wrapper.vm as any
    expect(vm.contextSummaryText).toBe('1,2,3')
  })

  it('contextSummaryText handles number contextSummary', () => {
    const wrapper = mountComponent({ message: { ...baseMessage, contextSummary: 42 } })
    const vm = wrapper.vm as any
    expect(vm.contextSummaryText).toBe('42')
  })

  // --- performMeasure ---

  it('performMeasure uses requestIdleCallback when available', async () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    // The component already calls performMeasure on mount via watch immediate
    // Verify measureResult is set after flush
    await wrapper.vm.$nextTick()
    // measureText mock returns { height: 60, width: 400 }
    expect(vm.measureResult).toBeTruthy()
  })

  it('performMeasure falls back to setTimeout when requestIdleCallback not available', async () => {
    // Remove requestIdleCallback for this test only
    const savedRIC = (window as any).requestIdleCallback
    delete (window as any).requestIdleCallback
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    await wrapper.vm.$nextTick()
    // Wait for setTimeout to fire
    await new Promise(resolve => setTimeout(resolve, 10))
    expect(vm.measureResult).toBeTruthy()
    // Restore working mock
    ;(window as any).requestIdleCallback = savedRIC
  })

  // --- collapsedPreview edge cases ---

  it('collapsedPreview returns full text when under 100 chars', () => {
    const wrapper = mountComponent({ message: { ...baseMessage, content: '<p>Short</p>' } })
    const vm = wrapper.vm as any
    expect(vm.collapsedPreview).toBe('Short')
  })

  it('collapsedPreview truncates with ellipsis when over 100 chars', () => {
    const longText = 'A'.repeat(150)
    const wrapper = mountComponent({ message: { ...baseMessage, content: `<p>${longText}</p>` } })
    const vm = wrapper.vm as any
    expect(vm.collapsedPreview).toContain('...')
    expect(vm.collapsedPreview.length).toBe(103) // 100 + '...'
  })

  it('collapsedPreview strips HTML tags', () => {
    const wrapper = mountComponent({ message: { ...baseMessage, content: '<div><span>Test</span></div>' } })
    const vm = wrapper.vm as any
    expect(vm.collapsedPreview).toBe('Test')
  })

  // --- messageStyle edge cases ---

  it('messageStyle returns minHeight 80px when not measured', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.measureResult = null
    expect(vm.messageStyle).toEqual({ minHeight: '80px' })
  })

  it('messageStyle returns height with 40px padding when measured', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.measureResult = { height: 100, width: 400 }
    expect(vm.messageStyle).toEqual({ height: '140px' })
  })

  // --- collapse / expand via UI ---

  it('collapse link click triggers collapse and emits event', async () => {
    const wrapper = mountComponent({ canCollapse: true })
    const vm = wrapper.vm as any
    vm.measureResult = { height: 60, width: 400 }
    await wrapper.vm.$nextTick()
    const collapseLink = wrapper.find('.message-fold-action')
    expect(collapseLink.exists()).toBe(true)
    await collapseLink.trigger('click')
    expect(vm.isCollapsed).toBe(true)
    expect(wrapper.emitted('collapse')).toBeTruthy()
  })

  it('expand via CollapsedMessagePreview triggers expand and emits event', async () => {
    const wrapper = mountComponent({ defaultCollapsed: true })
    const vm = wrapper.vm as any
    vm.measureResult = { height: 60, width: 400 }
    await wrapper.vm.$nextTick()
    const collapsedPreview = wrapper.find('.mock-collapsed')
    expect(collapsedPreview.exists()).toBe(true)
    await collapsedPreview.trigger('click')
    expect(vm.isCollapsed).toBe(false)
    expect(wrapper.emitted('expand')).toBeTruthy()
  })

  // --- toggleTts via UI ---

  it('TTS button click emits toggle-tts', async () => {
    const wrapper = mountComponent({ canSpeak: true })
    const vm = wrapper.vm as any
    vm.measureResult = { height: 60, width: 400 }
    await wrapper.vm.$nextTick()
    const ttsBtn = wrapper.find('.message-tts-btn')
    expect(ttsBtn.exists()).toBe(true)
    await ttsBtn.trigger('click')
    expect(wrapper.emitted('toggle-tts')).toBeTruthy()
  })

  // --- watch content change ---

  it('watch on content resets measureResult and re-measures', async () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.measureResult = { height: 60, width: 400 }
    await wrapper.setProps({ message: { ...baseMessage, content: '<p>New content</p>' } })
    // measureResult should be reset then re-measured
    await wrapper.vm.$nextTick()
    expect(vm.measureResult).toBeTruthy()
  })

  // --- trace panel rendering ---

  it('shows trace node with error and recovery hint', async () => {
    const wrapper = mountComponent({
      message: {
        ...baseMessage,
        nodeResults: [{
          node_id: 'n1',
          tool_id: 't1',
          action: 'run',
          success: false,
          error: 'Connection failed',
          recovery_hint: 'Check network',
          retries: 2,
          duration_ms: 150,
        }],
      },
    })
    const vm = wrapper.vm as any
    vm.measureResult = { height: 60, width: 400 }
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.trace-panel').exists()).toBe(true)
    expect(wrapper.find('.trace-status.fail').exists()).toBe(true)
    expect(wrapper.find('.trace-node-error').text()).toContain('Connection failed')
    expect(wrapper.find('.trace-node-hint').text()).toContain('Check network')
    expect(wrapper.find('.trace-node-meta').text()).toContain('重试 2 次')
    expect(wrapper.find('.trace-node-meta').text()).toContain('150ms')
  })

  it('shows trace node with success status', async () => {
    const wrapper = mountComponent({
      message: {
        ...baseMessage,
        nodeResults: [{
          node_id: 'n2',
          tool_id: 't2',
          action: 'execute',
          success: true,
        }],
      },
    })
    const vm = wrapper.vm as any
    vm.measureResult = { height: 60, width: 400 }
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.trace-status.ok').exists()).toBe(true)
  })
})
