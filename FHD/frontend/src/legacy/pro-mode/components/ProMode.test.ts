import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { ref, nextTick } from 'vue'

const mockStepBack = vi.fn()

vi.mock('@/composables/useProMode', () => ({
  useProMode: () => ({
    stepBack: mockStepBack,
    currentStage: ref('idle'),
  }),
}))

import ProMode from '@/legacy/pro-mode/components/ProMode.vue'

function mountComponent(propsOverrides = {}) {
  return mount(ProMode, {
    props: {
      modelValue: false,
      ...propsOverrides,
    },
    global: {
      stubs: {
        Teleport: true,
      },
    },
  })
}

describe('ProMode (legacy)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.stubGlobal('localStorage', {
      getItem: vi.fn().mockReturnValue('修茈'),
      setItem: vi.fn(),
      removeItem: vi.fn(),
      clear: vi.fn(),
    })
  })

  it('renders the overlay container', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.pro-mode-overlay').exists()).toBe(true)
  })

  it('renders EXIT PRO MODE button', () => {
    const wrapper = mountComponent()
    const btns = wrapper.findAll('.pro-exit-btn')
    const exitBtn = btns.find(b => b.text().includes('EXIT PRO MODE'))
    expect(exitBtn).toBeTruthy()
  })

  it('renders 撤回 button', () => {
    const wrapper = mountComponent()
    const btns = wrapper.findAll('.pro-exit-btn')
    const stepBackBtn = btns.find(b => b.text().includes('撤回'))
    expect(stepBackBtn).toBeTruthy()
  })

  it('renders STARK INDUSTRIES title', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.pro-title').exists()).toBe(true)
    expect(wrapper.find('.pro-title').text()).toContain('STARK INDUSTRIES')
  })

  it('renders jarvis-container', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.jarvis-container').exists()).toBe(true)
  })

  it('renders pro-status section', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.pro-status').exists()).toBe(true)
  })

  it('renders jarvis-chat-panel', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.jarvis-chat-panel').exists()).toBe(true)
  })

  it('renders jarvis-voice-btn', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.jarvis-voice-btn').exists()).toBe(true)
  })

  it('renders tool-runtime-panel', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.tool-runtime-panel').exists()).toBe(true)
  })

  it('renders data-stream lines', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.data-stream').exists()).toBe(true)
    expect(wrapper.findAll('.stream-line').length).toBe(4)
  })

  it('renders scan-line', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.scan-line').exists()).toBe(true)
  })

  it('renders corner-flash elements', () => {
    const wrapper = mountComponent()
    expect(wrapper.findAll('.corner-flash').length).toBe(4)
  })

  it('renders corner-decoration elements', () => {
    const wrapper = mountComponent()
    expect(wrapper.findAll('.corner-decoration').length).toBe(4)
  })

  it('renders light-source elements', () => {
    const wrapper = mountComponent()
    expect(wrapper.findAll('.light-source').length).toBe(3)
  })

  it('renders glow-pulse-ring elements', () => {
    const wrapper = mountComponent()
    expect(wrapper.findAll('.glow-pulse-ring').length).toBe(3)
  })

  it('renders center-expand-box layers', () => {
    const wrapper = mountComponent()
    expect(wrapper.findAll('.center-expand-box').length).toBe(4)
  })

  it('renders particle-layer with data-particle elements', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.particle-layer').exists()).toBe(true)
    expect(wrapper.findAll('.data-particle').length).toBe(16)
  })

  it('renders wechat-messages-panel', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.wechat-messages-panel').exists()).toBe(true)
  })

  it('renders pro-order-float-panel', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.pro-order-float-panel').exists()).toBe(true)
  })

  it('shows assistant name in status', () => {
    const wrapper = mountComponent()
    const status = wrapper.find('.pro-status')
    expect(status.text()).toContain('SYSTEM ONLINE')
  })

  it('emits update:modelValue false when exit button clicked', async () => {
    const wrapper = mountComponent({ modelValue: true })
    await nextTick()
    const btns = wrapper.findAll('.pro-exit-btn')
    const exitBtn = btns.find(b => b.text().includes('EXIT PRO MODE'))
    await exitBtn!.trigger('click')
    expect(wrapper.emitted('update:modelValue')).toBeTruthy()
    expect(wrapper.emitted('update:modelValue')![0]).toEqual([false])
  })

  it('applies active class when modelValue is true', async () => {
    const wrapper = mountComponent({ modelValue: true })
    await nextTick()
    const overlay = wrapper.find('.pro-mode-overlay')
    expect(overlay.classes()).toContain('active')
  })

  it('does not apply active class when modelValue is false', () => {
    const wrapper = mountComponent({ modelValue: false })
    const overlay = wrapper.find('.pro-mode-overlay')
    expect(overlay.classes()).not.toContain('active')
  })
})
