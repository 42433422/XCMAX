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

import OptimizedChatMessage from '@/components/OptimizedChatMessage.vue'

const baseMessage = {
  role: 'ai',
  content: '<p>Hello world</p>',
  time: '10:00',
}

function mountComponent(propsOverrides = {}) {
  return mount(OptimizedChatMessage, {
    props: {
      message: baseMessage,
      maxWidth: 600,
      ...propsOverrides,
    },
    global: {
      stubs: {
        ContextSummaryPills: true,
        CollapsedMessagePreview: true,
      },
    },
  })
}

describe('OptimizedChatMessage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders the message container', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.message').exists()).toBe(true)
  })

  it('applies role class to message', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.message.ai').exists()).toBe(true)
  })

  it('applies user role class for user messages', () => {
    const wrapper = mountComponent({ message: { ...baseMessage, role: 'user' } })
    expect(wrapper.find('.message.user').exists()).toBe(true)
  })

  it('shows skeleton before measurement completes', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.measureResult = null
    expect(wrapper.find('.message-skeleton').exists() || wrapper.find('.is-measuring').exists()).toBe(true)
  })

  it('shows message content after measurement', async () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.measureResult = { height: 60, width: 400 }
    vm.isCollapsed = false
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.message-html').exists()).toBe(true)
  })

  it('sanitizes HTML content', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    const result = vm.sanitizedContent
    expect(typeof result).toBe('string')
  })

  it('computes collapsedPreview from content', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    expect(typeof vm.collapsedPreview).toBe('string')
    expect(vm.collapsedPreview.length).toBeLessThanOrEqual(103) // 100 + '...'
  })

  it('computes messageStyle with minHeight when not measured', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.measureResult = null
    const style = vm.messageStyle
    expect(style).toHaveProperty('minHeight')
  })

  it('computes messageStyle with height when measured', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.measureResult = { height: 60, width: 400 }
    const style = vm.messageStyle
    expect(style).toHaveProperty('height')
  })

  it('collapse sets isCollapsed and emits collapse event', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.collapse()
    expect(vm.isCollapsed).toBe(true)
    expect(wrapper.emitted('collapse')).toBeTruthy()
  })

  it('expand sets isCollapsed to false and emits expand event', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.isCollapsed = true
    vm.expand()
    expect(vm.isCollapsed).toBe(false)
    expect(wrapper.emitted('expand')).toBeTruthy()
  })

  it('toggleTts emits toggle-tts event', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.toggleTts()
    expect(wrapper.emitted('toggle-tts')).toBeTruthy()
  })

  it('shows shipment download button for AI messages with download URL', async () => {
    const wrapper = mountComponent({
      message: { ...baseMessage, shipmentDownloadUrl: '/api/download/123' },
    })
    const vm = wrapper.vm as any
    vm.measureResult = { height: 60, width: 400 }
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.message-shipment-actions').exists()).toBe(true)
  })

  it('does not show shipment download for user messages', async () => {
    const wrapper = mountComponent({
      message: { ...baseMessage, role: 'user', shipmentDownloadUrl: '/api/download/123' },
    })
    const vm = wrapper.vm as any
    vm.measureResult = { height: 60, width: 400 }
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.message-shipment-actions').exists()).toBe(false)
  })

  it('shows collapse button for AI messages when canCollapse is true', async () => {
    const wrapper = mountComponent({ canCollapse: true })
    const vm = wrapper.vm as any
    vm.measureResult = { height: 60, width: 400 }
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.message-fold-action').exists()).toBe(true)
  })

  it('does not show collapse button when canCollapse is false', async () => {
    const wrapper = mountComponent({ canCollapse: false })
    const vm = wrapper.vm as any
    vm.measureResult = { height: 60, width: 400 }
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.message-fold-action').exists()).toBe(false)
  })

  it('shows TTS button for AI messages when canSpeak is true', async () => {
    const wrapper = mountComponent({ canSpeak: true })
    const vm = wrapper.vm as any
    vm.measureResult = { height: 60, width: 400 }
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.message-tts-btn').exists()).toBe(true)
  })

  it('shows thinking steps when present', async () => {
    const wrapper = mountComponent({
      message: { ...baseMessage, thinkingSteps: 'Step 1: Analyze\nStep 2: Plan' },
    })
    const vm = wrapper.vm as any
    vm.measureResult = { height: 60, width: 400 }
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.thinking-panel').exists()).toBe(true)
  })

  it('shows todo steps when present', async () => {
    const wrapper = mountComponent({
      message: { ...baseMessage, todoSteps: ['Step 1', 'Step 2'] },
    })
    const vm = wrapper.vm as any
    vm.measureResult = { height: 60, width: 400 }
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.todo-panel').exists()).toBe(true)
  })

  it('shows trace panel when workflowAction is present', async () => {
    const wrapper = mountComponent({
      message: { ...baseMessage, workflowAction: 'executing' },
    })
    const vm = wrapper.vm as any
    vm.measureResult = { height: 60, width: 400 }
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.trace-panel').exists()).toBe(true)
  })

  it('shows trace panel when nodeResults are present', async () => {
    const wrapper = mountComponent({
      message: { ...baseMessage, nodeResults: [{ node_id: 'n1', tool_id: 't1', action: 'run', success: true }] },
    })
    const vm = wrapper.vm as any
    vm.measureResult = { height: 60, width: 400 }
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.trace-panel').exists()).toBe(true)
  })

  it('shows time stamp', async () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.measureResult = { height: 60, width: 400 }
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.time').exists()).toBe(true)
    expect(wrapper.text()).toContain('10:00')
  })

  it('shows TTS playing state', async () => {
    const wrapper = mountComponent({ canSpeak: true, isPlaying: true })
    const vm = wrapper.vm as any
    vm.measureResult = { height: 60, width: 400 }
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.message-tts-btn.is-playing').exists()).toBe(true)
  })

  it('shows context summary when present', async () => {
    const wrapper = mountComponent({
      message: { ...baseMessage, contextSummary: { items: ['item1'] } },
    })
    const vm = wrapper.vm as any
    vm.measureResult = { height: 60, width: 400 }
    await wrapper.vm.$nextTick()
    expect(wrapper.findComponent({ name: 'ContextSummaryPills' }).exists()).toBe(true)
  })

  it('defaultCollapsed prop sets initial collapsed state', () => {
    const wrapper = mountComponent({ defaultCollapsed: true })
    const vm = wrapper.vm as any
    expect(vm.isCollapsed).toBe(true)
  })

  it('collapsedPreview truncates long content', () => {
    const longContent = '<p>' + 'A'.repeat(200) + '</p>'
    const wrapper = mountComponent({ message: { ...baseMessage, content: longContent } })
    const vm = wrapper.vm as any
    expect(vm.collapsedPreview.length).toBeLessThanOrEqual(103)
  })
})
