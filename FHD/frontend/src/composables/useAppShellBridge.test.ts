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
    document.body.innerHTML = ''
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
