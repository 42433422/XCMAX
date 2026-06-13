import { ref, watch, type Ref } from 'vue'
import { useModsStore } from '@/stores/mods'
import { writeAiSessionIdToStorage } from '@/utils/xcagiStorageKeys'
import chatApi from '../api/chat'
import {
  persistExcelAnalysisContext,
  useChatHistoryPersistence,
  type LinkedExcelSheet,
  type TaskItem,
} from './useChatPersistence'
import type { ShipmentTask } from './useShipmentTask'
import type { ChatMessage } from './useChatMessages'

export interface UseChatSessionHistoryDeps {
  sessionId: Ref<string>
  taskList: Ref<TaskItem[]>
  activeTaskId: Ref<string>
  expandedTaskIds: Ref<string[]>
  taskFilter: Ref<'all' | 'running' | 'success' | 'failed'>
  currentTask: Ref<ShipmentTask | null>
  lastExcelAnalysisContext: Ref<Record<string, unknown> | null>
  linkedExcelSheet: Ref<LinkedExcelSheet | null>
  linkedExcelAllSheets: Ref<boolean>
  loadMessages: (msgs: ChatMessage[]) => void
  clearMessages: () => void
  persistTaskPanelStateForSession: (targetSessionId?: string) => void
  applyPersistedTaskPanelStateForSession: (sid: string) => void
  clearPersistedTaskPanelState: (sid: string) => void
  generateSessionId: () => string
  normalizeServerContentToHtml: (raw: unknown) => string
}

export type HistorySessionItem = {
  session_id: string
  title?: string
  message_count?: number
  last_message_at?: string
  is_local_only?: boolean
}

export function useChatSessionHistory(deps: UseChatSessionHistoryDeps) {
  const modsStore = useModsStore()
  const {
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
  } = deps

  const historyPersistence = useChatHistoryPersistence({
    sessionId,
    getActiveModId: () => String(modsStore.activeModId || ''),
  })
  const {
    mergeHistorySessions,
    clearLocalHistoryCache,
    readLocalMessagesBySession,
  } = historyPersistence

  const showHistory = ref(false)
  const historySessions = ref<HistorySessionItem[]>([])
  const historyLoading = ref(false)
  const historyError = ref('')

  async function showHistoryPanel() {
    if (historyLoading.value) return
    showHistory.value = true
    historyLoading.value = true
    historyError.value = ''
    try {
      const data = await chatApi.getConversations({ limit: 20 })
      if (!data?.success) throw new Error(String(data?.message || '加载历史失败'))

      const sessionsRaw = Array.isArray((data as unknown)?.sessions)
        ? (data as unknown).sessions
        : Array.isArray((data as unknown)?.data)
          ? (data as unknown).data
          : Array.isArray((data as unknown)?.conversations)
            ? (data as unknown).conversations
            : []
      historySessions.value = mergeHistorySessions(sessionsRaw) as HistorySessionItem[]
    } catch (e) {
      const localFallback = mergeHistorySessions([]) as HistorySessionItem[]
      historySessions.value = localFallback
      historyError.value = localFallback.length ? '' : (e instanceof Error ? e.message : '加载历史失败，请稍后重试')
      console.error('加载历史失败:', e)
    } finally {
      historyLoading.value = false
    }
  }

  async function loadSession(targetSessionId: string) {
    const sid = String(targetSessionId || '').trim()
    if (!sid || historyLoading.value) return

    const previousSessionId = String(sessionId.value || '').trim()
    persistTaskPanelStateForSession(previousSessionId || 'default')
    historyError.value = ''
    historyLoading.value = true
    sessionId.value = sid
    writeAiSessionIdToStorage(sid)
    applyPersistedTaskPanelStateForSession(sid)

    try {
      const data = await chatApi.getConversation(sid)
      const serverMessages = Array.isArray((data as unknown)?.messages) ? (data as unknown).messages : []
      const localMessages = readLocalMessagesBySession(sid)
      if (data.success && serverMessages.length > 0) {
        loadMessages(serverMessages.map((msg: unknown) => ({
          role: msg?.role === 'user' || msg?.role === 'task' ? msg.role : 'ai',
          content: normalizeServerContentToHtml(msg.content),
          time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
        })))
      } else if (localMessages.length > 0) {
        loadMessages(localMessages.map((msg) => ({
          role: msg.role === 'user' || msg.role === 'task' ? msg.role : 'ai',
          content: normalizeServerContentToHtml(msg.content),
          time: msg.time || new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
        })))
      } else if (data.success) {
        loadMessages([{
          role: 'ai',
          content: '该会话暂无消息记录。',
          time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
        }])
      } else {
        throw new Error(String((data as unknown)?.message || '加载会话失败'))
      }
      showHistory.value = false
    } catch (e) {
      const localMessages = readLocalMessagesBySession(sid)
      if (localMessages.length > 0) {
        loadMessages(localMessages.map((msg) => ({
          role: msg.role === 'user' || msg.role === 'task' ? msg.role : 'ai',
          content: normalizeServerContentToHtml(msg.content),
          time: msg.time || new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
        })))
        historyError.value = ''
        showHistory.value = false
      } else {
        historyError.value = e instanceof Error ? e.message : '加载会话失败，请稍后重试'
        sessionId.value = previousSessionId
        writeAiSessionIdToStorage(previousSessionId)
        applyPersistedTaskPanelStateForSession(previousSessionId || 'default')
        console.error('加载会话失败:', e)
      }
    } finally {
      historyLoading.value = false
    }
  }

  async function clearHistorySessions() {
    if (historyLoading.value) return
    const confirmed = window.confirm('确认清空所有历史对话吗？此操作不可撤销。')
    if (!confirmed) return

    historyLoading.value = true
    historyError.value = ''
    try {
      clearLocalHistoryCache()
      const data = await chatApi.clearConversations({ user_id: 'default' })
      if (!data?.success) throw new Error(String((data as unknown)?.message || '清空历史失败'))
      historySessions.value = mergeHistorySessions([]) as HistorySessionItem[]
    } catch (e) {
      historySessions.value = mergeHistorySessions([]) as HistorySessionItem[]
      historyError.value = e instanceof Error ? e.message : '清空历史失败，请稍后重试'
      console.error('清空历史失败:', e)
    } finally {
      historyLoading.value = false
    }
  }

  function newConversation() {
    const prev = String(sessionId.value || '').trim() || 'default'
    persistTaskPanelStateForSession(prev)
    persistExcelAnalysisContext(prev, null)
    lastExcelAnalysisContext.value = null
    linkedExcelSheet.value = null
    linkedExcelAllSheets.value = false
    sessionId.value = generateSessionId()
    writeAiSessionIdToStorage(sessionId.value)
    taskList.value = []
    activeTaskId.value = ''
    expandedTaskIds.value = []
    taskFilter.value = 'all'
    currentTask.value = null
    clearPersistedTaskPanelState(sessionId.value)
    persistTaskPanelStateForSession(sessionId.value)
    clearMessages()
  }

  function registerHistoryModWatch(showHistoryPanelFn: () => Promise<void>) {
    watch(
      () => String(modsStore.activeModId || ''),
      () => {
        historyError.value = ''
        if (showHistory.value) {
          void showHistoryPanelFn()
        } else if (historySessions.value.length) {
          historySessions.value = mergeHistorySessions([]) as HistorySessionItem[]
        }
      },
    )
  }

  return {
    showHistory,
    historySessions,
    historyLoading,
    historyError,
    showHistoryPanel,
    loadSession,
    clearHistorySessions,
    newConversation,
    registerHistoryModWatch,
  }
}
