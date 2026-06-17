/**
 * Coverage ramp 测试：useChatSessionHistory
 *
 * 目标：覆盖 useChatSessionHistory.ts 中的：
 *   - showHistoryPanel（成功 / API 失败 / data.success=false / loading 防抖）
 *   - loadSession（成功 / 服务端有消息 / 仅本地消息 / 服务端成功但无消息 / 服务端失败回退本地 / 完全失败回滚）
 *   - clearHistorySessions（用户取消 / 成功 / API 失败 / loading 防抖）
 *   - newConversation（清空状态 + 持久化）
 *   - registerHistoryModWatch（mod 切换时刷新或重置）
 *
 * 铁律3：覆盖 happy path、空值/None、边界值、异常路径。
 * 铁律4：仅 mock 外部边界（chatApi / window.confirm / writeAiSessionIdToStorage），
 *        被测 composable 真实调用 useChatHistoryPersistence。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { ref, nextTick } from 'vue'
import { setActivePinia, createPinia } from 'pinia'
import { useChatSessionHistory } from './useChatSessionHistory'
import type { TaskItem, LinkedExcelSheet } from './useChatPersistence'
import type { ShipmentTask } from './useShipmentTask'
import type { ChatMessage } from './useChatMessages'

// -----------------------------------------------------------------------
// Mock 外部边界
// -----------------------------------------------------------------------

// vi.hoisted runs before vi.mock factories; used for shared mock objects.
const { chatApiMock, writeAiSessionIdToStorageMock, activeModIdRef } = vi.hoisted(() => {
  // Create a simple reactive-like object. We'll wrap with Vue's ref later
  // in beforeEach to enable watch reactivity.
  return {
    chatApiMock: {
      getConversations: vi.fn(),
      getConversation: vi.fn(),
      clearConversations: vi.fn(),
    },
    writeAiSessionIdToStorageMock: vi.fn(),
    activeModIdRef: { value: '' } as { value: string },
  }
})

vi.mock('../api/chat', () => ({
  default: chatApiMock,
}))

// writeAiSessionIdToStorage 是真实模块的简单写入；用 stub 避免拉起 tenantStorageScope 链
vi.mock('@/utils/xcagiStorageKeys', () => ({
  writeAiSessionIdToStorage: (...args: unknown[]) => writeAiSessionIdToStorageMock(...args),
}))

// modsStore stub：activeModId 由测试控制。
// 使用 getter 返回 activeModIdRef.value，使 watch(() => modsStore.activeModId) 能响应。
// 注意：由于 activeModIdRef 是普通对象（非 Vue ref），watch 不会自动追踪。
// 我们在 beforeEach 中用 Vue ref 替换 activeModIdRef 的 value 访问。
vi.mock('@/stores/mods', async () => {
  const { ref } = await import('vue')
  // Create a Vue ref that syncs with activeModIdRef
  const vueRef = ref(activeModIdRef.value)
  // Override activeModIdRef to use the Vue ref for reactivity
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

// chatStorageKeys stub：避免拉起 tenantStorageScope 解析链（外部边界）
vi.mock('@/utils/chatStorageKeys', () => ({
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

// -----------------------------------------------------------------------
// 测试工具
// -----------------------------------------------------------------------

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
  const sessionId = ref(overrides.sessionId ?? 'current-sid')
  const taskList = ref<TaskItem[]>(overrides.taskList ?? [])
  const activeTaskId = ref(overrides.activeTaskId ?? '')
  const expandedTaskIds = ref<string[]>(overrides.expandedTaskIds ?? [])
  const taskFilter = ref<'all' | 'running' | 'success' | 'failed'>(
    overrides.taskFilter ?? 'all',
  )
  const currentTask = ref<ShipmentTask | null>(overrides.currentTask ?? null)
  const lastExcelAnalysisContext = ref<Record<string, unknown> | null>(
    overrides.lastExcelAnalysisContext ?? null,
  )
  const linkedExcelSheet = ref<LinkedExcelSheet | null>(overrides.linkedExcelSheet ?? null)
  const linkedExcelAllSheets = ref<boolean>(overrides.linkedExcelAllSheets ?? false)

  const loadMessages = vi.fn()
  const clearMessages = vi.fn()
  const persistTaskPanelStateForSession = vi.fn()
  const applyPersistedTaskPanelStateForSession = vi.fn()
  const clearPersistedTaskPanelState = vi.fn()
  const generateSessionId = vi.fn(() => 'generated-new-sid')
  const normalizeServerContentToHtml = vi.fn(
    (raw: unknown) => `<p>${String(raw ?? '')}</p>`,
  )

  return {
    deps: {
      sessionId,
      taskList,
      activeTaskId,
      expandedTaskIds,
      taskFilter,
      currentTask,
      lastExcelAnalysisContext,
      linkedExcelSheet,
      linkedExcelAllSheets,
      loadMessages,
      clearMessages,
      persistTaskPanelStateForSession,
      applyPersistedTaskPanelStateForSession,
      clearPersistedTaskPanelState,
      generateSessionId,
      normalizeServerContentToHtml,
    },
    refs: {
      sessionId,
      taskList,
      activeTaskId,
      expandedTaskIds,
      taskFilter,
      currentTask,
      lastExcelAnalysisContext,
      linkedExcelSheet,
      linkedExcelAllSheets,
    },
    mocks: {
      loadMessages,
      clearMessages,
      persistTaskPanelStateForSession,
      applyPersistedTaskPanelStateForSession,
      clearPersistedTaskPanelState,
      generateSessionId,
      normalizeServerContentToHtml,
    },
  }
}

describe('useChatSessionHistory — coverage ramp', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    sessionStorage.clear()
    activeModIdRef.value = ''
    vi.clearAllMocks()
    chatApiMock.getConversations.mockReset()
    chatApiMock.getConversation.mockReset()
    chatApiMock.clearConversations.mockReset()
    writeAiSessionIdToStorageMock.mockReset()
    // 默认 window.confirm 返回 true
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    // 默认 console.error 静音
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  // -----------------------------------------------------------------------
  // showHistoryPanel
  // -----------------------------------------------------------------------
  describe('showHistoryPanel', () => {
    it('loads server sessions successfully and merges with local', async () => {
      chatApiMock.getConversations.mockResolvedValue({
        success: true,
        sessions: [
          { session_id: 'srv1', title: 'Server 1', last_message_at: '2026-06-01' },
        ],
      })
      const { deps } = makeDeps()
      const { showHistoryPanel, showHistory, historySessions, historyLoading, historyError } =
        useChatSessionHistory(deps)

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
      const { showHistoryPanel, historySessions } = useChatSessionHistory(deps)
      await showHistoryPanel()
      expect(historySessions.value.find((s) => s.session_id === 'd1')).toBeDefined()
    })

    it('uses data.conversations when sessions and data absent', async () => {
      chatApiMock.getConversations.mockResolvedValue({
        success: true,
        conversations: [{ session_id: 'c1', title: 'C1' }],
      })
      const { deps } = makeDeps()
      const { showHistoryPanel, historySessions } = useChatSessionHistory(deps)
      await showHistoryPanel()
      expect(historySessions.value.find((s) => s.session_id === 'c1')).toBeDefined()
    })

    it('throws and falls back to local when data.success is false', async () => {
      chatApiMock.getConversations.mockResolvedValue({
        success: false,
        message: '权限不足',
      })
      const { deps } = makeDeps()
      const { showHistoryPanel, historySessions, historyError } = useChatSessionHistory(deps)
      await showHistoryPanel()
      // No local sessions either → error message surfaces
      expect(historySessions.value).toEqual([])
      expect(historyError.value).toBe('权限不足')
    })

    it('falls back to local sessions when API throws', async () => {
      // Provide a local session
      localStorage.setItem(
        'xcagi_chat_messages_local1',
        JSON.stringify([{ role: 'user', content: 'local msg' }]),
      )
      chatApiMock.getConversations.mockRejectedValue(new Error('Network error'))
      const { deps } = makeDeps()
      const { showHistoryPanel, historySessions, historyError } = useChatSessionHistory(deps)
      await showHistoryPanel()
      expect(historySessions.value.length).toBe(1)
      expect(historyError.value).toBe('') // local fallback exists, error suppressed
    })

    it('shows error message when API throws and no local fallback', async () => {
      chatApiMock.getConversations.mockRejectedValue(new Error('Network error'))
      const { deps } = makeDeps()
      const { showHistoryPanel, historySessions, historyError } = useChatSessionHistory(deps)
      await showHistoryPanel()
      expect(historySessions.value).toEqual([])
      expect(historyError.value).toBe('Network error')
    })

    it('shows generic error when API throws non-Error', async () => {
      chatApiMock.getConversations.mockRejectedValue('string error')
      const { deps } = makeDeps()
      const { showHistoryPanel, historyError } = useChatSessionHistory(deps)
      await showHistoryPanel()
      expect(historyError.value).toBe('加载历史失败，请稍后重试')
    })

    it('does nothing when already loading', async () => {
      chatApiMock.getConversations.mockImplementation(
        () => new Promise(() => {}), // never resolves
      )
      const { deps } = makeDeps()
      const { showHistoryPanel, historyLoading } = useChatSessionHistory(deps)
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
      const { showHistoryPanel, historyError } = useChatSessionHistory(deps)
      await showHistoryPanel()
      expect(historyError.value).toBe('加载历史失败')
    })
  })

  // -----------------------------------------------------------------------
  // loadSession
  // -----------------------------------------------------------------------
  describe('loadSession', () => {
    it('does nothing when targetSessionId is empty', async () => {
      const { deps } = makeDeps()
      const { loadSession, historyLoading } = useChatSessionHistory(deps)
      await loadSession('')
      expect(historyLoading.value).toBe(false)
      expect(chatApiMock.getConversation).not.toHaveBeenCalled()
    })

    it('does nothing when already loading', async () => {
      chatApiMock.getConversation.mockImplementation(
        () => new Promise(() => {}),
      )
      const { deps } = makeDeps()
      const { loadSession, historyLoading } = useChatSessionHistory(deps)
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
      const { loadSession, showHistory } = useChatSessionHistory(deps)
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

    it('normalizes role to ai when not user/task', async () => {
      chatApiMock.getConversation.mockResolvedValue({
        success: true,
        messages: [{ role: 'assistant', content: 'reply' }],
      })
      const { deps, mocks } = makeDeps()
      const { loadSession } = useChatSessionHistory(deps)
      await loadSession('s1')
      const loaded = mocks.loadMessages.mock.calls[0][0] as ChatMessage[]
      expect(loaded[0].role).toBe('ai')
    })

    it('uses normalizeServerContentToHtml for content', async () => {
      chatApiMock.getConversation.mockResolvedValue({
        success: true,
        messages: [{ role: 'ai', content: 'raw text' }],
      })
      const { deps, mocks } = makeDeps()
      const { loadSession } = useChatSessionHistory(deps)
      await loadSession('s1')
      expect(mocks.normalizeServerContentToHtml).toHaveBeenCalledWith('raw text')
    })

    it('falls back to local messages when server success but no server messages', async () => {
      localStorage.setItem(
        'xcagi_chat_messages_local-sid',
        JSON.stringify([{ role: 'user', content: 'local msg' }]),
      )
      chatApiMock.getConversation.mockResolvedValue({
        success: true,
        messages: [],
      })
      const { deps, mocks } = makeDeps()
      const { loadSession, showHistory } = useChatSessionHistory(deps)
      showHistory.value = true
      await loadSession('local-sid')
      expect(mocks.loadMessages).toHaveBeenCalled()
      const loaded = mocks.loadMessages.mock.calls[0][0] as ChatMessage[]
      expect(loaded[0].content).toBe('<p>local msg</p>')
      expect(showHistory.value).toBe(false)
    })

    it('loads placeholder when server success, no messages, no local', async () => {
      chatApiMock.getConversation.mockResolvedValue({
        success: true,
        messages: [],
      })
      const { deps, mocks } = makeDeps()
      const { loadSession, showHistory } = useChatSessionHistory(deps)
      showHistory.value = true
      await loadSession('empty-sid')
      expect(mocks.loadMessages).toHaveBeenCalled()
      const loaded = mocks.loadMessages.mock.calls[0][0] as ChatMessage[]
      expect(loaded[0].role).toBe('ai')
      expect(String(loaded[0].content)).toContain('该会话暂无消息记录')
      expect(showHistory.value).toBe(false)
    })

    it('throws and falls back to local messages when server fails', async () => {
      localStorage.setItem(
        'xcagi_chat_messages_local-sid',
        JSON.stringify([{ role: 'user', content: 'local fallback' }]),
      )
      chatApiMock.getConversation.mockResolvedValue({
        success: false,
        message: '会话不存在',
      })
      const { deps, mocks, refs } = makeDeps()
      const { loadSession, showHistory, historyError } = useChatSessionHistory(deps)
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
      const { loadSession, historyError } = useChatSessionHistory(deps)
      await loadSession('bad-sid')
      expect(historyError.value).toBe('会话不存在')
      expect(refs.sessionId.value).toBe('original-sid')
      expect(writeAiSessionIdToStorageMock).toHaveBeenCalledWith('original-sid')
      expect(deps.applyPersistedTaskPanelStateForSession).toHaveBeenCalledWith('original-sid')
    })

    it('rolls back when API throws and no local fallback', async () => {
      chatApiMock.getConversation.mockRejectedValue(new Error('Network down'))
      const { deps, refs } = makeDeps({ sessionId: 'original-sid' })
      const { loadSession, historyError } = useChatSessionHistory(deps)
      await loadSession('bad-sid')
      expect(historyError.value).toBe('Network down')
      expect(refs.sessionId.value).toBe('original-sid')
    })

    it('shows generic error when API throws non-Error and no local fallback', async () => {
      chatApiMock.getConversation.mockRejectedValue('string error')
      const { deps } = makeDeps()
      const { loadSession, historyError } = useChatSessionHistory(deps)
      await loadSession('bad-sid')
      expect(historyError.value).toBe('加载会话失败，请稍后重试')
    })

    it('uses default message when server fails without message field', async () => {
      chatApiMock.getConversation.mockResolvedValue({ success: false })
      const { deps } = makeDeps()
      const { loadSession, historyError } = useChatSessionHistory(deps)
      await loadSession('bad-sid')
      expect(historyError.value).toBe('加载会话失败')
    })

    it('persists previous session panel state before switching', async () => {
      chatApiMock.getConversation.mockResolvedValue({ success: true, messages: [] })
      const { deps, mocks } = makeDeps({ sessionId: 'prev-sid' })
      const { loadSession } = useChatSessionHistory(deps)
      await loadSession('new-sid')
      expect(mocks.persistTaskPanelStateForSession).toHaveBeenCalledWith('prev-sid')
    })

    it('uses "default" when previous sessionId is empty', async () => {
      chatApiMock.getConversation.mockResolvedValue({ success: true, messages: [] })
      const { deps, mocks } = makeDeps({ sessionId: '' })
      const { loadSession } = useChatSessionHistory(deps)
      await loadSession('new-sid')
      expect(mocks.persistTaskPanelStateForSession).toHaveBeenCalledWith('default')
    })

    it('sets historyLoading to false in finally block', async () => {
      chatApiMock.getConversation.mockRejectedValue(new Error('boom'))
      const { deps } = makeDeps()
      const { loadSession, historyLoading } = useChatSessionHistory(deps)
      await loadSession('bad-sid')
      expect(historyLoading.value).toBe(false)
    })
  })

  // -----------------------------------------------------------------------
  // clearHistorySessions
  // -----------------------------------------------------------------------
  describe('clearHistorySessions', () => {
    it('does nothing when user cancels confirm', async () => {
      vi.spyOn(window, 'confirm').mockReturnValue(false)
      const { deps } = makeDeps()
      const { clearHistorySessions, historyLoading } = useChatSessionHistory(deps)
      await clearHistorySessions()
      expect(historyLoading.value).toBe(false)
      expect(chatApiMock.clearConversations).not.toHaveBeenCalled()
    })

    it('does nothing when already loading', async () => {
      vi.spyOn(window, 'confirm').mockReturnValue(false)
      const { deps } = makeDeps()
      const api = useChatSessionHistory(deps)
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
      localStorage.setItem(
        'xcagi_chat_messages_s1',
        JSON.stringify([{ role: 'user', content: 'msg' }]),
      )
      chatApiMock.clearConversations.mockResolvedValue({ success: true, deleted: 5 })
      const { deps } = makeDeps()
      const { clearHistorySessions, historyLoading, historyError, historySessions } =
        useChatSessionHistory(deps)
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
      const { clearHistorySessions, historyError } = useChatSessionHistory(deps)
      await clearHistorySessions()
      expect(historyError.value).toBe('清空失败原因')
    })

    it('uses default message when server returns success=false without message', async () => {
      chatApiMock.clearConversations.mockResolvedValue({ success: false })
      const { deps } = makeDeps()
      const { clearHistorySessions, historyError } = useChatSessionHistory(deps)
      await clearHistorySessions()
      expect(historyError.value).toBe('清空历史失败')
    })

    it('shows error when API throws', async () => {
      chatApiMock.clearConversations.mockRejectedValue(new Error('Server down'))
      const { deps } = makeDeps()
      const { clearHistorySessions, historyError } = useChatSessionHistory(deps)
      await clearHistorySessions()
      expect(historyError.value).toBe('Server down')
    })

    it('shows generic error when API throws non-Error', async () => {
      chatApiMock.clearConversations.mockRejectedValue('string error')
      const { deps } = makeDeps()
      const { clearHistorySessions, historyError } = useChatSessionHistory(deps)
      await clearHistorySessions()
      expect(historyError.value).toBe('清空历史失败，请稍后重试')
    })

    it('sets historyLoading to false in finally block', async () => {
      chatApiMock.clearConversations.mockRejectedValue(new Error('boom'))
      const { deps } = makeDeps()
      const { clearHistorySessions, historyLoading } = useChatSessionHistory(deps)
      await clearHistorySessions()
      expect(historyLoading.value).toBe(false)
    })

    it('passes user_id default to clearConversations', async () => {
      chatApiMock.clearConversations.mockResolvedValue({ success: true })
      const { deps } = makeDeps()
      const { clearHistorySessions } = useChatSessionHistory(deps)
      await clearHistorySessions()
      expect(chatApiMock.clearConversations).toHaveBeenCalledWith({ user_id: 'default' })
    })
  })

  // -----------------------------------------------------------------------
  // newConversation
  // -----------------------------------------------------------------------
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

      const { newConversation } = useChatSessionHistory(deps)
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
      const { newConversation } = useChatSessionHistory(deps)
      newConversation()
      expect(mocks.persistTaskPanelStateForSession).toHaveBeenCalledWith('default')
    })

    it('uses generated sessionId from generateSessionId dep', () => {
      const customGen = vi.fn(() => 'custom-new-id')
      const { deps, refs } = makeDeps()
      deps.generateSessionId = customGen
      const { newConversation } = useChatSessionHistory(deps)
      newConversation()
      expect(refs.sessionId.value).toBe('custom-new-id')
      expect(customGen).toHaveBeenCalled()
    })
  })

  // -----------------------------------------------------------------------
  // registerHistoryModWatch
  // -----------------------------------------------------------------------
  describe('registerHistoryModWatch', () => {
    it('refreshes history panel when mod changes and panel is open', async () => {
      chatApiMock.getConversations.mockResolvedValue({ success: true, sessions: [] })
      const { deps } = makeDeps()
      const api = useChatSessionHistory(deps)
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
      const api = useChatSessionHistory(deps)
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
      const api = useChatSessionHistory(deps)
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
      const api = useChatSessionHistory(deps)
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

  // -----------------------------------------------------------------------
  // 返回值结构
  // -----------------------------------------------------------------------
  describe('return shape', () => {
    it('exposes all expected fields', () => {
      const { deps } = makeDeps()
      const result = useChatSessionHistory(deps)
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
      const { showHistory, historySessions, historyLoading, historyError } =
        useChatSessionHistory(deps)
      expect(showHistory.value).toBe(false)
      expect(historySessions.value).toEqual([])
      expect(historyLoading.value).toBe(false)
      expect(historyError.value).toBe('')
    })
  })
})
