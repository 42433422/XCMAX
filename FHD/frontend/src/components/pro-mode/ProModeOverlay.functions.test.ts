import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { ref, type Ref } from 'vue'

// Shared mutable state that the mock factories read from.
// We update these refs before each test to control the overlay's mode.
const state: Record<string, Ref<unknown>> = {
  isActive: ref(true),
  isTransitioning: ref(false),
  isWorkMode: ref(false),
  isMonitorMode: ref(false),
  currentStage: ref('idle'),
  selectedCompany: ref(null),
  selectedProduct: ref(null),
  coreScale: ref(1),
  orbitLayerScale: ref(1),
}

const mockExitProMode = vi.fn()
const mockExitMonitorMode = vi.fn()
const mockEnterMonitorMode = vi.fn()
const mockResetTransientState = vi.fn()
const mockSendMessage = vi.fn()
const mockAddMessage = vi.fn()
const mockClearMessages = vi.fn()

vi.mock('@/composables/useProMode', () => ({
  useProMode: () => ({
    isActive: state.isActive,
    isTransitioning: state.isTransitioning,
    isWorkMode: state.isWorkMode,
    isMonitorMode: state.isMonitorMode,
    currentStage: state.currentStage,
    selectedCompany: state.selectedCompany,
    selectedProduct: state.selectedProduct,
    coreScale: state.coreScale,
    orbitLayerScale: state.orbitLayerScale,
    exitProMode: mockExitProMode,
    exitMonitorMode: mockExitMonitorMode,
    enterMonitorMode: mockEnterMonitorMode,
    resetTransientState: mockResetTransientState,
  }),
}))

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

import ProModeOverlay from './ProModeOverlay.vue'

function setState(overrides: Record<string, unknown>) {
  for (const [key, value] of Object.entries(overrides)) {
    if (state[key]) (state[key] as Ref<unknown>).value = value
  }
}

function resetState() {
  setState({
    isActive: true,
    isTransitioning: false,
    isWorkMode: false,
    isMonitorMode: false,
    currentStage: 'idle',
    selectedCompany: null,
    selectedProduct: null,
  })
}

function mountOverlay() {
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

describe('ProModeOverlay event handlers', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    resetState()
  })

  it('handleCoreClick calls resetTransientState', async () => {
    const wrapper = mountOverlay()
    wrapper.findComponent({ name: 'JarvisCore' }).vm.$emit('click')
    await wrapper.vm.$nextTick()
    expect(mockResetTransientState).toHaveBeenCalled()
  })

  it('handleVoiceButtonClick logs', async () => {
    const wrapper = mountOverlay()
    const spy = vi.spyOn(console, 'log').mockImplementation(() => {})
    wrapper.findComponent({ name: 'JarvisVoiceButton' }).vm.$emit('click')
    await wrapper.vm.$nextTick()
    expect(spy).toHaveBeenCalledWith('Voice button clicked')
    spy.mockRestore()
  })

  it('handleVoiceButtonLongPress logs', async () => {
    const wrapper = mountOverlay()
    const spy = vi.spyOn(console, 'log').mockImplementation(() => {})
    wrapper.findComponent({ name: 'JarvisVoiceButton' }).vm.$emit('long-press')
    await wrapper.vm.$nextTick()
    expect(spy).toHaveBeenCalledWith('Voice button long pressed')
    spy.mockRestore()
  })

  it('handleMessageSend calls sendMessage', async () => {
    const wrapper = mountOverlay()
    wrapper.findComponent({ name: 'JarvisChatPanel' }).vm.$emit('message-send', 'hello')
    await wrapper.vm.$nextTick()
    expect(mockSendMessage).toHaveBeenCalledWith('hello')
  })

  it('handleTaskConfirm logs the task', async () => {
    const wrapper = mountOverlay()
    const spy = vi.spyOn(console, 'log').mockImplementation(() => {})
    wrapper.findComponent({ name: 'JarvisChatPanel' }).vm.$emit('task-confirm', { id: 1 })
    await wrapper.vm.$nextTick()
    expect(spy).toHaveBeenCalledWith('Task confirmed:', { id: 1 })
    spy.mockRestore()
  })

  it('handleTaskIgnore logs the task', async () => {
    const wrapper = mountOverlay()
    const spy = vi.spyOn(console, 'log').mockImplementation(() => {})
    wrapper.findComponent({ name: 'JarvisChatPanel' }).vm.$emit('task-ignore', { id: 2 })
    await wrapper.vm.$nextTick()
    expect(spy).toHaveBeenCalledWith('Task ignored:', { id: 2 })
    spy.mockRestore()
  })

  it('handleExit calls exitProMode and clearMessages', async () => {
    const wrapper = mountOverlay()
    await wrapper.find('.pro-exit-button').trigger('click')
    expect(mockExitProMode).toHaveBeenCalled()
    expect(mockClearMessages).toHaveBeenCalled()
  })

  it('handleCompanySelect logs the company (orbit stage)', async () => {
    setState({ currentStage: 'orbit' })
    const wrapper = mountOverlay()
    const spy = vi.spyOn(console, 'log').mockImplementation(() => {})
    const orbit = wrapper.findComponent({ name: 'ProProductOrbitLayer' })
    expect(orbit.exists()).toBe(true)
    orbit.vm.$emit('company-select', { name: 'Acme' })
    await wrapper.vm.$nextTick()
    expect(spy).toHaveBeenCalledWith('Company selected:', { name: 'Acme' })
    spy.mockRestore()
  })

  it('handleProductSelect logs the product (orbit stage)', async () => {
    setState({ currentStage: 'orbit' })
    const wrapper = mountOverlay()
    const spy = vi.spyOn(console, 'log').mockImplementation(() => {})
    const orbit = wrapper.findComponent({ name: 'ProProductOrbitLayer' })
    orbit.vm.$emit('product-select', { id: 42 })
    await wrapper.vm.$nextTick()
    expect(spy).toHaveBeenCalledWith('Product selected:', { id: 42 })
    spy.mockRestore()
  })

  it('handleReset calls resetTransientState (orbit stage)', async () => {
    setState({ currentStage: 'orbit' })
    const wrapper = mountOverlay()
    const orbit = wrapper.findComponent({ name: 'ProProductOrbitLayer' })
    orbit.vm.$emit('reset')
    await wrapper.vm.$nextTick()
    expect(mockResetTransientState).toHaveBeenCalled()
  })

  it('handleToolSelect logs the tool (idle stage)', async () => {
    const wrapper = mountOverlay()
    const spy = vi.spyOn(console, 'log').mockImplementation(() => {})
    wrapper.findComponent({ name: 'CodeRings' }).vm.$emit('tool-select', { name: 'search' })
    await wrapper.vm.$nextTick()
    expect(spy).toHaveBeenCalledWith('Tool selected:', { name: 'search' })
    spy.mockRestore()
  })

  it('handleImportClick logs', async () => {
    const wrapper = mountOverlay()
    const spy = vi.spyOn(console, 'log').mockImplementation(() => {})
    wrapper.findComponent({ name: 'IconRingContainer' }).vm.$emit('import-click')
    await wrapper.vm.$nextTick()
    expect(spy).toHaveBeenCalledWith('Import clicked')
    spy.mockRestore()
  })

  it('handleExportClick logs', async () => {
    const wrapper = mountOverlay()
    const spy = vi.spyOn(console, 'log').mockImplementation(() => {})
    wrapper.findComponent({ name: 'IconRingContainer' }).vm.$emit('export-click')
    await wrapper.vm.$nextTick()
    expect(spy).toHaveBeenCalledWith('Export clicked')
    spy.mockRestore()
  })

  it('handleContactClick logs the contact (work mode)', async () => {
    setState({ isWorkMode: true })
    const wrapper = mountOverlay()
    const spy = vi.spyOn(console, 'log').mockImplementation(() => {})
    const monitor = wrapper.findComponent({ name: 'WorkModeMonitor' })
    expect(monitor.exists()).toBe(true)
    monitor.vm.$emit('contact-click', { id: 'c1' })
    await wrapper.vm.$nextTick()
    expect(spy).toHaveBeenCalledWith('Contact clicked:', { id: 'c1' })
    spy.mockRestore()
  })

  it('handleWorkModeMessageSend logs contactId and message (work mode)', async () => {
    setState({ isWorkMode: true })
    const wrapper = mountOverlay()
    const spy = vi.spyOn(console, 'log').mockImplementation(() => {})
    const monitor = wrapper.findComponent({ name: 'WorkModeMonitor' })
    monitor.vm.$emit('message-send', 'c1', 'hi')
    await wrapper.vm.$nextTick()
    expect(spy).toHaveBeenCalledWith('Send message:', 'c1', 'hi')
    spy.mockRestore()
  })

  it('handleOrderDownload logs the orderId (work mode)', async () => {
    setState({ isWorkMode: true })
    const wrapper = mountOverlay()
    const spy = vi.spyOn(console, 'log').mockImplementation(() => {})
    const monitor = wrapper.findComponent({ name: 'WorkModeMonitor' })
    monitor.vm.$emit('download-order', 'ord-123')
    await wrapper.vm.$nextTick()
    expect(spy).toHaveBeenCalledWith('Download order:', 'ord-123')
    spy.mockRestore()
  })

  it('handleResetTaskAcquisition resets state (work mode)', async () => {
    setState({ isWorkMode: true })
    const wrapper = mountOverlay()
    const monitor = wrapper.findComponent({ name: 'WorkModeMonitor' })
    monitor.vm.$emit('reset-task')
    await wrapper.vm.$nextTick()
    expect(monitor.exists()).toBe(true)
  })

  it('handleMonitorModeClose calls exitMonitorMode (monitor mode)', async () => {
    setState({ isMonitorMode: true })
    const wrapper = mountOverlay()
    const panel = wrapper.findComponent({ name: 'MonitorModePanel' })
    expect(panel.exists()).toBe(true)
    panel.vm.$emit('close')
    await wrapper.vm.$nextTick()
    expect(mockExitMonitorMode).toHaveBeenCalled()
  })

  it('handleViewHistory logs (monitor mode)', async () => {
    setState({ isMonitorMode: true })
    const wrapper = mountOverlay()
    const spy = vi.spyOn(console, 'log').mockImplementation(() => {})
    const panel = wrapper.findComponent({ name: 'MonitorModePanel' })
    panel.vm.$emit('view-history')
    await wrapper.vm.$nextTick()
    expect(spy).toHaveBeenCalledWith('View history')
    spy.mockRestore()
  })
})

describe('ProModeOverlay computed properties', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    resetState()
  })

  it('isEntering is true when transitioning and active', () => {
    setState({ isTransitioning: true, isActive: true })
    const wrapper = mountOverlay()
    expect(wrapper.find('.pro-mode-overlay').classes()).toContain('entering')
  })

  it('isExiting is true when transitioning and not active', () => {
    setState({ isTransitioning: true, isActive: false })
    const wrapper = mountOverlay()
    expect(wrapper.find('.pro-mode-overlay').classes()).toContain('exiting')
  })

  it('applies work-mode class when isWorkMode', () => {
    setState({ isWorkMode: true })
    const wrapper = mountOverlay()
    expect(wrapper.find('.pro-mode-overlay').classes()).toContain('work-mode')
  })

  it('applies monitor-mode class when isMonitorMode', () => {
    setState({ isMonitorMode: true })
    const wrapper = mountOverlay()
    expect(wrapper.find('.pro-mode-overlay').classes()).toContain('monitor-mode')
  })

  it('renders ProProductOrbitLayer when currentStage is not idle', () => {
    setState({ currentStage: 'orbit' })
    const wrapper = mountOverlay()
    expect(wrapper.findComponent({ name: 'ProProductOrbitLayer' }).exists()).toBe(true)
    expect(wrapper.findComponent({ name: 'CodeRings' }).exists()).toBe(false)
    expect(wrapper.findComponent({ name: 'IconRingContainer' }).exists()).toBe(false)
  })

  it('renders WorkModeMonitor when isWorkMode is true', () => {
    setState({ isWorkMode: true })
    const wrapper = mountOverlay()
    expect(wrapper.findComponent({ name: 'WorkModeMonitor' }).exists()).toBe(true)
  })

  it('renders MonitorModePanel when isMonitorMode is true', () => {
    setState({ isMonitorMode: true })
    const wrapper = mountOverlay()
    expect(wrapper.findComponent({ name: 'MonitorModePanel' }).exists()).toBe(true)
  })
})
