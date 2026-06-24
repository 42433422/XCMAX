import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'

const container = vi.hoisted(() => ({ mocks: {} as Record<string, unknown> }))

vi.mock('@/composables/useAiOpenCursor', async () => {
  const { ref } = await import('vue')
  const cursorX = ref(0)
  const cursorY = ref(0)
  const cursorVisible = ref(false)
  const cursorClicking = ref(false)
  const cursorActionLabel = ref('')
  const enabled = ref(false)
  const connected = ref(false)
  const initAiOpenCursor = vi.fn()
  container.mocks.cursorX = cursorX
  container.mocks.cursorY = cursorY
  container.mocks.cursorVisible = cursorVisible
  container.mocks.cursorClicking = cursorClicking
  container.mocks.cursorActionLabel = cursorActionLabel
  container.mocks.enabled = enabled
  container.mocks.connected = connected
  container.mocks.initAiOpenCursor = initAiOpenCursor
  return {
    cursorX,
    cursorY,
    cursorVisible,
    cursorClicking,
    cursorActionLabel,
    aiopenCursorEnabled: enabled,
    aiopenCursorConnected: connected,
    initAiOpenCursor,
  }
})

import VirtualCursorOverlay from './VirtualCursorOverlay.vue'

const cursorState = container.mocks as {
  cursorX: { value: number }
  cursorY: { value: number }
  cursorVisible: { value: boolean }
  cursorClicking: { value: boolean }
  cursorActionLabel: { value: string }
  enabled: { value: boolean }
  connected: { value: boolean }
  initAiOpenCursor: ReturnType<typeof vi.fn>
}

let wrappers: Array<{ unmount: () => void }> = []

function mountComponent() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', component: { template: '<div />' } }],
  })
  return router.push('/').then(() =>
    router.isReady().then(() => {
      const wrapper = mount(VirtualCursorOverlay, {
        global: { plugins: [router] },
        attachTo: document.body,
      })
      wrappers.push(wrapper)
      return wrapper
    }),
  )
}

describe('VirtualCursorOverlay', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    cursorState.cursorX.value = 0
    cursorState.cursorY.value = 0
    cursorState.cursorVisible.value = false
    cursorState.cursorClicking.value = false
    cursorState.cursorActionLabel.value = ''
    cursorState.enabled.value = false
    cursorState.connected.value = false
  })

  afterEach(() => {
    wrappers.forEach((w) => w.unmount())
    wrappers = []
    document.body.innerHTML = ''
  })

  it('initializes aiopen cursor with router on mount', async () => {
    await mountComponent()
    expect(cursorState.initAiOpenCursor).toHaveBeenCalled()
  })

  it('does not render cursor when cursorVisible is false', async () => {
    await mountComponent()
    expect(document.querySelector('.aiopen-cursor')).toBeNull()
  })

  it('renders cursor when cursorVisible is true', async () => {
    cursorState.cursorVisible.value = true
    await mountComponent()
    expect(document.querySelector('.aiopen-cursor')).not.toBeNull()
  })

  it('applies translate transform based on cursorX and cursorY', async () => {
    cursorState.cursorVisible.value = true
    cursorState.cursorX.value = 100
    cursorState.cursorY.value = 200
    await mountComponent()
    const cursor = document.querySelector('.aiopen-cursor') as HTMLElement
    expect(cursor.getAttribute('style')).toContain('translate(100px, 200px)')
  })

  it('applies clicking class when cursorClicking is true', async () => {
    cursorState.cursorVisible.value = true
    cursorState.cursorClicking.value = true
    await mountComponent()
    const cursor = document.querySelector('.aiopen-cursor') as HTMLElement
    expect(cursor.classList.contains('aiopen-cursor--clicking')).toBe(true)
  })

  it('does not apply clicking class when cursorClicking is false', async () => {
    cursorState.cursorVisible.value = true
    cursorState.cursorClicking.value = false
    await mountComponent()
    const cursor = document.querySelector('.aiopen-cursor') as HTMLElement
    expect(cursor.classList.contains('aiopen-cursor--clicking')).toBe(false)
  })

  it('renders action label when cursorActionLabel is set', async () => {
    cursorState.cursorVisible.value = true
    cursorState.cursorActionLabel.value = '点击'
    await mountComponent()
    const label = document.querySelector('.aiopen-cursor-label')
    expect(label).not.toBeNull()
    expect(label!.textContent).toContain('点击')
  })

  it('does not render action label when cursorActionLabel is empty', async () => {
    cursorState.cursorVisible.value = true
    cursorState.cursorActionLabel.value = ''
    await mountComponent()
    expect(document.querySelector('.aiopen-cursor-label')).toBeNull()
  })

  it('renders ripple when clicking', async () => {
    cursorState.cursorVisible.value = true
    cursorState.cursorClicking.value = true
    await mountComponent()
    expect(document.querySelector('.aiopen-cursor-ripple')).not.toBeNull()
  })

  it('does not render ripple when not clicking', async () => {
    cursorState.cursorVisible.value = true
    cursorState.cursorClicking.value = false
    await mountComponent()
    expect(document.querySelector('.aiopen-cursor-ripple')).toBeNull()
  })

  it('does not render control badge when enabled or connected is false', async () => {
    await mountComponent()
    expect(document.querySelector('.aiopen-control-badge')).toBeNull()
  })

  it('renders control badge when enabled and connected are true', async () => {
    cursorState.enabled.value = true
    cursorState.connected.value = true
    await mountComponent()
    const badge = document.querySelector('.aiopen-control-badge')
    expect(badge).not.toBeNull()
    expect(badge!.textContent).toContain('AI 操控通道已连接')
  })

  it('does not render control badge when only enabled is true', async () => {
    cursorState.enabled.value = true
    cursorState.connected.value = false
    await mountComponent()
    expect(document.querySelector('.aiopen-control-badge')).toBeNull()
  })

  it('renders cursor arrow svg inside cursor', async () => {
    cursorState.cursorVisible.value = true
    await mountComponent()
    expect(document.querySelector('.aiopen-cursor-arrow')).not.toBeNull()
  })

  it('cursor has aria-hidden=true', async () => {
    cursorState.cursorVisible.value = true
    await mountComponent()
    const cursor = document.querySelector('.aiopen-cursor') as HTMLElement
    expect(cursor.getAttribute('aria-hidden')).toBe('true')
  })
})
