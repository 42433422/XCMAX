import { getCurrentScope, onScopeDispose, ref, watch, type Ref } from 'vue'
import { useModsStore } from '@/stores/mods'
import chatApi from '../api/chat'
import {
  useChatHistoryPersistence,
  type LinkedExcelSheet,
  type TaskItem,
  type TaskFilter,
} from './useChatPersistence'
import type { ShipmentTask } from './useShipmentTask'
import { chatMessageExtrasFromServerRow, type ChatMessage } from './useChatMessages'
import { asRecord, asArray, asString } from '@/utils/typeGuards'
import { formatChatMessageTime } from '@/utils/chatTaskLabels'
import { resolveChatStorageScope, writeAiSessionIdToStorage } from '@/utils/chatStorageKeys'

export interface UseChatSessionHistoryDeps {
  sessionId: Ref<string>
  taskList: Ref<TaskItem[]>
  activeTaskId: Ref<string>
  expandedTaskIds: Ref<string[]>
  taskFilter: Ref<TaskFilter>
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
  onIdentityChange?: () => void
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
  const { mergeHistorySessions, clearLocalHistoryCache, removeLocalSessionCache, readLocalMessagesBySession } = historyPersistence

  const showHistory = ref(false)
  const historySessions = ref<HistorySessionItem[]>([])
  const historyLoading = ref(false)
  const historyError = ref('')
  let requestEpoch = 0
  if (getCurrentScope()) onScopeDispose(() => { requestEpoch += 1 })

  function captureRequest() {
    const epoch = ++requestEpoch
    const modId = String(modsStore.activeModId || '')
    const tenant = resolveChatStorageScope()
    return {
      epoch,
      isCurrent: () => epoch === requestEpoch && modId === String(modsStore.activeModId || '')
        && tenant === resolveChatStorageScope(),
    }
  }

  function finishRequest(epoch: number) {
    if (epoch === requestEpoch) historyLoading.value = false
  }

  const normalizeLocalMessages = (messages: ChatMessage[]): ChatMessage[] => messages.map((msg) => {
    const row = asRecord(msg)
    const roleRaw = asString(row.role || (msg as { role?: string }).role)
    return {
      role: roleRaw === 'user' || roleRaw === 'task' ? roleRaw : 'ai',
      // 本地缓存已可展示，不要再次 HTML 转义。
      content: asString(row.content || (msg as { content?: string }).content),
      time: formatChatMessageTime(row.time ?? row.timestamp ?? row.created_at),
      ...chatMessageExtrasFromServerRow({ ui_payload: row }),
    }
  })

  async function refreshHistorySessions() {
    if (historyLoading.value) return
    const request = captureRequest()
    historyLoading.value = true
    historyError.value = ''
    try {
      const data = await chatApi.getConversations({ limit: 20 })
      if (!request.isCurrent()) return
      if (!data?.success) throw new Error(String(data?.message || '加载历史失败'))

      const dataRow = asRecord(data)
      const sessionsRaw = asArray(dataRow.sessions ?? dataRow.data ?? dataRow.conversations)
      historySessions.value = mergeHistorySessions(sessionsRaw) as HistorySessionItem[]
    } catch (e) {
      if (!request.isCurrent()) return
      const localFallback = mergeHistorySessions([]) as HistorySessionItem[]
      historySessions.value = localFallback
      historyError.value = localFallback.length ? '' : e instanceof Error ? e.message : '加载历史失败，请稍后重试'
      console.error('加载历史失败:', e)
    } finally {
      finishRequest(request.epoch)
    }
  }

  async function showHistoryPanel() {
    showHistory.value = true
    await refreshHistorySessions()
  }

  async function loadSession(targetSessionId: string) {
    const sid = String(targetSessionId || '').trim()
    if (!sid || historyLoading.value) return
    const request = captureRequest()

    const previousSessionId = String(sessionId.value || '').trim()
    persistTaskPanelStateForSession(previousSessionId || 'default')
    historyError.value = ''
    historyLoading.value = true
    sessionId.value = sid
    writeAiSessionIdToStorage(sid)
    applyPersistedTaskPanelStateForSession(sid)

    try {
      const data = await chatApi.getConversation(sid)
      if (!request.isCurrent() || sessionId.value !== sid) return
      const dataRow = asRecord(data)
      const serverMessages = asArray(dataRow.messages)
      const localMessages = readLocalMessagesBySession(sid)
      if (data.success && serverMessages.length > 0) {
        const merged = [...localMessages]
        const matched = new Set<number>()
        for (const message of serverMessages.map((msg: unknown): ChatMessage => {
          const row = asRecord(msg)
          const roleRaw = asString(row.role)
          return {
            role: roleRaw === 'user' || roleRaw === 'task' ? roleRaw : 'ai',
            content: normalizeServerContentToHtml(asString(row.content)),
            time: formatChatMessageTime(row.time ?? row.timestamp ?? row.created_at ?? row.createdAt ?? row.updated_at),
            ...chatMessageExtrasFromServerRow(row),
          }
        })) {
          const index = localMessages.findIndex((local, i) => !matched.has(i)
            && local.role === message.role && local.time === message.time
            && historyPersistence.toPlainText(local.content) === historyPersistence.toPlainText(message.content))
          if (index < 0) merged.push(message)
          else {
            matched.add(index)
            merged[index] = { ...merged[index], ...message }
          }
        }
        loadMessages(merged)
      } else if (localMessages.length > 0) {
        loadMessages(
          normalizeLocalMessages(localMessages)
        )
      } else if (data.success) {
        loadMessages([
          {
            role: 'ai',
            content: '该会话暂无消息记录。',
            time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
          },
        ])
      } else {
        throw new Error(asString((data as { message?: unknown }).message, '加载会话失败'))
      }
      showHistory.value = false
    } catch (e) {
      if (!request.isCurrent() || sessionId.value !== sid) return
      const localMessages = readLocalMessagesBySession(sid)
      if (localMessages.length > 0) {
        loadMessages(
          normalizeLocalMessages(localMessages)
        )
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
      finishRequest(request.epoch)
    }
  }

  async function clearHistorySessions() {
    if (historyLoading.value) return
    const confirmed = window.confirm('确认清空所有历史对话吗？此操作不可撤销。')
    if (!confirmed) return
    const request = captureRequest()

    historyLoading.value = true
    historyError.value = ''
    let remoteCleared = false
    try {
      const data = await chatApi.clearConversations({ user_id: 'default' })
      if (!request.isCurrent()) return
      if (!data?.success) throw new Error(asString((data as { message?: unknown }).message, '清空历史失败'))
      remoteCleared = true
      clearLocalHistoryCache()
      historySessions.value = mergeHistorySessions([]) as HistorySessionItem[]
    } catch (e) {
      if (!request.isCurrent()) return
      if (remoteCleared) historySessions.value = mergeHistorySessions([]) as HistorySessionItem[]
      historyError.value = remoteCleared
        ? '服务端历史已清空，本机缓存清理未完成，请重试。'
        : e instanceof Error ? e.message : '清空历史失败，本机记录已保留，请稍后重试'
      console.error('清空历史失败:', e)
    } finally {
      finishRequest(request.epoch)
    }
  }

  async function renameSession(targetSessionId: string, title: string): Promise<boolean> {
    const sid = String(targetSessionId || '').trim()
    const next = String(title || '').trim()
    if (!sid || !next || historyLoading.value) return false
    const request = captureRequest()
    historyError.value = ''
    try {
      const data = await chatApi.renameConversation(sid, next)
      if (!request.isCurrent()) return false
      if (!data?.success) throw new Error(asString((data as { message?: unknown }).message, '重命名失败'))
      historySessions.value = historySessions.value.map((s) =>
        s.session_id === sid ? { ...s, title: next } : s,
      )
      return true
    } catch (e) {
      if (!request.isCurrent()) return false
      historyError.value = e instanceof Error ? e.message : '重命名失败，请稍后重试'
      console.error('重命名会话失败:', e)
      return false
    }
  }

  async function deleteSession(targetSessionId: string): Promise<boolean> {
    const sid = String(targetSessionId || '').trim()
    if (!sid || historyLoading.value) return false
    const request = captureRequest()
    historyError.value = ''
    try {
      const data = await chatApi.deleteConversation(sid)
      if (!request.isCurrent()) return false
      if (!data?.success) throw new Error(asString((data as { message?: unknown }).message, '删除会话失败'))
      removeLocalSessionCache(sid)
      historySessions.value = historySessions.value.filter((s) => s.session_id !== sid)
      if (sid === String(sessionId.value || '').trim()) {
        newConversation()
      }
      return true
    } catch (e) {
      if (!request.isCurrent()) return false
      historyError.value = e instanceof Error ? e.message : '删除会话失败，请稍后重试'
      console.error('删除会话失败:', e)
      return false
    }
  }

  function resetConversationView() {
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
    clearMessages()
  }

  function newConversation() {
    requestEpoch += 1
    historyLoading.value = false
    const prev = String(sessionId.value || '').trim() || 'default'
    persistTaskPanelStateForSession(prev)
    resetConversationView()
    clearPersistedTaskPanelState(sessionId.value)
    persistTaskPanelStateForSession(sessionId.value)
  }

  function registerHistoryModWatch(showHistoryPanelFn: () => Promise<void>) {
    watch(
      () => JSON.stringify([String(modsStore.activeModId || ''), resolveChatStorageScope()]),
      () => {
        requestEpoch += 1
        deps.onIdentityChange?.()
        historyLoading.value = false
        historyError.value = ''
        resetConversationView()
        historySessions.value = mergeHistorySessions([]) as HistorySessionItem[]
        if (showHistory.value) {
          void showHistoryPanelFn()
        }
      },
    )
  }

  return {
    showHistory,
    historySessions,
    historyLoading,
    historyError,
    refreshHistorySessions,
    showHistoryPanel,
    loadSession,
    clearHistorySessions,
    renameSession,
    deleteSession,
    newConversation,
    registerHistoryModWatch,
  }
}
