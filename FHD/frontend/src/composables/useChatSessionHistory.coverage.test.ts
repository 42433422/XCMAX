import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { ref, nextTick, effectScope, type EffectScope } from 'vue'
import { setRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime'
import { setActivePinia, createPinia } from 'pinia'
import { useChatSessionHistory, type UseChatSessionHistoryDeps } from './useChatSessionHistory'
import type { TaskItem, LinkedExcelSheet } from './useChatPersistence'
import type { ShipmentTask } from './useShipmentTask'
import type { ChatMessage } from './useChatMessages'

const { chatApiMock, writeAiSessionIdToStorageMock, activeModIdRef } = vi.hoisted(() => {
  return {
    chatApiMock: {
      getConversations: vi.fn(),
      getConversation: vi.fn(),
      clearConversations: vi.fn(),
      renameConversation: vi.fn(),
      deleteConversation: vi.fn(),
    },
    writeAiSessionIdToStorageMock: vi.fn(),
    activeModIdRef: { value: '' } as { value: string },
  }
})

vi.mock('../api/chat', () => ({
  default: chatApiMock,
}))

vi.mock('@/stores/mods', async () => {
  const { ref } = await import('vue')
  const vueRef = ref(activeModIdRef.value)
  Object.defineProperty(activeModIdRef, 'value', {
    get: () => vueRef.value,
    set: (v: string) => {
      vueRef.value = v
    },
    configurable: true,
  })
  return {
    useModsStore: () => ({
      get activeModId() {
        return vueRef.value
      },
    }),
  }
})

vi.mock('@/utils/chatStorageKeys', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/utils/chatStorageKeys')>(),
  writeAiSessionIdToStorage: (...args: unknown[]) => writeAiSessionIdToStorageMock(...args),
  CHAT_MESSAGES_STORAGE_PREFIX: 'xcagi_chat_messages_',
  CHAT_SESSION_META_PREFIX: 'xcagi_chat_session_meta_',
  buildChatMessagesKey: (sid: string, _modId?: string) => `xcagi_chat_messages_${sid}`,
  buildChatSessionMetaKey: (sid: string, _modId?: string) => `xcagi_chat_session_meta_${sid}`,
  extractSessionIdForActiveMod: (prefix: string, key: string, _modId?: string) => {
    const raw = String(key || '')
    if (!raw.startsWith(prefix)) return null
    const rest = raw.slice(prefix.length)
    return rest || null
  },
}))

interface DepsOverrides {
  sessionId?: string
  taskList?: TaskItem[]
  activeTaskId?: string
  expandedTaskIds?: string[]
  taskFilter?: 'all' | 'running' | 'success' | 'failed'
  currentTask?: ShipmentTask | null
  lastExcelAnalysisContext?: Record<string, unknown> | null
  linkedExcelSheet?: LinkedExcelSheet | null
  linkedExcelAllSheets?: boolean
}

function makeDeps(overrides: DepsOverrides = {}) {
  const refs = {
    sessionId: ref(overrides.sessionId ?? 'current-sid'),
    taskList: ref<TaskItem[]>(overrides.taskList ?? []),
    activeTaskId: ref(overrides.activeTaskId ?? ''),
    expandedTaskIds: ref<string[]>(overrides.expandedTaskIds ?? []),
    taskFilter: ref<'all' | 'running' | 'success' | 'failed'>(overrides.taskFilter ?? 'all'),
    currentTask: ref<ShipmentTask | null>(overrides.currentTask ?? null),
    lastExcelAnalysisContext: ref<Record<string, unknown> | null>(overrides.lastExcelAnalysisContext ?? null),
    linkedExcelSheet: ref<LinkedExcelSheet | null>(overrides.linkedExcelSheet ?? null),
    linkedExcelAllSheets: ref<boolean>(overrides.linkedExcelAllSheets ?? false),
  }
  const mocks = {
    loadMessages: vi.fn(),
    clearMessages: vi.fn(),
    persistTaskPanelStateForSession: vi.fn(),
    applyPersistedTaskPanelStateForSession: vi.fn(),
    clearPersistedTaskPanelState: vi.fn(),
    generateSessionId: vi.fn(() => 'generated-new-sid'),
    normalizeServerContentToHtml: vi.fn((raw: unknown) => `<p>${String(raw ?? '')}</p>`),
  }
  return { deps: { ...refs, ...mocks }, refs, mocks }
}

const scopes: EffectScope[] = []
function makeHistory(deps: UseChatSessionHistoryDeps) {
  const scope = effectScope()
  scopes.push(scope)
  const history = scope.run(() => useChatSessionHistory(deps))!
  const register = history.registerHistoryModWatch
  history.registerHistoryModWatch = (refresh) => { scope.run(() => register(refresh)) }
  return history
}

describe('useChatSessionHistory — coverage ramp', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    sessionStorage.clear()
    activeModIdRef.value = ''
    setRuntimeTenantStorageScopeInput(null)
    vi.clearAllMocks()
    chatApiMock.getConversations.mockReset()
    chatApiMock.getConversation.mockReset()
    chatApiMock.clearConversations.mockReset()
    chatApiMock.renameConversation.mockReset()
    chatApiMock.deleteConversation.mockReset()
    writeAiSessionIdToStorageMock.mockReset()
    // 默认 window.confirm 返回 true
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    // 默认 console.error 静音
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    for (const scope of scopes.splice(0)) scope.stop()
    vi.restoreAllMocks()
    setRuntimeTenantStorageScopeInput(null)
  })

  // showHistoryPanel
  describe('showHistoryPanel', () => {
    it('refreshes sidebar sessions without opening the history modal', async () => {
      chatApiMock.getConversations.mockResolvedValue({
        success: true,
        sessions: [{ session_id: 'side-1', title: '侧栏会话', message_count: 2 }],
      })
      const { deps } = makeDeps()
      const { refreshHistorySessions, showHistory, historySessions } = makeHistory(deps)

      await refreshHistorySessions()

      expect(showHistory.value).toBe(false)
      expect(historySessions.value).toEqual([
        expect.objectContaining({ session_id: 'side-1', title: '侧栏会话', message_count: 2 }),
      ])
    })

    it('loads server sessions successfully and merges with local', async () => {
      chatApiMock.getConversations.mockResolvedValue({
        success: true,
        sessions: [{ session_id: 'srv1', title: 'Server 1', last_message_at: '2026-06-01' }],
      })
      const { deps } = makeDeps()
      const { showHistoryPanel, showHistory, historySessions, historyLoading, historyError } = makeHistory(deps)

      const promise = showHistoryPanel()
      expect(showHistory.value).toBe(true)
      expect(historyLoading.value).toBe(true)
      await promise

      expect(historyLoading.value).toBe(false)
      expect(historyError.value).toBe('')
      expect(historySessions.value.length).toBeGreaterThanOrEqual(1)
      const srv = historySessions.value.find((s) => s.session_id === 'srv1')
      expect(srv).toBeDefined()
      expect(srv!.is_local_only).toBe(false)
    })

    it('uses data.data when sessions absent', async () => {
      chatApiMock.getConversations.mockResolvedValue({
        success: true,
        data: [{ session_id: 'd1', title: 'D1' }],
      })
      const { deps } = makeDeps()
      const { showHistoryPanel, historySessions } = makeHistory(deps)
      await showHistoryPanel()
      expect(historySessions.value.find((s) => s.session_id === 'd1')).toBeDefined()
    })

    it('uses data.conversations when sessions and data absent', async () => {
      chatApiMock.getConversations.mockResolvedValue({
        success: true,
        conversations: [{ session_id: 'c1', title: 'C1' }],
      })
      const { deps } = makeDeps()
      const { showHistoryPanel, historySessions } = makeHistory(deps)
      await showHistoryPanel()
      expect(historySessions.value.find((s) => s.session_id === 'c1')).toBeDefined()
    })

    it('throws and falls back to local when data.success is false', async () => {
      chatApiMock.getConversations.mockResolvedValue({
        success: false,
        message: '权限不足',
      })
      const { deps } = makeDeps()
      const { showHistoryPanel, historySessions, historyError } = makeHistory(deps)
      await showHistoryPanel()
      // No local sessions either → error message surfaces
      expect(historySessions.value).toEqual([])
      expect(historyError.value).toBe('权限不足')
    })

    it('falls back to local sessions when API throws', async () => {
      // Provide a local session
      localStorage.setItem('xcagi_chat_messages_local1', JSON.stringify([{ role: 'user', content: 'local msg' }]))
      chatApiMock.getConversations.mockRejectedValue(new Error('Network error'))
      const { deps } = makeDeps()
      const { showHistoryPanel, historySessions, historyError } = makeHistory(deps)
      await showHistoryPanel()
      expect(historySessions.value.length).toBe(1)
      expect(historyError.value).toBe('') // local fallback exists, error suppressed
    })

    it('shows error message when API throws and no local fallback', async () => {
      chatApiMock.getConversations.mockRejectedValue(new Error('Network error'))
      const { deps } = makeDeps()
      const { showHistoryPanel, historySessions, historyError } = makeHistory(deps)
      await showHistoryPanel()
      expect(historySessions.value).toEqual([])
      expect(historyError.value).toBe('Network error')
    })

    it('shows generic error when API throws non-Error', async () => {
      chatApiMock.getConversations.mockRejectedValue('string error')
      const { deps } = makeDeps()
      const { showHistoryPanel, historyError } = makeHistory(deps)
      await showHistoryPanel()
      expect(historyError.value).toBe('加载历史失败，请稍后重试')
    })

    it('does nothing when already loading', async () => {
      chatApiMock.getConversations.mockImplementation(
        () => new Promise(() => {}), // never resolves
      )
      const { deps } = makeDeps()
      const { showHistoryPanel, historyLoading } = makeHistory(deps)
      const p1 = showHistoryPanel()
      expect(historyLoading.value).toBe(true)
      // Second call should be a no-op
      await showHistoryPanel()
      // Still loading from first call
      expect(historyLoading.value).toBe(true)
      // Cleanup: we can't await p1; just leave it
      void p1
    })

    it('handles data.success=false with no message field', async () => {
      chatApiMock.getConversations.mockResolvedValue({ success: false })
      const { deps } = makeDeps()
      const { showHistoryPanel, historyError } = makeHistory(deps)
      await showHistoryPanel()
      expect(historyError.value).toBe('加载历史失败')
    })
  })

  // loadSession
  describe('loadSession', () => {
    it('does nothing when targetSessionId is empty', async () => {
      const { deps } = makeDeps()
      const { loadSession, historyLoading } = makeHistory(deps)
      await loadSession('')
      expect(historyLoading.value).toBe(false)
      expect(chatApiMock.getConversation).not.toHaveBeenCalled()
    })

    it('does nothing when already loading', async () => {
      chatApiMock.getConversation.mockImplementation(() => new Promise(() => {}))
      const { deps } = makeDeps()
      const { loadSession, historyLoading } = makeHistory(deps)
      const p = loadSession('s1')
      expect(historyLoading.value).toBe(true)
      await loadSession('s2')
      // Still loading first
      expect(historyLoading.value).toBe(true)
      void p
    })

    it('loads server messages when success and serverMessages non-empty', async () => {
      chatApiMock.getConversation.mockResolvedValue({
        success: true,
        messages: [
          { role: 'user', content: 'hello' },
          { role: 'ai', content: 'world' },
        ],
      })
      const { deps, refs, mocks } = makeDeps({ sessionId: 'old-sid' })
      const { loadSession, showHistory } = makeHistory(deps)
      // Pre-open history panel
      showHistory.value = true

      await loadSession('new-sid')

      expect(refs.sessionId.value).toBe('new-sid')
      expect(writeAiSessionIdToStorageMock).toHaveBeenCalledWith('new-sid')
      expect(mocks.applyPersistedTaskPanelStateForSession).toHaveBeenCalledWith('new-sid')
      expect(mocks.persistTaskPanelStateForSession).toHaveBeenCalledWith('old-sid')
      expect(mocks.loadMessages).toHaveBeenCalled()
      // showHistory should be closed after successful load
      expect(showHistory.value).toBe(false)
    })

    it('keeps original local order context when approval returns only a server receipt', async () => {
      const local = [
        { role: 'user', content: '创建销售订单，数量2，单价9.90', time: '20:34' },
        { role: 'ai', content: '<p>等待审批</p>', time: '20:35', approvalCard: { approval_request_ids: ['approval-1'] } },
        { role: 'user', content: '确认创建', time: '20:36' },
      ]
      localStorage.setItem('xcagi_chat_messages_sale', JSON.stringify(local))
      localStorage.setItem('xcagi_chat_session_meta_sale', JSON.stringify({ title: '创建销售订单', message_count: 3 }))
      chatApiMock.getConversation.mockResolvedValue({ success: true, messages: [
        { role: 'assistant', content: '等待审批', time: '20:35' },
        { role: 'assistant', content: '审批完成，订单SO1，金额19.80', time: '20:38' },
      ] })
      chatApiMock.getConversations.mockResolvedValue({ success: true, sessions: [{ session_id: 'sale', message_count: 2 }] })
      const { deps, mocks } = makeDeps()
      const { loadSession, refreshHistorySessions, historySessions } = makeHistory(deps)
      await loadSession('sale')
      expect(mocks.loadMessages.mock.calls[0][0]).toEqual([
        local[0], expect.objectContaining({ role: 'ai', time: '20:35', approvalCard: expect.objectContaining(local[1].approvalCard) }),
        local[2], expect.objectContaining({ content: expect.stringContaining('订单SO1') }),
      ])
      await refreshHistorySessions()
      expect(historySessions.value[0]).toMatchObject({ title: '创建销售订单', message_count: 3, is_local_only: false })
    })

    it('preserves repeated user messages while matching each server copy once', async () => {
      const message = { role: 'user', content: '确认', time: '20:36' }
      localStorage.setItem('xcagi_chat_messages_repeat', JSON.stringify([message, message]))
      chatApiMock.getConversation.mockResolvedValue({ success: true, messages: [message, message] })
      const { deps, mocks } = makeDeps()
      await makeHistory(deps).loadSession('repeat')
      expect(mocks.loadMessages.mock.calls[0][0]).toHaveLength(2)
    })

    it('normalizes role to ai when not user/task', async () => {
      chatApiMock.getConversation.mockResolvedValue({
        success: true,
        messages: [{ role: 'assistant', content: 'reply' }],
      })
      const { deps, mocks } = makeDeps()
      const { loadSession } = makeHistory(deps)
      await loadSession('s1')
      const loaded = mocks.loadMessages.mock.calls[0][0] as ChatMessage[]
      expect(loaded[0].role).toBe('ai')
    })

    it('restores each server message original timestamp', async () => {
      const timestamp = '2026-07-13T10:25:00-07:00'
      chatApiMock.getConversation.mockResolvedValue({
        success: true,
        messages: [{ role: 'assistant', content: 'reply', timestamp }],
      })
      const { deps, mocks } = makeDeps()
      const { loadSession } = makeHistory(deps)
      await loadSession('s1')
      const loaded = mocks.loadMessages.mock.calls[0][0] as ChatMessage[]
      expect(loaded[0].time).toBe(new Date(timestamp).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }))
    })

    it('uses normalizeServerContentToHtml for content', async () => {
      chatApiMock.getConversation.mockResolvedValue({
        success: true,
        messages: [{ role: 'ai', content: 'raw text' }],
      })
      const { deps, mocks } = makeDeps()
      const { loadSession } = makeHistory(deps)
      await loadSession('s1')
      expect(mocks.normalizeServerContentToHtml).toHaveBeenCalledWith('raw text')
    })

    it('falls back to local messages when server success but no server messages', async () => {
      localStorage.setItem('xcagi_chat_messages_local-sid', JSON.stringify([{ role: 'user', content: 'local msg' }]))
      chatApiMock.getConversation.mockResolvedValue({
        success: true,
        messages: [],
      })
      const { deps, mocks } = makeDeps()
      const { loadSession, showHistory } = makeHistory(deps)
      showHistory.value = true
      await loadSession('local-sid')
      expect(mocks.loadMessages).toHaveBeenCalled()
      const loaded = mocks.loadMessages.mock.calls[0][0] as ChatMessage[]
      expect(loaded[0].content).toBe('local msg')
      expect(showHistory.value).toBe(false)
    })

    it('does not double-escape cached HTML entities when restoring local history', async () => {
      localStorage.setItem(
        'xcagi_chat_messages_local-entity',
        JSON.stringify([{ role: 'ai', content: '状态为 &quot;正常&quot;', time: '07:25' }]),
      )
      chatApiMock.getConversation.mockResolvedValue({ success: true, messages: [] })
      const { deps, mocks } = makeDeps()
      const { loadSession } = makeHistory(deps)
      await loadSession('local-entity')
      const loaded = mocks.loadMessages.mock.calls[0][0] as ChatMessage[]
      expect(loaded[0].content).toBe('状态为 &quot;正常&quot;')
      expect(loaded[0].content).not.toContain('&amp;quot;')
    })

    it('loads placeholder when server success, no messages, no local', async () => {
      chatApiMock.getConversation.mockResolvedValue({
        success: true,
        messages: [],
      })
      const { deps, mocks } = makeDeps()
      const { loadSession, showHistory } = makeHistory(deps)
      showHistory.value = true
      await loadSession('empty-sid')
      expect(mocks.loadMessages).toHaveBeenCalled()
      const loaded = mocks.loadMessages.mock.calls[0][0] as ChatMessage[]
      expect(loaded[0].role).toBe('ai')
      expect(String(loaded[0].content)).toContain('该会话暂无消息记录')
      expect(showHistory.value).toBe(false)
    })

    it('throws and falls back to local messages when server fails', async () => {
      localStorage.setItem('xcagi_chat_messages_local-sid', JSON.stringify([{ role: 'user', content: 'local fallback' }]))
      chatApiMock.getConversation.mockResolvedValue({
        success: false,
        message: '会话不存在',
      })
      const { deps, mocks, refs } = makeDeps()
      const { loadSession, showHistory, historyError } = makeHistory(deps)
      showHistory.value = true
      await loadSession('local-sid')
      expect(mocks.loadMessages).toHaveBeenCalled()
      expect(historyError.value).toBe('')
      expect(showHistory.value).toBe(false)
      // sessionId should remain as new (local fallback succeeded)
      expect(refs.sessionId.value).toBe('local-sid')
    })

    it('rolls back sessionId and shows error when server fails and no local fallback', async () => {
      chatApiMock.getConversation.mockResolvedValue({
        success: false,
        message: '会话不存在',
      })
      const { deps, refs } = makeDeps({ sessionId: 'original-sid' })
      const { loadSession, historyError } = makeHistory(deps)
      await loadSession('bad-sid')
      expect(historyError.value).toBe('会话不存在')
      expect(refs.sessionId.value).toBe('original-sid')
      expect(writeAiSessionIdToStorageMock).toHaveBeenCalledWith('original-sid')
      expect(deps.applyPersistedTaskPanelStateForSession).toHaveBeenCalledWith('original-sid')
    })

    it('rolls back when API throws and no local fallback', async () => {
      chatApiMock.getConversation.mockRejectedValue(new Error('Network down'))
      const { deps, refs } = makeDeps({ sessionId: 'original-sid' })
      const { loadSession, historyError } = makeHistory(deps)
      await loadSession('bad-sid')
      expect(historyError.value).toBe('Network down')
      expect(refs.sessionId.value).toBe('original-sid')
    })

    it('shows generic error when API throws non-Error and no local fallback', async () => {
      chatApiMock.getConversation.mockRejectedValue('string error')
      const { deps } = makeDeps()
      const { loadSession, historyError } = makeHistory(deps)
      await loadSession('bad-sid')
      expect(historyError.value).toBe('加载会话失败，请稍后重试')
    })

    it('uses default message when server fails without message field', async () => {
      chatApiMock.getConversation.mockResolvedValue({ success: false })
      const { deps } = makeDeps()
      const { loadSession, historyError } = makeHistory(deps)
      await loadSession('bad-sid')
      expect(historyError.value).toBe('加载会话失败')
    })

    it('persists previous session panel state before switching', async () => {
      chatApiMock.getConversation.mockResolvedValue({ success: true, messages: [] })
      const { deps, mocks } = makeDeps({ sessionId: 'prev-sid' })
      const { loadSession } = makeHistory(deps)
      await loadSession('new-sid')
      expect(mocks.persistTaskPanelStateForSession).toHaveBeenCalledWith('prev-sid')
    })

    it('uses "default" when previous sessionId is empty', async () => {
      chatApiMock.getConversation.mockResolvedValue({ success: true, messages: [] })
      const { deps, mocks } = makeDeps({ sessionId: '' })
      const { loadSession } = makeHistory(deps)
      await loadSession('new-sid')
      expect(mocks.persistTaskPanelStateForSession).toHaveBeenCalledWith('default')
    })

    it('sets historyLoading to false in finally block', async () => {
      chatApiMock.getConversation.mockRejectedValue(new Error('boom'))
      const { deps } = makeDeps()
      const { loadSession, historyLoading } = makeHistory(deps)
      await loadSession('bad-sid')
      expect(historyLoading.value).toBe(false)
    })
  })

  // clearHistorySessions
  describe('clearHistorySessions', () => {
    it('does nothing when user cancels confirm', async () => {
      vi.spyOn(window, 'confirm').mockReturnValue(false)
      const { deps } = makeDeps()
      const { clearHistorySessions, historyLoading } = makeHistory(deps)
      await clearHistorySessions()
      expect(historyLoading.value).toBe(false)
      expect(chatApiMock.clearConversations).not.toHaveBeenCalled()
    })

    it('does nothing when already loading', async () => {
      vi.spyOn(window, 'confirm').mockReturnValue(false)
      const { deps } = makeDeps()
      const api = makeHistory(deps)
      // Force loading state via showHistoryPanel that never resolves
      chatApiMock.getConversations.mockImplementation(() => new Promise(() => {}))
      const p = api.showHistoryPanel()
      expect(api.historyLoading.value).toBe(true)
      await api.clearHistorySessions()
      // Should still be loading (clearHistorySessions was a no-op)
      expect(api.historyLoading.value).toBe(true)
      void p
    })

    it('clears local cache and server sessions successfully', async () => {
      localStorage.setItem('xcagi_chat_messages_s1', JSON.stringify([{ role: 'user', content: 'msg' }]))
      chatApiMock.clearConversations.mockResolvedValue({ success: true, deleted: 5 })
      const { deps } = makeDeps()
      const { clearHistorySessions, historyLoading, historyError, historySessions } = makeHistory(deps)
      await clearHistorySessions()
      expect(historyLoading.value).toBe(false)
      expect(historyError.value).toBe('')
      expect(historySessions.value).toEqual([])
      expect(localStorage.getItem('xcagi_chat_messages_s1')).toBeNull()
    })

    it('shows error when server returns success=false', async () => {
      chatApiMock.clearConversations.mockResolvedValue({
        success: false,
        message: '清空失败原因',
      })
      const { deps } = makeDeps()
      const { clearHistorySessions, historyError } = makeHistory(deps)
      await clearHistorySessions()
      expect(historyError.value).toBe('清空失败原因')
    })

    it('uses default message when server returns success=false without message', async () => {
      chatApiMock.clearConversations.mockResolvedValue({ success: false })
      const { deps } = makeDeps()
      const { clearHistorySessions, historyError } = makeHistory(deps)
      await clearHistorySessions()
      expect(historyError.value).toBe('清空历史失败')
    })

    it('shows error when API throws', async () => {
      chatApiMock.clearConversations.mockRejectedValue(new Error('Server down'))
      const { deps } = makeDeps()
      const { clearHistorySessions, historyError } = makeHistory(deps)
      await clearHistorySessions()
      expect(historyError.value).toBe('Server down')
    })

    it('shows generic error when API throws non-Error', async () => {
      chatApiMock.clearConversations.mockRejectedValue('string error')
      const { deps } = makeDeps()
      const { clearHistorySessions, historyError } = makeHistory(deps)
      await clearHistorySessions()
      expect(historyError.value).toBe('清空历史失败，本机记录已保留，请稍后重试')
    })

    it('sets historyLoading to false in finally block', async () => {
      chatApiMock.clearConversations.mockRejectedValue(new Error('boom'))
      const { deps } = makeDeps()
      const { clearHistorySessions, historyLoading } = makeHistory(deps)
      await clearHistorySessions()
      expect(historyLoading.value).toBe(false)
    })

    it('passes user_id default to clearConversations', async () => {
      chatApiMock.clearConversations.mockResolvedValue({ success: true })
      const { deps } = makeDeps()
      const { clearHistorySessions } = makeHistory(deps)
      await clearHistorySessions()
      expect(chatApiMock.clearConversations).toHaveBeenCalledWith({ user_id: 'default' })
    })

    it('preserves both local cache and visible sessions until a successful remote receipt', async () => {
      let resolve!: (value: unknown) => void
      chatApiMock.clearConversations.mockReturnValue(new Promise(r => { resolve = r }))
      const { deps } = makeDeps()
      const history = makeHistory(deps)
      const original = [{ session_id: 's1', title: 'preserved' }]
      history.historySessions.value = original
      localStorage.setItem('xcagi_chat_messages_s1', 'original')
      const clearing = history.clearHistorySessions()
      expect(localStorage.getItem('xcagi_chat_messages_s1')).toBe('original')
      resolve({ success: false, message: 'remote refused' })
      await clearing
      expect(localStorage.getItem('xcagi_chat_messages_s1')).toBe('original')
      expect(history.historySessions.value).toEqual(original)
      expect(history.historyError.value).toBe('remote refused')
    })

    it('reports remote success and local failure as a partial clear', async () => {
      chatApiMock.clearConversations.mockResolvedValue({ success: true })
      localStorage.setItem('xcagi_chat_messages_s1', JSON.stringify([{ role: 'user', content: 'retained' }]))
      vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => { throw new Error('storage denied') })
      const history = makeHistory(makeDeps().deps)
      await history.clearHistorySessions()
      expect(history.historyError.value).toContain('服务端历史已清空，本机缓存清理未完成')
      expect(localStorage.getItem('xcagi_chat_messages_s1')).toContain('retained')
      expect(history.historySessions.value.some(item => item.session_id === 's1')).toBe(true)
    })
  })

  // newConversation
  describe('newConversation', () => {
    it('clears all state and generates new sessionId', () => {
      const { deps, refs, mocks } = makeDeps({
        sessionId: 'old-sid',
        taskList: [
          {
            id: 't1',
            type: 'shipment',
            title: 'T',
            source: 'shipment',
            status: 'success',
            startedAt: 1,
            updatedAt: 2,
          },
        ],
        activeTaskId: 't1',
        expandedTaskIds: ['t1'],
        taskFilter: 'success',
        currentTask: { type: 'shipment_generate' } as ShipmentTask,
        lastExcelAnalysisContext: { file_path: '/x.xlsx' },
        linkedExcelSheet: { sheet_name: 'S1', sheet_index: 1 },
        linkedExcelAllSheets: true,
      })

      const { newConversation } = makeHistory(deps)
      newConversation()

      expect(refs.sessionId.value).toBe('generated-new-sid')
      expect(writeAiSessionIdToStorageMock).toHaveBeenCalledWith('generated-new-sid')
      expect(refs.taskList.value).toEqual([])
      expect(refs.activeTaskId.value).toBe('')
      expect(refs.expandedTaskIds.value).toEqual([])
      expect(refs.taskFilter.value).toBe('all')
      expect(refs.currentTask.value).toBeNull()
      expect(refs.lastExcelAnalysisContext.value).toBeNull()
      expect(refs.linkedExcelSheet.value).toBeNull()
      expect(refs.linkedExcelAllSheets.value).toBe(false)
      expect(mocks.clearMessages).toHaveBeenCalled()
      expect(mocks.clearPersistedTaskPanelState).toHaveBeenCalledWith('generated-new-sid')
      expect(mocks.persistTaskPanelStateForSession).toHaveBeenCalledWith('old-sid')
      expect(mocks.persistTaskPanelStateForSession).toHaveBeenCalledWith('generated-new-sid')
    })

    it('uses "default" when previous sessionId is empty', () => {
      const { deps, mocks } = makeDeps({ sessionId: '' })
      const { newConversation } = makeHistory(deps)
      newConversation()
      expect(mocks.persistTaskPanelStateForSession).toHaveBeenCalledWith('default')
    })

    it('uses generated sessionId from generateSessionId dep', () => {
      const customGen = vi.fn(() => 'custom-new-id')
      const { deps, refs } = makeDeps()
      deps.generateSessionId = customGen
      const { newConversation } = makeHistory(deps)
      newConversation()
      expect(refs.sessionId.value).toBe('custom-new-id')
      expect(customGen).toHaveBeenCalled()
    })
  })

  // registerHistoryModWatch
  describe('registerHistoryModWatch', () => {
    it('refreshes history panel when mod changes and panel is open', async () => {
      chatApiMock.getConversations.mockResolvedValue({ success: true, sessions: [] })
      const { deps } = makeDeps()
      const api = makeHistory(deps)
      api.registerHistoryModWatch(api.showHistoryPanel)
      api.showHistory.value = true
      await nextTick()
      // Reset mock to clear any prior calls from initialization
      chatApiMock.getConversations.mockClear()
      // Trigger mod change
      activeModIdRef.value = 'new-mod'
      await nextTick()
      // Wait for the watch callback's async showHistoryPanelFn
      await new Promise((resolve) => setTimeout(resolve, 10))
      expect(chatApiMock.getConversations).toHaveBeenCalled()
    })

    it('resets historySessions when mod changes and panel is closed but sessions exist', async () => {
      const { deps } = makeDeps()
      const api = makeHistory(deps)
      // Pre-populate historySessions
      chatApiMock.getConversations.mockResolvedValue({
        success: true,
        sessions: [{ session_id: 's1', title: 'T1' }],
      })
      await api.showHistoryPanel()
      expect(api.historySessions.value.length).toBeGreaterThan(0)

      api.registerHistoryModWatch(api.showHistoryPanel)
      // Close panel (same instance)
      api.showHistory.value = false
      await nextTick()
      // Trigger mod change
      activeModIdRef.value = 'changed-mod'
      await nextTick()
      // historySessions should be reset (mergeHistorySessions([]) returns [])
      expect(api.historySessions.value).toEqual([])
    })

    it('does nothing when mod changes, panel closed, and no sessions', async () => {
      const { deps } = makeDeps()
      const api = makeHistory(deps)
      // Use a spy to track if showHistoryPanelFn is called
      const spy = vi.fn().mockResolvedValue(undefined)
      api.registerHistoryModWatch(spy)
      // Verify initial state
      expect(api.showHistory.value).toBe(false)
      expect(api.historySessions.value).toEqual([])
      await nextTick()
      // Trigger mod change
      activeModIdRef.value = 'changed-mod'
      await nextTick()
      // Verify state is still closed/empty
      expect(api.showHistory.value).toBe(false)
      expect(api.historySessions.value).toEqual([])
      // showHistoryPanelFn should NOT be called (panel closed, no sessions)
      expect(spy).not.toHaveBeenCalled()
    })

    it('clears historyError when mod changes', async () => {
      const { deps } = makeDeps()
      const api = makeHistory(deps)
      // Force an error
      chatApiMock.getConversations.mockRejectedValue(new Error('boom'))
      await api.showHistoryPanel()
      expect(api.historyError.value).toBe('boom')
      // showHistoryPanel sets showHistory=true; close it so watch doesn't re-trigger
      api.showHistory.value = false

      api.registerHistoryModWatch(api.showHistoryPanel)
      activeModIdRef.value = 'changed-mod'
      await nextTick()
      expect(api.historyError.value).toBe('')
    })
  })

  describe('pending actions and session editing', () => {
    function deferred() {
      let resolve!: (value: Record<string, unknown>) => void
      let reject!: (error: Error) => void
      const promise = new Promise<Record<string, unknown>>((yes, no) => { resolve = yes; reject = no })
      return { promise, resolve, reject }
    }

    it.each([true, false])('does not restore an abandoned session after starting a new conversation, response success=%s', async (success) => {
      const pending = deferred()
      chatApiMock.getConversation.mockReturnValue(pending.promise)
      const { deps, mocks, refs } = makeDeps()
      const history = makeHistory(deps)
      const loading = history.loadSession('abandoned')
      history.newConversation()
      if (success) pending.resolve({ success: true, messages: [{ role: 'ai', content: 'old account data' }] })
      else pending.reject(new Error('old session error'))
      await loading
      expect(refs.sessionId.value).toBe('generated-new-sid')
      expect(mocks.loadMessages).not.toHaveBeenCalled()
      expect(history.historyError.value).toBe('')
      expect(history.historyLoading.value).toBe(false)
      expect(writeAiSessionIdToStorageMock.mock.lastCall).toEqual(['generated-new-sid'])
    })

    it('does not restore a session or its persisted ID after the chat owner is disposed', async () => {
      const pending = deferred()
      chatApiMock.getConversation.mockReturnValue(pending.promise)
      const { deps, mocks } = makeDeps()
      const history = makeHistory(deps)
      const loading = history.loadSession('old-page')
      scopes.at(-1)!.stop()
      writeAiSessionIdToStorageMock.mockClear()
      pending.reject(new Error('old page failed'))
      await loading
      expect(mocks.loadMessages).not.toHaveBeenCalled()
      expect(writeAiSessionIdToStorageMock).not.toHaveBeenCalled()
    })

    it('loads the new Mod history while the old Mod request is pending and ignores its late result', async () => {
      const pending = deferred()
      chatApiMock.getConversations.mockReturnValueOnce(pending.promise).mockResolvedValueOnce({
        success: true, sessions: [{ session_id: 'new-mod-session', title: 'New Mod' }],
      })
      const { deps } = makeDeps()
      const history = makeHistory(deps)
      history.registerHistoryModWatch(history.showHistoryPanel)
      const old = history.showHistoryPanel()
      activeModIdRef.value = 'new-mod'
      await nextTick()
      await Promise.resolve()
      pending.resolve({ success: true, sessions: [{ session_id: 'old-mod-session' }] })
      await old
      expect(chatApiMock.getConversations).toHaveBeenCalledTimes(2)
      expect(history.historySessions.value.map((item) => item.session_id)).toEqual(['new-mod-session'])
      expect(history.historyLoading.value).toBe(false)
    })

    it.each([true, false])('ignores a pending session load after changing tenant, success=%s', async (success) => {
      setRuntimeTenantStorageScopeInput({ tenantId: 1 })
      const pending = deferred()
      chatApiMock.getConversation.mockReturnValue(pending.promise)
      const { deps, mocks, refs } = makeDeps()
      const history = makeHistory(deps)
      const loading = history.loadSession('tenant-one')
      setRuntimeTenantStorageScopeInput({ tenantId: 2 })
      refs.sessionId.value = 'tenant-two'
      if (success) pending.resolve({ success: true, messages: [{ content: 'private tenant-one message' }] })
      else pending.reject(new Error('tenant-one failed'))
      await loading
      expect(mocks.loadMessages).not.toHaveBeenCalled()
      expect(refs.sessionId.value).toBe('tenant-two')
      expect(history.historyError.value).toBe('')
      expect(history.historyLoading.value).toBe(false)
    })

    it('renames only the requested session using trimmed input', async () => {
      chatApiMock.renameConversation.mockResolvedValue({ success: true })
      const { deps } = makeDeps()
      const history = makeHistory(deps)
      history.historySessions.value = [{ session_id: 'one', title: 'Before' }, { session_id: 'two', title: 'Unchanged' }]
      expect(await history.renameSession(' one ', ' After ')).toBe(true)
      expect(chatApiMock.renameConversation).toHaveBeenCalledWith('one', 'After')
      expect(history.historySessions.value.map((item) => item.title)).toEqual(['After', 'Unchanged'])
    })

    it.each([true, false])('deletes the selected cache and resets the active conversation only when active=%s', async (active) => {
      chatApiMock.deleteConversation.mockResolvedValue({ success: true })
      const { deps, refs, mocks } = makeDeps({ sessionId: active ? 'removed' : 'kept' })
      const history = makeHistory(deps)
      history.historySessions.value = [{ session_id: 'removed' }, { session_id: 'kept' }]
      localStorage.setItem('xcagi_chat_messages_removed', JSON.stringify([{ role: 'user', content: 'old' }]))
      expect(await history.deleteSession(' removed ')).toBe(true)
      expect(chatApiMock.deleteConversation).toHaveBeenCalledWith('removed')
      expect(history.historySessions.value.map((item) => item.session_id)).toEqual(['kept'])
      expect(localStorage.getItem('xcagi_chat_messages_removed')).toBeNull()
      expect(refs.sessionId.value).toBe(active ? 'generated-new-sid' : 'kept')
      expect(mocks.clearMessages).toHaveBeenCalledTimes(active ? 1 : 0)
    })

    it.each(['rename', 'delete'] as const)('does not let a late %s response change a newly selected Mod', async (action) => {
      const pending = deferred()
      const method = action === 'rename' ? chatApiMock.renameConversation : chatApiMock.deleteConversation
      method.mockReturnValue(pending.promise)
      const { deps, mocks } = makeDeps({ sessionId: 'same-id' })
      const history = makeHistory(deps)
      const operation = action === 'rename' ? history.renameSession('same-id', 'Old Mod title') : history.deleteSession('same-id')
      activeModIdRef.value = 'new-mod'
      history.historySessions.value = [{ session_id: 'same-id', title: 'New Mod title' }]
      localStorage.setItem('xcagi_chat_messages_same-id', JSON.stringify([{ role: 'user', content: 'new Mod cache' }]))
      pending.resolve({ success: true })
      expect(await operation).toBe(false)
      expect(history.historySessions.value).toEqual([{ session_id: 'same-id', title: 'New Mod title' }])
      expect(localStorage.getItem('xcagi_chat_messages_same-id')).toContain('new Mod cache')
      expect(mocks.clearMessages).not.toHaveBeenCalled()
    })

    it.each(['rename', 'delete'] as const)('%s reports API failures without changing the session list', async (action) => {
      const method = action === 'rename' ? chatApiMock.renameConversation : chatApiMock.deleteConversation
      method.mockResolvedValue({ success: false, message: 'permission denied' })
      const { deps } = makeDeps()
      const history = makeHistory(deps)
      history.historySessions.value = [{ session_id: 'one', title: 'Before' }]
      const result = action === 'rename' ? await history.renameSession('one', 'After') : await history.deleteSession('one')
      expect(result).toBe(false)
      expect(history.historyError.value).toBe('permission denied')
      expect(history.historySessions.value).toEqual([{ session_id: 'one', title: 'Before' }])
    })
  })

  // 返回值结构
  describe('return shape', () => {
    it('exposes all expected fields', () => {
      const { deps } = makeDeps()
      const result = makeHistory(deps)
      expect(result).toHaveProperty('showHistory')
      expect(result).toHaveProperty('historySessions')
      expect(result).toHaveProperty('historyLoading')
      expect(result).toHaveProperty('historyError')
      expect(result).toHaveProperty('showHistoryPanel')
      expect(result).toHaveProperty('loadSession')
      expect(result).toHaveProperty('clearHistorySessions')
      expect(result).toHaveProperty('newConversation')
      expect(result).toHaveProperty('registerHistoryModWatch')
    })

    it('initializes with default state', () => {
      const { deps } = makeDeps()
      const { showHistory, historySessions, historyLoading, historyError } = makeHistory(deps)
      expect(showHistory.value).toBe(false)
      expect(historySessions.value).toEqual([])
      expect(historyLoading.value).toBe(false)
      expect(historyError.value).toBe('')
    })
  })
  it('clears the view on owner change but keeps it on an identical identity refresh', async () => {
    const { deps } = makeDeps()
    const onIdentityChange = vi.fn()
    deps.onIdentityChange = onIdentityChange
    const history = makeHistory(deps)
    history.registerHistoryModWatch(async () => {})
    setRuntimeTenantStorageScopeInput({ tenantId: 9, localUserId: 1 })
    await nextTick()
    const cleared = vi.mocked(deps.clearMessages).mock.calls.length
    const identityChanges = onIdentityChange.mock.calls.length
    setRuntimeTenantStorageScopeInput({ tenantId: 9, localUserId: 1 })
    await nextTick()
    expect(deps.clearMessages).toHaveBeenCalledTimes(cleared)
    expect(onIdentityChange).toHaveBeenCalledTimes(identityChanges)
    setRuntimeTenantStorageScopeInput({ tenantId: 9, localUserId: 2 })
    await nextTick()
    expect(deps.clearMessages).toHaveBeenCalledTimes(cleared + 1)
    expect(onIdentityChange).toHaveBeenCalledTimes(identityChanges + 1)
    expect(deps.taskList.value).toEqual([])
  })

})
