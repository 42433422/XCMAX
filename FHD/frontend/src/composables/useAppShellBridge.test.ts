import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useAppShellBridge } from './useAppShellBridge'
import { navigateFromSidebarKey } from '@/utils/sidebarNavigation'

vi.mock('@/utils/sidebarNavigation', () => ({
  navigateFromSidebarKey: vi.fn(async () => true),
}))

function makeRouter() {
  return { push: vi.fn() } as unknown as import('vue-router').Router
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
    const bridge = useAppShellBridge(router)
    bridge.installSwitchViewBridge()
    window.dispatchEvent(new CustomEvent('xcagi:switch-view', { detail: { view: 'products' } }))
    expect(navigateFromSidebarKey).toHaveBeenCalledWith(router, 'products')
    bridge.uninstall()
  })

  it('bindLegacyUploadHooks wires fileUploadEntry when present', () => {
    const openImport = vi.fn()
    ;(window as Window & { openImportWindow?: () => void }).openImportWindow = openImport
    const entry = document.createElement('div')
    entry.id = 'fileUploadEntry'
    document.body.appendChild(entry)

    const bridge = useAppShellBridge(makeRouter())
    bridge.bindLegacyUploadHooks('chat')
    entry.click()
    expect(openImport).toHaveBeenCalled()
    bridge.uninstall()
  })
})
