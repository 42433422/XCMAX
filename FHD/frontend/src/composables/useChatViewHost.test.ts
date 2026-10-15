import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
import { useChatViewHost, type UseChatViewHostDeps } from './useChatViewHost'

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
