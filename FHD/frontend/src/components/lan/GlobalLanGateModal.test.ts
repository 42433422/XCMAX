import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { ref } from 'vue'

const modalVisible = ref(false)
const modalRedirect = ref<string | null>(null)
const dismissLanGateModal = vi.fn()
const openLanGateModal = vi.fn()
const refresh = vi.fn().mockResolvedValue(undefined)

vi.mock('@/composables/useLanGate', () => ({
  useLanGate: () => ({
    modalVisible,
    modalRedirect,
    dismissLanGateModal,
    openLanGateModal,
    refresh,
  }),
}))

vi.mock('@/api/core', () => ({
  XCAGI_PROMPT_LAN_GATE_EVENT: 'xcagi:prompt-lan-gate',
}))

vi.mock('@/components/lan/LanGatePanel.vue', () => ({
  default: {
    name: 'LanGatePanel',
    template: '<div class="lan-gate-panel-stub" />',
  },
}))

import GlobalLanGateModal from './GlobalLanGateModal.vue'

function queryOverlay(): Element | null {
  return document.querySelector('.global-lan-gate-overlay')
}
function queryBackdrop(): Element | null {
  return document.querySelector('.global-lan-gate-backdrop')
}
function queryShell(): Element | null {
  return document.querySelector('.global-lan-gate-shell')
}
function queryPanelStub(): Element | null {
  return document.querySelector('.lan-gate-panel-stub')
}

describe('GlobalLanGateModal', () => {
  let wrappers: Array<{ unmount: () => void }> = []

  beforeEach(() => {
    vi.clearAllMocks()
    modalVisible.value = false
    modalRedirect.value = null
    refresh.mockResolvedValue(undefined)
    wrappers = []
  })

  afterEach(() => {
    wrappers.forEach((w) => w.unmount())
    wrappers = []
    document.body.innerHTML = ''
  })

  function mountComponent() {
    const wrapper = mount(GlobalLanGateModal, { attachTo: document.body })
    wrappers.push(wrapper)
    return wrapper
  }

  it('does not render overlay when modalVisible is false', () => {
    mountComponent()
    expect(queryOverlay()).toBeNull()
  })

  it('renders overlay when modalVisible is true', () => {
    modalVisible.value = true
    mountComponent()
    expect(queryOverlay()).not.toBeNull()
  })

  it('renders LanGatePanel inside shell when visible', () => {
    modalVisible.value = true
    mountComponent()
    expect(queryPanelStub()).not.toBeNull()
  })

  it('passes redirectPath to LanGatePanel', () => {
    modalVisible.value = true
    modalRedirect.value = '/custom-path'
    mountComponent()
    expect(queryShell()).not.toBeNull()
  })

  it('uses "/" as default redirectPath when modalRedirect is null', () => {
    modalVisible.value = true
    modalRedirect.value = null
    mountComponent()
    expect(queryShell()).not.toBeNull()
  })

  it('dismisses modal when backdrop is clicked', async () => {
    modalVisible.value = true
    mountComponent()
    const backdrop = queryBackdrop() as HTMLElement
    backdrop.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(dismissLanGateModal).toHaveBeenCalled()
  })

  it('does not dismiss when shell is clicked', async () => {
    modalVisible.value = true
    mountComponent()
    const shell = queryShell() as HTMLElement
    shell.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(dismissLanGateModal).not.toHaveBeenCalled()
  })

  it('has dialog role and aria-modal=true when visible', () => {
    modalVisible.value = true
    mountComponent()
    const overlay = queryOverlay() as HTMLElement
    expect(overlay.getAttribute('role')).toBe('dialog')
    expect(overlay.getAttribute('aria-modal')).toBe('true')
  })

  it('calls refresh and opens modal on lan gate prompt event', async () => {
    mountComponent()
    window.dispatchEvent(new CustomEvent('xcagi:prompt-lan-gate'))
    await flushPromises()
    expect(refresh).toHaveBeenCalledWith(true)
    expect(openLanGateModal).toHaveBeenCalled()
  })

  it('does not open modal if already visible on prompt event', async () => {
    modalVisible.value = true
    mountComponent()
    openLanGateModal.mockClear()
    window.dispatchEvent(new CustomEvent('xcagi:prompt-lan-gate'))
    await flushPromises()
    expect(openLanGateModal).not.toHaveBeenCalled()
  })

  it('removes event listener on unmount', async () => {
    const wrapper = mountComponent()
    wrapper.unmount()
    refresh.mockClear()
    openLanGateModal.mockClear()
    window.dispatchEvent(new CustomEvent('xcagi:prompt-lan-gate'))
    await flushPromises()
    expect(refresh).not.toHaveBeenCalled()
  })

  it('handles refresh rejection gracefully on prompt event', async () => {
    refresh.mockRejectedValueOnce(new Error('refresh failed'))
    mountComponent()
    window.dispatchEvent(new CustomEvent('xcagi:prompt-lan-gate'))
    await flushPromises()
    expect(openLanGateModal).toHaveBeenCalled()
  })
})
