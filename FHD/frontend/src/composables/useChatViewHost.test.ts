import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { defineComponent, h, KeepAlive, nextTick, ref } from 'vue'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { useChatViewHost, type UseChatViewHostDeps } from './useChatViewHost'

const startup = vi.hoisted(() => ({ register: vi.fn(), preparePage: vi.fn(), consumePrompt: vi.fn() }))
vi.mock('@/composables/useStartupSplash', () => ({ useStartupPageReady: startup.register }))
vi.mock('@/constants/productFlow', () => ({ consumeFirstAiTaskPrompt: startup.consumePrompt }))

function makeDeps(): UseChatViewHostDeps {
  return {
    modsStore: {
      initialize: vi.fn().mockResolvedValue(undefined),
      isLoaded: true,
    } as unknown as UseChatViewHostDeps['modsStore'],
    modsFromStore: ref([{ id: 'mod1', name: 'Test Mod' }]),
    autoRefreshStarredWechat: ref(false),
    isTaskPaneResizable: ref(true),
    messageInput: ref(''),
    latestAssistantPush: ref(null),
    syncSessionMessages: vi.fn().mockResolvedValue(undefined),
    pageScopeKey: () => JSON.stringify(['synthetic-session', 'mod1', 1]),
    chatHandleAutoAction: vi.fn(),
    sendMessage: vi.fn().mockResolvedValue(undefined),
    batchCalculateHeights: vi.fn(),
    stopMessageTts: vi.fn(),
    cleanupVoiceInput: vi.fn(),
    stopTaskPaneResize: vi.fn(),
  }
}

describe('useChatViewHost', () => {
  let wrapper: VueWrapper | undefined
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
    localStorage.clear()
    startup.register.mockReturnValue(startup.preparePage)
    startup.preparePage.mockResolvedValue(undefined)
    startup.consumePrompt.mockReturnValue('')
  })
  afterEach(() => {
    wrapper?.unmount(); wrapper = undefined
    vi.clearAllTimers()
    vi.useRealTimers()
  })

  function mountHost(deps: UseChatViewHostDeps) {
    const visible = ref(true)
    const Host = defineComponent({ setup() { useChatViewHost(deps); return () => h('section', 'chat') } })
    wrapper = mount(defineComponent({ setup: () => () => h(KeepAlive, null, {
      default: () => visible.value ? h(Host) : null,
    }) }))
    return visible
  }

  it('registers a strict current-page read and starts preparation on mount', async () => {
    const deps = makeDeps()
    mountHost(deps)
    expect(startup.register).toHaveBeenCalledOnce()
    expect(startup.register).toHaveBeenCalledWith(expect.any(Function), deps.pageScopeKey)
    expect(startup.preparePage).toHaveBeenCalledOnce()
    expect(deps.syncSessionMessages).not.toHaveBeenCalled()
    const current = vi.fn(() => true)
    await startup.register.mock.calls[0][0](current)
    expect(deps.syncSessionMessages).toHaveBeenCalledWith({ required: true, isCurrent: current })
    expect(deps.modsStore.initialize).toHaveBeenCalledOnce()
  })

  it('returns a required synchronization failure to the readiness hook', async () => {
    const deps = makeDeps()
    const failure = new Error('current conversation unavailable')
    vi.mocked(deps.syncSessionMessages).mockRejectedValue(failure)
    mountHost(deps)
    const current = () => true
    await expect(startup.register.mock.calls[0][0](current)).rejects.toBe(failure)
  })

  it('refreshes an activated cached page in the background without rerunning startup preparation', async () => {
    const deps = makeDeps()
    const visible = mountHost(deps)
    await nextTick()
    expect(deps.syncSessionMessages).not.toHaveBeenCalled()
    visible.value = false
    await nextTick()
    expect(deps.cleanupVoiceInput).toHaveBeenCalledOnce()
    visible.value = true
    await nextTick()
    expect(deps.syncSessionMessages).toHaveBeenCalledOnce()
    expect(deps.syncSessionMessages).toHaveBeenCalledWith()
    expect(startup.preparePage).toHaveBeenCalledOnce()
  })

  it('waits for initial page preparation before sending the one-time onboarding prompt', async () => {
    const deps = makeDeps()
    let finish!: () => void
    startup.preparePage.mockReturnValue(new Promise<void>(resolve => { finish = resolve }))
    startup.consumePrompt.mockReturnValue('合成首任务')
    mountHost(deps)
    expect(deps.sendMessage).not.toHaveBeenCalled()
    expect(deps.messageInput.value).toBe('')
    finish()
    await flushPromises()
    expect(deps.messageInput.value).toBe('合成首任务')
    expect(deps.sendMessage).toHaveBeenCalledOnce()
  })

  it('does not send the onboarding prompt after initial page preparation fails', async () => {
    const deps = makeDeps()
    startup.preparePage.mockRejectedValue(new Error('initial data failed'))
    startup.consumePrompt.mockReturnValue('合成首任务')
    mountHost(deps)
    await flushPromises()
    expect(deps.sendMessage).not.toHaveBeenCalled()
    expect(deps.messageInput.value).toBe('')
  })

  it.each([true, false])('persists the requested refresh setting %s', (enabled) => {
    const deps = makeDeps()
    useChatViewHost(deps).onAutoRefreshToolbarChange(enabled)
    expect(deps.autoRefreshStarredWechat.value).toBe(enabled)
    expect(localStorage.getItem('xcagi_auto_refresh_starred_wechat')).toBe(enabled ? '1' : '0')
  })

  it('onAutoRefreshToolbarChange dispatches custom event', () => {
    const deps = makeDeps()
    const host = useChatViewHost(deps)
    const dispatchSpy = vi.spyOn(window, 'dispatchEvent')
    host.onAutoRefreshToolbarChange(true)
    expect(dispatchSpy).toHaveBeenCalledWith(expect.objectContaining({ type: 'xcagi:auto-refresh-wechat-changed' }))
    dispatchSpy.mockRestore()
  })

})
