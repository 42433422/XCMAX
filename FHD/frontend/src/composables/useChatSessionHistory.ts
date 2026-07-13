import { ref, watch, type Ref } from 'vue'
import { useModsStore } from '@/stores/mods'
import { writeAiSessionIdToStorage } from '@/utils/xcagiStorageKeys'
import chatApi from '../api/chat'
import {
  CHAT_TASK_PANEL_STORAGE_PREFIX,
  useChatHistoryPersistence,
  type LinkedExcelSheet,
  type TaskItem,
} from './useChatPersistence'
import type { ShipmentTask } from './useShipmentTask'
import { mergeChatMessageSidecars, type ChatMessage } from './useChatMessages'
import { asRecord, asArray, asString } from '@/utils/typeGuards'
import { formatChatMessageTime } from '@/utils/chatTaskLabels'

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
  activateSessionContext: (sid: string) => void
  clearSessionContext: (sid: string, clearPersistedExcel?: boolean) => void
  clearAllSessionContexts: () => void
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
    activateSessionContext,
    clearSessionContext,
    clearAllSessionContexts,
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

  function clearAllPersistedTaskPanelStates(): void {
    if (typeof sessionStorage === 'undefined') return
    const removeKeys: string[] = []
    for (let i = 0; i < sessionStorage.length; i += 1) {
      const key = String(sessionStorage.key(i) || '')
      if (key.startsWith(CHAT_TASK_PANEL_STORAGE_PREFIX)) removeKeys.push(key)
    }
    removeKeys.forEach((key) => sessionStorage.removeItem(key))
  }

  function resetActiveConversation(nextSessionId: string): void {
    sessionId.value = nextSessionId
    writeAiSessionIdToStorage(nextSessionId)
    taskList.value = []
    activeTaskId.value = ''
    expandedTaskIds.value = []
    taskFilter.value = 'all'
    currentTask.value = null
    lastExcelAnalysisContext.value = null
    linkedExcelSheet.value = null
    linkedExcelAllSheets.value = false
    clearPersistedTaskPanelState(nextSessionId)
    clearMessages()
  }

  async function showHistoryPanel() {
    if (historyLoading.value) return
    showHistory.value = true
    historyLoading.value = true
    historyError.value = ''
    try {
      const data = await chatApi.getConversations({ limit: 20 })
      if (!data?.success) throw new Error(String(data?.message || '加载历史失败'))

      const dataRow = asRecord(data)
      const sessionsRaw = asArray(
        dataRow.sessions ?? dataRow.data ?? dataRow.conversations,
      )
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
    activateSessionContext(sid)

    try {
      const data = await chatApi.getConversation(sid)
      if (String(sessionId.value || '').trim() !== sid) return
      const dataRow = asRecord(data)
      const serverMessages = asArray(dataRow.messages)
      const localMessages = readLocalMessagesBySession(sid)
      if (data.success && serverMessages.length > 0) {
        const mappedServerMessages = serverMessages.map((msg: unknown) => {
          const row = asRecord(msg)
          const roleRaw = asString(row.role)
          return {
            role: roleRaw === 'user' || roleRaw === 'task' ? roleRaw : 'ai',
            content: normalizeServerContentToHtml(asString(row.content)),
            time: formatChatMessageTime(
              row.time ?? row.timestamp ?? row.created_at ?? row.createdAt ?? row.updated_at,
            ),
          }
        }) as ChatMessage[]
        loadMessages(mergeChatMessageSidecars(mappedServerMessages, localMessages))
      } else if (localMessages.length > 0) {
        // 本地缓存已经过 UI 消息白名单清洗，直接加载可保留审批、下载和轨迹卡片。
        loadMessages(localMessages)
      } else if (data.success) {
        loadMessages([{
          role: 'ai',
          content: '该会话暂无消息记录。',
          time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
        }])
      } else {
        throw new Error(asString((data as { message?: unknown }).message, '加载会话失败'))
      }
      showHistory.value = false
    } catch (e) {
      if (String(sessionId.value || '').trim() !== sid) return
      const localMessages = readLocalMessagesBySession(sid)
      if (localMessages.length > 0) {
        loadMessages(localMessages)
        historyError.value = ''
        showHistory.value = false
      } else {
        historyError.value = e instanceof Error ? e.message : '加载会话失败，请稍后重试'
        sessionId.value = previousSessionId
        writeAiSessionIdToStorage(previousSessionId)
        applyPersistedTaskPanelStateForSession(previousSessionId || 'default')
        activateSessionContext(previousSessionId || 'default')
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
      const data = await chatApi.clearConversations({ user_id: 'default' })
      if (!data?.success) throw new Error(asString((data as { message?: unknown }).message, '清空历史失败'))
      clearLocalHistoryCache()
      clearAllPersistedTaskPanelStates()
      clearAllSessionContexts()
      const nextSessionId = generateSessionId()
      resetActiveConversation(nextSessionId)
      clearSessionContext(nextSessionId, true)
      persistTaskPanelStateForSession(nextSessionId)
      historySessions.value = []
      showHistory.value = false
    } catch (e) {
      historyError.value = e instanceof Error ? e.message : '清空历史失败，请稍后重试'
      console.error('清空历史失败:', e)
    } finally {
      historyLoading.value = false
    }
  }

  function newConversation() {
    const prev = String(sessionId.value || '').trim() || 'default'
    persistTaskPanelStateForSession(prev)
    const nextSessionId = generateSessionId()
    resetActiveConversation(nextSessionId)
    clearSessionContext(nextSessionId, true)
    persistTaskPanelStateForSession(nextSessionId)
    historyError.value = ''
    showHistory.value = false
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
