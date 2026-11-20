import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import DesktopAssistantView from './DesktopAssistantView.vue'

const { profile, desktop, durable, resolveIdentity, resetPanel } = vi.hoisted(() => ({
  profile: {
    refreshFromServer: vi.fn(), clear: vi.fn(), workspaceReady: true,
    sessionCheckUnavailable: false, isAdminAccount: false, userRole: '',
  },
  desktop: { openMain: vi.fn(), onShow: vi.fn() },
  durable: vi.fn(), resolveIdentity: vi.fn(), resetPanel: vi.fn(),
}))
vi.mock('@/stores/accountProfile', () => ({ useAccountProfileStore: () => profile }))
vi.mock('@/utils/authSessionCache', () => ({ LS_ENTERPRISE_SESSION_HINT: 'session-hint' }))
vi.mock('@/utils/chatSessionRestore', () => ({ isDurableChatScope: durable }))
vi.mock('@/utils/chatStorageKeys', () => ({
  resolveChatStorageScope: () => 'owner-1', resolveChatIdentity: resolveIdentity,
}))
vi.mock('@/components/FloatingChatAssistant.vue', async () => {
  const { defineComponent, h } = await import('vue')
  return { default: defineComponent({
    setup(_, { expose }) {
      expose({ resetDesktopPanel: resetPanel })
      return () => h('div', { 'data-test': 'chat-panel' }, '私人聊天')
    },
  }) }
})

let wrapper: VueWrapper | undefined
let show: () => void
let stopWatching: ReturnType<typeof vi.fn>
const originalDesktop = window.xcagiDesktopAssistant
function view() { return wrapper = mount(DesktopAssistantView) }
function storage(key: string | null, area = localStorage, newValue: string | null = null) {
  window.dispatchEvent(new StorageEvent('storage', { key, storageArea: area, newValue }))
}
beforeEach(() => {
  vi.resetAllMocks()
  Object.assign(profile, { workspaceReady: true, sessionCheckUnavailable: false, isAdminAccount: false, userRole: '' })
  profile.refreshFromServer.mockResolvedValue(undefined)
  desktop.openMain.mockResolvedValue(undefined)
  stopWatching = vi.fn()
  desktop.onShow.mockImplementation(callback => { show = callback; return stopWatching })
  durable.mockReturnValue(true)
  resolveIdentity.mockReturnValue('account-1')
  window.xcagiDesktopAssistant = desktop as unknown as Window['xcagiDesktopAssistant']
})
afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  window.xcagiDesktopAssistant = originalDesktop
})

describe('desktop assistant session boundary', () => {
  it('rechecks the session on show and resets the visible panel before changing identity', async () => {
    const page = view()
    expect(page.get('button').attributes('disabled')).toBeDefined()
    await flushPromises()
    expect(profile.refreshFromServer).toHaveBeenCalledWith({ keepVisible: true })
    const firstPanel = page.get('[data-test="chat-panel"]').element
    resolveIdentity.mockReturnValue('account-2')
    show()
    await flushPromises()
    expect(resetPanel).toHaveBeenCalled()
    expect(page.get('[data-test="chat-panel"]').element).not.toBe(firstPanel)
    expect(page.find('button').exists()).toBe(false)
  })

  it.each([
    { workspaceReady: false }, { sessionCheckUnavailable: true },
    { isAdminAccount: true }, { userRole: 'tenant:reader' },
  ])('keeps the launcher only when the session cannot chat: %j', async flags => {
    Object.assign(profile, flags)
    const page = view()
    await flushPromises()
    expect(page.find('[data-test="chat-panel"]').exists()).toBe(false)
    desktop.openMain.mockRejectedValueOnce(new Error('主窗口暂不可用'))
    await page.get('button').trigger('click')
    await flushPromises()
    expect(desktop.openMain).toHaveBeenCalledOnce()
  })

  it('does not mount private chat for an anonymous storage scope', async () => {
    durable.mockReturnValue(false)
    const page = view()
    await flushPromises()
    expect(page.find('[data-test="chat-panel"]').exists()).toBe(false)
    expect(resolveIdentity).not.toHaveBeenCalled()
  })

  it.each(['session-hint', null])('clears chat for a cross-window logout (%s) and rejects a late refresh', async key => {
    const page = view()
    await flushPromises()
    storage('unrelated-key')
    storage('session-hint', sessionStorage)
    storage('session-hint', localStorage, 'replacement')
    expect(profile.clear).not.toHaveBeenCalled()
    let finish!: () => void
    profile.refreshFromServer.mockReturnValueOnce(new Promise<void>(resolve => { finish = resolve }))
    show()
    storage(key)
    await flushPromises()
    expect(profile.clear).toHaveBeenCalledWith(false)
    expect(page.find('[data-test="chat-panel"]').exists()).toBe(false)
    finish()
    await flushPromises()
    expect(page.find('[data-test="chat-panel"]').exists()).toBe(false)
    expect(page.get('button').attributes('disabled')).toBeUndefined()
  })

  it('keeps the latest successful refresh when an older request fails', async () => {
    let fail!: (reason: Error) => void
    profile.refreshFromServer.mockReturnValueOnce(new Promise<void>((_, reject) => { fail = reject }))
    const page = view()
    show()
    await flushPromises()
    fail(new Error('旧请求失败'))
    await flushPromises()
    expect(page.find('[data-test="chat-panel"]').exists()).toBe(true)
    expect(profile.clear).not.toHaveBeenCalled()
    profile.refreshFromServer.mockRejectedValueOnce(new Error('当前会话失败'))
    show()
    await flushPromises()
    expect(page.find('[data-test="chat-panel"]').exists()).toBe(false)
    expect(profile.clear).toHaveBeenCalledWith(false)
  })

  it('invalidates immediately and removes listeners before a pending refresh completes after unmount', async () => {
    const page = view()
    await flushPromises()
    window.dispatchEvent(new Event('xcagi:enterprise-session-invalid'))
    await flushPromises()
    expect(page.find('[data-test="chat-panel"]').exists()).toBe(false)
    let finish!: () => void
    profile.refreshFromServer.mockReturnValueOnce(new Promise<void>(resolve => { finish = resolve }))
    show()
    page.unmount()
    wrapper = undefined
    profile.clear.mockClear()
    storage(null)
    window.dispatchEvent(new Event('xcagi:enterprise-session-invalid'))
    finish()
    await flushPromises()
    expect(stopWatching).toHaveBeenCalledOnce()
    expect(profile.clear).not.toHaveBeenCalled()
  })
})
