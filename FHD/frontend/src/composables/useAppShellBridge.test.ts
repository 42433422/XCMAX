import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  parseDesktopDeepLinkv2,
  navigateByDeepLink,
  useAppShellBridge,
} from './useAppShellBridge'
import { navigateFromSidebarKey } from '@/utils/sidebarNavigation'

vi.mock('@/utils/sidebarNavigation', () => ({
  navigateFromSidebarKey: vi.fn(async () => true),
}))

function makeRouter() {
  return { push: vi.fn() } as unknown as import('vue-router').Router
}

describe('useAppShellBridge', () => {
  beforeEach(() => {
    document.body.replaceChildren()
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

describe('parseDesktopDeepLinkv2', () => {
  it('解析 host 与查询参数', () => {
    const parsed = parseDesktopDeepLinkv2('xcagi://chat?q=%E4%BD%A0%E5%A5%BD&id=7')
    expect(parsed).not.toBeNull()
    expect(parsed!.host).toBe('chat')
    expect(parsed!.params.q).toBe('你好')
    expect(parsed!.params.id).toBe('7')
  })

  it('非深链 / 非法输入返回 null', () => {
    expect(parseDesktopDeepLinkv2('https://example.com/x')).toBeNull()
    expect(parseDesktopDeepLinkv2('')).toBeNull()
    expect(parseDesktopDeepLinkv2('xcagi:/bad-scheme')).toBeNull()
  })
})

describe('navigateByDeepLink', () => {
  const router = { push: vi.fn() } as unknown as import('vue-router').Router

  beforeEach(() => {
    vi.mocked(navigateFromSidebarKey).mockReset()
    vi.mocked(navigateFromSidebarKey).mockResolvedValue(true)
    document.body.replaceChildren()
  })

  it('chat 意图跳对话页并回填 q 参数', () => {
    const input = document.createElement('textarea')
    input.id = 'messageInput'
    document.body.appendChild(input)
    navigateByDeepLink(router, { raw: 'xcagi://chat?q=hi', host: 'chat', params: { q: 'hi' } })
    expect(navigateFromSidebarKey).toHaveBeenCalledWith(router, 'chat')
    expect(input.value).toBe('hi')
  })

  it('未知 host 回退对话页', async () => {
    vi.mocked(navigateFromSidebarKey).mockResolvedValueOnce(false)
    navigateByDeepLink(router, { raw: 'xcagi://nope', host: 'nope', params: {} })
    await vi.waitFor(() => expect(navigateFromSidebarKey).toHaveBeenCalledWith(router, 'chat'))
  })
})

describe('desktop and legacy event lifecycle', () => {
  type DesktopWindow = Window & { xcagiDesktop?: { onDeepLink?: (cb: (url: string) => void) => () => void;
    consumeDeepLink?: () => Promise<string | null>; onVoiceInvoke?: (cb: () => void) => () => void }; openImportWindow?: () => void }
  const desktop = window as DesktopWindow
  afterEach(() => { delete desktop.xcagiDesktop; delete desktop.openImportWindow; vi.useRealTimers(); vi.restoreAllMocks(); document.body.replaceChildren() })
  it('consumes a pending link, handles live links and voice, then releases both listeners', async () => {
    vi.useFakeTimers()
    let deepLink!: (url: string) => void, voice!: () => void
    const stopLink = vi.fn(), stopVoice = vi.fn(), router = makeRouter(), bridge = useAppShellBridge(router)
    const input = document.createElement('textarea'); input.id = 'messageInput'; document.body.append(input)
    const change = vi.fn(); input.addEventListener('input', change)
    desktop.xcagiDesktop = { consumeDeepLink: vi.fn().mockResolvedValue('xcagi://chat?q=pending'),
      onDeepLink: (cb) => { deepLink = cb; return stopLink }, onVoiceInvoke: (cb) => { voice = cb; return stopVoice } }
    bridge.installDesktopShellIntegrations()
    await Promise.resolve()
    expect(input.value).toBe('pending')
    deepLink(`xcagi://message?q=${'a'.repeat(600)}`)
    expect(input.value).toHaveLength(500)
    expect(change).toHaveBeenCalledTimes(2)
    deepLink('https://invalid.example'); input.blur(); voice(); await vi.runAllTimersAsync()
    expect(document.activeElement).toBe(input)
    expect(navigateFromSidebarKey).toHaveBeenCalledWith(router, 'chat')
    bridge.uninstall(); bridge.uninstall()
    expect(stopLink).toHaveBeenCalledOnce(); expect(stopVoice).toHaveBeenCalledOnce()
  })
  it.each([null, 'https://invalid.example'])('ignores a non-actionable pending desktop link %s', async (pending) => {
    vi.mocked(navigateFromSidebarKey).mockClear()
    desktop.xcagiDesktop = { consumeDeepLink: vi.fn().mockResolvedValue(pending) }
    const bridge = useAppShellBridge(makeRouter()); bridge.installDesktopShellIntegrations(); await Promise.resolve()
    expect(navigateFromSidebarKey).not.toHaveBeenCalled(); bridge.uninstall()
  })
  it('contains optional desktop registration and cleanup failures', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const fail = () => { throw new Error('shell unavailable') }
    desktop.xcagiDesktop = { onDeepLink: fail, onVoiceInvoke: fail }
    const bridge = useAppShellBridge(makeRouter()); bridge.installDesktopShellIntegrations()
    expect(warn).toHaveBeenCalledTimes(2)
    desktop.xcagiDesktop = { onDeepLink: () => fail }; bridge.installDesktopShellIntegrations()
    expect(() => bridge.uninstall()).not.toThrow()
    expect(parseDesktopDeepLinkv2('xcagi://[bad')).toBeNull()
  })
  it('limits sandbox navigation to typed requests and uninstalls event handlers', () => {
    const router = makeRouter(), bridge = useAppShellBridge(router), post = vi.spyOn(window.parent, 'postMessage').mockImplementation(() => {})
    bridge.installSandboxBridge(false); expect(post).not.toHaveBeenCalled()
    bridge.installSandboxBridge(true); expect(post).toHaveBeenCalledWith({ type: 'sandbox:ready' }, '*')
    for (const data of [{ type: 'other', path: '/ignored' }, { type: 'sandbox:navigate', path: 42 }, { type: 'sandbox:navigate', path: '/settings' }]) window.dispatchEvent(new MessageEvent('message', { data }))
    expect(router.push).toHaveBeenCalledExactlyOnceWith('/settings')
    bridge.uninstall(); window.dispatchEvent(new MessageEvent('message', { data: { type: 'sandbox:navigate', path: '/later' } }))
    expect(router.push).toHaveBeenCalledOnce()
  })
  it('binds upload entries once, handles absent and failing import hooks, and forwards the file picker click', () => {
    document.body.innerHTML = '<button id="fileUploadEntry"></button><button id="chooseFileBtn"></button><input id="fileInput" type="file">'
    const bridge = useAppShellBridge(makeRouter()), entry = document.getElementById('fileUploadEntry')!, picker = document.getElementById('fileInput')!
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {}), click = vi.spyOn(picker, 'click').mockImplementation(() => {})
    bridge.bindLegacyUploadHooks('settings'); expect(entry.hasAttribute('data-xcagi-bound')).toBe(false)
    bridge.bindLegacyUploadHooks(''); bridge.bindLegacyUploadHooks('chat')
    entry.click(); expect(warn).toHaveBeenCalledWith('[AppShellBridge] openImportWindow not found on window')
    desktop.openImportWindow = () => { throw new Error('import failed') }; entry.click()
    expect(warn).toHaveBeenCalledTimes(2)
    document.getElementById('chooseFileBtn')!.click(); expect(click).toHaveBeenCalledOnce()
    picker.remove(); expect(() => document.getElementById('chooseFileBtn')!.click()).not.toThrow()
    bridge.uninstall()
  })
})
