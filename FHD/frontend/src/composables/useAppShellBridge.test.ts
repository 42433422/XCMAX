import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useAppShellBridge } from './useAppShellBridge'

function makeRouter() {
  return { push: vi.fn() } as unknown as import('vue-router').Router
}

function makeProMode() {
  return {
    readProModeStateFromDom: vi.fn(() => false),
    isProMode: { value: false },
    hasLegacyProModeRuntime: vi.fn(() => false),
    resolveModProEntryPath: vi.fn(() => ''),
    enterModProMode: vi.fn(async () => {}),
    exitModProMode: vi.fn(async () => {}),
    syncProModeStateSoon: vi.fn(),
    handleToggleProMode: vi.fn(),
  }
}

describe('useAppShellBridge', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('installSwitchViewBridge navigates on xcagi:switch-view', () => {
    const router = makeRouter()
    const bridge = useAppShellBridge(router, makeProMode())
    bridge.installSwitchViewBridge()
    window.dispatchEvent(new CustomEvent('xcagi:switch-view', { detail: { view: 'products' } }))
    expect(router.push).toHaveBeenCalledWith({ name: 'products' })
    bridge.uninstall()
  })

  it('bindLegacyUploadHooks wires fileUploadEntry when present', () => {
    const openImport = vi.fn()
    ;(window as Window & { openImportWindow?: () => void }).openImportWindow = openImport
    const entry = document.createElement('div')
    entry.id = 'fileUploadEntry'
    document.body.appendChild(entry)

    const bridge = useAppShellBridge(makeRouter(), makeProMode())
    bridge.bindLegacyUploadHooks('chat')
    entry.click()
    expect(openImport).toHaveBeenCalled()
    bridge.uninstall()
  })

  it('setProModeEnabled delegates to enterModProMode when enabling', () => {
    const proMode = makeProMode()
    const bridge = useAppShellBridge(makeRouter(), proMode)
    bridge.installProModeBridge()
    const w = window as Window & { setProModeEnabled?: (enabled: boolean) => void }
    w.setProModeEnabled?.(true)
    expect(proMode.enterModProMode).toHaveBeenCalled()
    bridge.uninstall()
  })
})
