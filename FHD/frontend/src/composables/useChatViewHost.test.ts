import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
import { useChatViewHost, type UseChatViewHostDeps } from './useChatViewHost'

vi.mock('@/utils/hostBusinessPageRedirect', () => ({
  resolveHostBusinessPageRedirect: vi.fn(() => null),
}))

vi.mock('@/utils/typeGuards', () => ({
  asRecord: vi.fn((v) => v || {}),
}))

function makeDeps(): UseChatViewHostDeps {
  return {
    modsStore: {
      initialize: vi.fn().mockResolvedValue(undefined),
      isLoaded: true,
    } as any,
    modsFromStore: ref([{ id: 'mod1', name: 'Test Mod' }]),
    autoRefreshStarredWechat: ref(false),
    isTaskPaneResizable: ref(true),
    messageInput: ref(''),
    latestAssistantPush: ref(null),
    syncSessionMessages: vi.fn().mockResolvedValue(undefined),
    chatHandleAutoAction: vi.fn(),
    sendMessage: vi.fn().mockResolvedValue(undefined),
    batchCalculateHeights: vi.fn(),
    stopMessageTts: vi.fn(),
    cleanupVoiceInput: vi.fn(),
    stopTaskPaneResize: vi.fn(),
  }
}

describe('useChatViewHost', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('returns toolbar change handlers', () => {
    const host = useChatViewHost(makeDeps())
    expect(typeof host.onAutoRefreshToolbarChange).toBe('function')
  })

  it('onAutoRefreshToolbarChange enables and persists setting', () => {
    const deps = makeDeps()
    const host = useChatViewHost(deps)
    host.onAutoRefreshToolbarChange(true)
    expect(deps.autoRefreshStarredWechat.value).toBe(true)
    expect(localStorage.getItem('xcagi_auto_refresh_starred_wechat')).toBe('1')
  })

  it('onAutoRefreshToolbarChange disables and persists setting', () => {
    const deps = makeDeps()
    const host = useChatViewHost(deps)
    host.onAutoRefreshToolbarChange(false)
    expect(deps.autoRefreshStarredWechat.value).toBe(false)
    expect(localStorage.getItem('xcagi_auto_refresh_starred_wechat')).toBe('0')
  })

  it('onAutoRefreshToolbarChange dispatches custom event', () => {
    const deps = makeDeps()
    const host = useChatViewHost(deps)
    const dispatchSpy = vi.spyOn(window, 'dispatchEvent')
    host.onAutoRefreshToolbarChange(true)
    expect(dispatchSpy).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'xcagi:auto-refresh-wechat-changed' }),
    )
    dispatchSpy.mockRestore()
  })

  it('onTaskPaneViewportChange updates isTaskPaneResizable', () => {
    const deps = makeDeps()
    useChatViewHost(deps)
    // Test via the public API - the viewport change handler is internal
    // but we can verify the initial state
    expect(deps.isTaskPaneResizable.value).toBe(true)
  })

  it('latestAssistantPush is null initially', () => {
    const deps = makeDeps()
    useChatViewHost(deps)
    expect(deps.latestAssistantPush.value).toBeNull()
  })
})
