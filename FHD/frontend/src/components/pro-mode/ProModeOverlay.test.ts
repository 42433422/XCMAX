import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { ref } from 'vue'

const mockExitProMode = vi.fn()
const mockExitMonitorMode = vi.fn()
const mockEnterMonitorMode = vi.fn()
const mockResetTransientState = vi.fn()

vi.mock('@/composables/useProMode', () => ({
  useProMode: () => ({
    isActive: ref(true),
    isTransitioning: ref(false),
    isWorkMode: ref(false),
    isMonitorMode: ref(false),
    currentStage: ref('idle'),
    selectedCompany: ref(null),
    selectedProduct: ref(null),
    coreScale: ref(1),
    orbitLayerScale: ref(1),
    exitProMode: mockExitProMode,
    exitMonitorMode: mockExitMonitorMode,
    enterMonitorMode: mockEnterMonitorMode,
    resetTransientState: mockResetTransientState,
  }),
}))

const mockSendMessage = vi.fn()
const mockAddMessage = vi.fn()
const mockClearMessages = vi.fn()

vi.mock('@/composables/useJarvisChat', () => ({
  useJarvisChat: () => ({
    messages: ref([]),
    isRecording: ref(false),
    isCoreSpeaking: ref(false),
    statusText: ref('READY'),
    sendMessage: mockSendMessage,
    addMessage: mockAddMessage,
    clearMessages: mockClearMessages,
  }),
}))

import ProModeOverlay from '@/components/pro-mode/ProModeOverlay.vue'

function mountComponent() {
  return mount(ProModeOverlay, {
    global: {
      stubs: {
        FallingTextContainer: true,
        StarkGrid: true,
        JarvisCore: true,
        WireRings: true,
        EnergyParticles: true,
        JarvisVoiceButton: true,
        JarvisChatPanel: true,
        JarvisStatus: true,
        ProProductOrbitLayer: true,
        CodeRings: true,
        IconRingContainer: true,
        ToolRuntimePanel: true,
        WorkModeMonitor: true,
        MonitorModePanel: true,
        ProFeatureWidget: true,
      },
    },
  })
}

describe('ProModeOverlay', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('renders the overlay container', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.pro-mode-overlay').exists()).toBe(true)
  })

  it('applies active class when isActive is true', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.pro-mode-overlay').classes()).toContain('active')
  })

  it('renders corner-flash elements', () => {
    const wrapper = mountComponent()
    expect(wrapper.findAll('.corner-flash').length).toBe(4)
  })

  it('renders center-expansion-box', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.center-expansion-box').exists()).toBe(true)
  })

  it('renders halo-pulse-ring elements', () => {
    const wrapper = mountComponent()
    expect(wrapper.findAll('.halo-pulse-ring').length).toBe(3)
  })

  it('renders jarvis-container', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.jarvis-container').exists()).toBe(true)
  })

  it('renders JarvisCore stub inside jarvis-container', () => {
    const wrapper = mountComponent()
    expect(wrapper.findComponent({ name: 'JarvisCore' }).exists()).toBe(true)
  })

  it('renders WireRings stub', () => {
    const wrapper = mountComponent()
    expect(wrapper.findComponent({ name: 'WireRings' }).exists()).toBe(true)
  })

  it('renders EnergyParticles stub', () => {
    const wrapper = mountComponent()
    expect(wrapper.findComponent({ name: 'EnergyParticles' }).exists()).toBe(true)
  })

  it('renders JarvisVoiceButton stub', () => {
    const wrapper = mountComponent()
    expect(wrapper.findComponent({ name: 'JarvisVoiceButton' }).exists()).toBe(true)
  })

  it('renders JarvisChatPanel stub', () => {
    const wrapper = mountComponent()
    expect(wrapper.findComponent({ name: 'JarvisChatPanel' }).exists()).toBe(true)
  })

  it('renders JarvisStatus stub', () => {
    const wrapper = mountComponent()
    expect(wrapper.findComponent({ name: 'JarvisStatus' }).exists()).toBe(true)
  })

  it('renders exit button with correct text', () => {
    const wrapper = mountComponent()
    const btn = wrapper.find('.pro-exit-button')
    expect(btn.exists()).toBe(true)
    expect(btn.text()).toContain('退出专业模式')
  })

  it('calls exitProMode and clearMessages when exit button clicked', async () => {
    const wrapper = mountComponent()
    await wrapper.find('.pro-exit-button').trigger('click')
    expect(mockExitProMode).toHaveBeenCalled()
    expect(mockClearMessages).toHaveBeenCalled()
  })

  it('renders CodeRings when currentStage is idle', () => {
    const wrapper = mountComponent()
    expect(wrapper.findComponent({ name: 'CodeRings' }).exists()).toBe(true)
  })

  it('renders IconRingContainer when currentStage is idle', () => {
    const wrapper = mountComponent()
    expect(wrapper.findComponent({ name: 'IconRingContainer' }).exists()).toBe(true)
  })

  it('does not render ToolRuntimePanel when runningTool is null', () => {
    const wrapper = mountComponent()
    expect(wrapper.findComponent({ name: 'ToolRuntimePanel' }).exists()).toBe(false)
  })

  it('does not render WorkModeMonitor when isWorkMode is false', () => {
    const wrapper = mountComponent()
    expect(wrapper.findComponent({ name: 'WorkModeMonitor' }).exists()).toBe(false)
  })

  it('does not render MonitorModePanel when isMonitorMode is false', () => {
    const wrapper = mountComponent()
    expect(wrapper.findComponent({ name: 'MonitorModePanel' }).exists()).toBe(false)
  })

  it('does not render ProFeatureWidget when showFeatureWidget is false', () => {
    const wrapper = mountComponent()
    expect(wrapper.findComponent({ name: 'ProFeatureWidget' }).exists()).toBe(false)
  })

  it('renders FallingTextContainer', () => {
    const wrapper = mountComponent()
    expect(wrapper.findComponent({ name: 'FallingTextContainer' }).exists()).toBe(true)
  })

  it('renders StarkGrid', () => {
    const wrapper = mountComponent()
    expect(wrapper.findComponent({ name: 'StarkGrid' }).exists()).toBe(true)
  })

  it('does not render ProProductOrbitLayer when currentStage is idle', () => {
    const wrapper = mountComponent()
    expect(wrapper.findComponent({ name: 'ProProductOrbitLayer' }).exists()).toBe(false)
  })
})
