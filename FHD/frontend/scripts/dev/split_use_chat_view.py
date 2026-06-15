#!/usr/bin/env python3
"""One-shot splitter: useChatView.ts.bak -> composables + facade (Phase 7)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMP = ROOT / "src/composables"
BAK = COMP / "useChatView.ts.bak"

# 1-based inclusive line ranges to EXTRACT (removed from orchestration body)
EXTRACT_RANGES: list[tuple[int, int]] = [
    (361, 1547),   # workflow panel + task-panel watchers
    (1549, 1631),  # db token gate
    (1646, 1716),  # excel context part 1 (after resolve fn)
    (1718, 1922),  # request
    (1924, 1965),  # mount/unmount hooks (replaced by composables)
    (2608, 2752),  # response attach
    (3160, 3285),  # session history
    (3323, 3369),  # excel bind
]

INNER_RANGES: list[tuple[int, int]] = [
    (187, 202),    # shipment + print service
    (211, 309),    # excel analysis hook
    (339, 341),    # task table computed
    (1967, 2606),  # task actions (through handleAutoAction)
    (2754, 3158),  # maybePrefetch + executeRemoteChatRound + sendMessage
    (3287, 3321),  # misc helpers
]


def load_lines() -> list[str]:
    return BAK.read_text(encoding="utf-8").splitlines(keepends=True)


def dedent(block: str, n: int = 2) -> str:
    prefix = " " * n
    out: list[str] = []
    for line in block.splitlines(keepends=True):
        if line.startswith(prefix):
            out.append(line[n:])
        else:
            out.append(line)
    return "".join(out)


def indent_block(block: str, spaces: int = 2) -> str:
    prefix = " " * spaces
    return "".join((prefix + line if line.strip() else line) for line in block.splitlines(keepends=True))


def slice_lines(lines: list[str], start: int, end: int) -> str:
    return "".join(lines[start - 1 : end])


def remove_ranges(lines: list[str], ranges: list[tuple[int, int]]) -> list[str]:
    skip = set()
    for a, b in ranges:
        skip.update(range(a, b + 1))
    return [ln for i, ln in enumerate(lines, start=1) if i not in skip]


def main() -> None:
    lines = load_lines()
    # body: inside useChatView after opening brace (line 81) until return (3371)
    body_start = 81
    body_end = 3370
    body_lines = lines[body_start:body_end]

    # Re-index body-only line numbers: original line L -> body index L - body_start
    def body_slice(start: int, end: int) -> str:
        return dedent("".join(lines[start - 1 : end]))

    workflow_body = indent_block(body_slice(361, 1521))
    watcher_body = body_slice(1523, 1547)
    db_body = indent_block(body_slice(1549, 1631))
    excel_body = indent_block(body_slice(1646, 1716) + "\n" + body_slice(3323, 3369))
    request_body = indent_block(body_slice(1718, 1855) + body_slice(1859, 1922))
    response_body = indent_block(body_slice(2608, 2752))
    session_body = indent_block(body_slice(3160, 3285))

    workflow_footer = WORKFLOW_FOOTER_TEMPLATE.replace(
        "WATCHER_PLACEHOLDER",
        watcher_body.rstrip(),
    )

    # --- useChatWorkflowPanel.ts ---
    (COMP / "useChatWorkflowPanel.ts").write_text(
        WORKFLOW_HEADER + workflow_body + workflow_footer,
        encoding="utf-8",
    )

    (COMP / "useChatDbTokenGate.ts").write_text(
        DB_HEADER + db_body + DB_FOOTER,
        encoding="utf-8",
    )

    (COMP / "useChatExcelContext.ts").write_text(
        EXCEL_HEADER + excel_body + EXCEL_FOOTER,
        encoding="utf-8",
    )

    (COMP / "useChatRequest.ts").write_text(
        REQUEST_HEADER + request_body + REQUEST_FOOTER,
        encoding="utf-8",
    )

    (COMP / "useChatResponseAttach.ts").write_text(
        RESPONSE_HEADER + response_body + RESPONSE_FOOTER,
        encoding="utf-8",
    )

    (COMP / "useChatSessionHistory.ts").write_text(
        SESSION_HEADER + session_body + SESSION_FOOTER,
        encoding="utf-8",
    )

    orch_inner = "".join(body_slice(a, b) for a, b in INNER_RANGES)
    orch_inner = "".join(
        ("  " + line if line.strip() else line) for line in orch_inner.splitlines(keepends=True)
    )
    (COMP / "useChatOrchestration.ts").write_text(
        ORCH_HEADER + orch_inner + ORCH_FOOTER,
        encoding="utf-8",
    )

    (COMP / "useChatView.ts").write_text(FACADE, encoding="utf-8")
    print("Generated composables + facade")


WORKFLOW_HEADER = '''import { watch, type Ref } from 'vue'
import { useModsStore } from '@/stores/mods'
import { useWorkflowAiEmployeesStore, workflowAiEmployeesStorageKey } from '@/stores/workflowAiEmployees'
import {
  buildModWorkflowPanelMeta,
  findWorkflowEmployeeEntry,
  resolvePhoneAgentApiBase,
  listPhoneAgentEmployeeIds,
  resolvePhoneChannelForEmployee,
} from '@/utils/modWorkflowEmployees'
import { isCoreWorkflowEmployeeId, isCoreWorkflowModInstalled } from '@/constants/coreWorkflowMod'
import {
  appendCoreWorkflowSummaryParts,
  buildCoreWorkflowMonitorLine,
  buildCoreWorkflowStepsForEmployee,
  computeCoreWorkflowCurrentHint,
  computeCoreWorkflowProgressState,
  computeCoreWorkflowStageLine,
  computeWorkflowProgressFromSteps,
  mergeCorePayloadFromExisting,
  type WorkflowMonitorPayload,
  type WorkflowStepRow,
} from '@/workflow/coreWorkflowMonitor'
import {
  buildLabelPrintHostUpdate,
  buildReceiptFeedbackHostUpdate,
  buildWechatMonitorUpdate,
  dispatchCoreWorkflowModRun,
  runLabelPrintSideEffect,
} from '@/workflow/coreWorkflowDispatcher'
import { formatWorkflowClock } from '@/workflow/coreWorkflowPrefs'
import type { TaskItem } from './useChatPersistence'
import type { ShipmentTask } from './useShipmentTask'

export type PhoneAgentStatusPayload = {
  phone_channel?: 'wechat' | 'adb' | string
  running?: boolean
  window_monitor_available?: boolean
  audio_capture_available?: boolean
  asr_available?: boolean
  intent_handler_available?: boolean
  tts_available?: boolean
  vb_cable_available?: boolean
  vb_cable_playback_device_name?: string | null
  vb_cable_stream_sample_hz?: number | null
  ffmpeg_on_path?: boolean
  mp3_decode_available?: boolean
  remote_hear_tts_hint?: string
  vb_cable_roles_zh?: string
  lastPolledAt?: number
  last_popup_detected_at_ms?: number
  last_popup_source?: string
  last_popup_title?: string
  last_popup_class_name?: string
  last_popup_hwnd?: number | null
  last_popup_w?: number | null
  last_popup_h?: number | null
  last_click_at_ms?: number | null
  last_click_ok?: boolean | null
  last_click_method?: string | null
  last_click_x?: number | null
  last_click_y?: number | null
  last_click_error?: string | null
  last_opening_at_ms?: number | null
  last_opening_ok?: boolean | null
  last_opening_error?: string | null
  last_call_ended_at_ms?: number | null
  last_call_end_reason?: string | null
  last_asr_text?: string | null
  last_asr_at_ms?: number | null
  last_reply_text?: string | null
  last_reply_at_ms?: number | null
  last_pipeline_error?: string | null
  phone_asr_rms_silence_threshold?: number
  phone_asr_rms_speech_hi?: number
  phone_asr_rms_silence_lo?: number
  phone_capture_peak_rms_since_last_poll?: number
  phone_input_devices?: Array<{ index: number; name: string }>
  phone_asr_hint?: string
  phone_capture_backend?: string
  phone_capture_thread_alive?: boolean | null
  phone_capture_problem_zh?: string
  phone_audio_capture_started_ok?: boolean
  phone_whisper_model?: string
  phone_whisper_backend?: string
  phone_whisper_device?: string
  phone_whisper_compute_type?: string
  fetchError?: string
  phone_agent_manager_load_failed?: boolean
  phone_agent_manager_load_message?: string
  phone_agent_get_status_failed?: boolean
  phone_agent_get_status_message?: string
  phone_agent_status_route_failed?: boolean
  phone_agent_status_route_message?: string
  phone_agent_last_start_error?: string | null
  phone_in_call_ui_visible?: boolean
  phone_wechat_call_session_active?: boolean
  phone_agent_voice_session_active?: boolean
  adb_available?: boolean
  adb_device_connected?: boolean
  adb_device_serial?: string | null
  adb_call_state?: string | null
  adb_last_poll_at_ms?: number | null
  adb_last_answer_at_ms?: number | null
  adb_last_answer_ok?: boolean | null
  adb_last_error?: string | null
  phone_pywin32_installed?: boolean
  phone_window_monitor_hint_zh?: string | null
}

export interface UseChatWorkflowPanelDeps {
  taskList: Ref<TaskItem[]>
  activeTaskId: Ref<string>
  expandedTaskIds: Ref<string[]>
  taskFilter: Ref<'all' | 'running' | 'success' | 'failed'>
  currentTask: Ref<ShipmentTask | null>
  upsertTask: (item: Partial<TaskItem> & Pick<TaskItem, 'id' | 'type' | 'source' | 'title' | 'status'>) => void
  sortTaskList: () => void
  createTaskId: (prefix: string) => string
  persistTaskPanelStateForSession: (targetSessionId?: string) => void
  showTaskConfirm: (task: unknown) => void
  emitAssistantPush: (payload?: Record<string, unknown>) => void
  maybeCloseAssistantFloatForShipmentTask: (task: unknown, autoAction: unknown) => void
}

export function useChatWorkflowPanel(deps: UseChatWorkflowPanelDeps) {
  const modsStore = useModsStore()
  const workflowAiEmployeesStore = useWorkflowAiEmployeesStore()
  const {
    taskList,
    activeTaskId,
    expandedTaskIds,
    taskFilter,
    upsertTask,
    sortTaskList,
    createTaskId,
    persistTaskPanelStateForSession,
    showTaskConfirm,
    emitAssistantPush,
    maybeCloseAssistantFloatForShipmentTask,
  } = deps

'''

WORKFLOW_FOOTER_TEMPLATE = '''
  function registerWorkflowPanelWatchers(
    persistTaskPanelStateForSession: (targetSessionId?: string) => void,
    currentTask: { value: ShipmentTask | null },
  ) {
WATCHER_PLACEHOLDER
  }

  function mountWorkflowPanel() {
    window.addEventListener('xcagi:wechat-ai-task-enqueue', onWechatAiTaskEnqueue)
    window.addEventListener('xcagi:wechat-shipment-preview-task', onWechatShipmentPreviewTask)
    window.addEventListener('xcagi:workflow-label-print-signal', onWorkflowLabelPrintSignal)
    window.addEventListener('xcagi:workflow-receipt-feedback-signal', onWorkflowReceiptFeedbackSignal)
    window.addEventListener('xcagi:workflow-ai-employees-changed', onWorkflowAiEmployeesChanged)
    window.addEventListener('storage', onWorkflowEmployeesStorage)
    window.addEventListener('xcagi:auto-refresh-wechat-changed', onStarRefreshOrIntentChangedForWorkflow)
    window.addEventListener('xcagi:pro-intent-experience-changed', onStarRefreshOrIntentChangedForWorkflow)
    window.addEventListener('xcagi:wechat-star-feed-polled', onWechatStarFeedPolled)
    window.addEventListener('focus', onWindowFocusForWorkflowTasks)
    document.addEventListener('visibilitychange', onVisibilityChangeForWorkflowTasks)
    syncWorkflowEmployeePanelTasks(readWorkflowEmployeeEnabledMap())
    window.setTimeout(() => ensureWorkflowEmployeePanelTasksFromStorage(), 120)
  }

  function unmountWorkflowPanel() {
    window.removeEventListener('xcagi:wechat-ai-task-enqueue', onWechatAiTaskEnqueue)
    window.removeEventListener('xcagi:wechat-shipment-preview-task', onWechatShipmentPreviewTask)
    window.removeEventListener('xcagi:workflow-label-print-signal', onWorkflowLabelPrintSignal)
    window.removeEventListener('xcagi:workflow-receipt-feedback-signal', onWorkflowReceiptFeedbackSignal)
    window.removeEventListener('xcagi:workflow-ai-employees-changed', onWorkflowAiEmployeesChanged)
    window.removeEventListener('storage', onWorkflowEmployeesStorage)
    window.removeEventListener('xcagi:auto-refresh-wechat-changed', onStarRefreshOrIntentChangedForWorkflow)
    window.removeEventListener('xcagi:pro-intent-experience-changed', onStarRefreshOrIntentChangedForWorkflow)
    window.removeEventListener('xcagi:wechat-star-feed-polled', onWechatStarFeedPolled)
    window.removeEventListener('focus', onWindowFocusForWorkflowTasks)
    document.removeEventListener('visibilitychange', onVisibilityChangeForWorkflowTasks)
    stopPhoneAgentStatusPoll()
  }

  return {
    onWechatAiTaskEnqueue,
    readWorkflowEmployeeEnabledMap,
    upsertWorkflowEmployeeTask,
    syncWorkflowEmployeePanelTasks,
    mountWorkflowPanel,
    unmountWorkflowPanel,
    registerWorkflowPanelWatchers,
  }
}
'''

DB_HEADER = '''import { type Ref } from 'vue'
import {
  XCAGI_PROMPT_DB_READ_TOKEN_EVENT,
  XCAGI_PROMPT_DB_WRITE_TOKEN_EVENT,
  armNextPlannerChatDbWriteToken,
  consumePlannerChatDbWriteTokenArm,
  isPlannerChatDbWriteTokenArmed,
  isProductsReadGateGraceActive,
  readStoredDbTokens,
} from '@/fhd/dbTokenHeaders'

export interface UseChatDbTokenGateDeps {
  sessionId: Ref<string>
  isProMode: Ref<boolean>
  pendingDbWriteChatRetryMessages: Ref<string[] | null>
  plannerWriteUnlockResumeDraft: Ref<string>
  executeRemoteChatRound: (msgs: string[], opts?: { fromWriteUnlock?: boolean }) => Promise<void>
}

export function useChatDbTokenGate(deps: UseChatDbTokenGateDeps) {
  const {
    sessionId,
    isProMode,
    pendingDbWriteChatRetryMessages,
    plannerWriteUnlockResumeDraft,
    executeRemoteChatRound,
  } = deps

'''

DB_FOOTER = '''
  return {
    resolveEffectiveProModeState,
    syncProModeState,
    getModeScopedUserId,
    resolveChatDbTokensForPayload,
    handleChatRequiresToken,
    onDbWriteUnlockedForChatRetry,
  }
}
'''

EXCEL_HEADER = '''import { ref, computed, type Ref } from 'vue'
import {
  readPersistedExcelAnalysisContext,
  persistExcelAnalysisContext,
  resolveExcelFilePathFromAnalysis,
  resolveExcelSheetOptionsFromContext,
  resolveLinkedSheetGridPreview,
  type LinkedExcelSheet,
} from './useChatPersistence'
import { filesToMultimodalRows, type MultimodalAttachmentRow } from '@/utils/multimodalAttachments'

export interface UseChatExcelContextDeps {
  sessionId: Ref<string>
  addAndSaveMessage: (content: string, role?: 'user' | 'ai' | 'task', extras?: Record<string, unknown>) => Promise<void>
  resolveExcelAnalysisContextForRequest?: () => Record<string, unknown> | null
}

export function useChatExcelContext(deps: UseChatExcelContextDeps) {
  const { sessionId, addAndSaveMessage } = deps

  const lastExcelAnalysisContext = ref<Record<string, unknown> | null>(null)
  const linkedExcelSheet = ref<LinkedExcelSheet | null>(null)
  const linkedExcelAllSheets = ref(false)
  const multimodalStaging = ref<MultimodalAttachmentRow[]>([])
  const multimodalPendingCount = computed(() => multimodalStaging.value.length)

  function resolveExcelAnalysisContextForRequest(): Record<string, unknown> | null {
    if (lastExcelAnalysisContext.value) return lastExcelAnalysisContext.value
    const sid = String(sessionId.value || '').trim() || 'default'
    const restored = readPersistedExcelAnalysisContext(sid)
    if (restored) {
      lastExcelAnalysisContext.value = restored
      return restored
    }
    return null
  }

  const excelSheetOptions = computed(() => {
    const ctx = resolveExcelAnalysisContextForRequest()
    return resolveExcelSheetOptionsFromContext(ctx)
  })

'''

EXCEL_FOOTER = '''
  return {
    lastExcelAnalysisContext,
    linkedExcelSheet,
    linkedExcelAllSheets,
    multimodalStaging,
    multimodalPendingCount,
    excelSheetOptions,
    resolveExcelAnalysisContextForRequest,
    injectExcelContextPayload,
    consumeMultimodalIntoPlannerContext,
    onMultimodalFileChange,
    bindExcelSheetToChat,
    bindAllExcelSheetsToChat,
    persistExcelAnalysisContextForSession: (sid: string, ctx: Record<string, unknown> | null) =>
      persistExcelAnalysisContext(sid, ctx),
  }
}
'''

REQUEST_HEADER = '''import { ref, type Ref } from 'vue'
import type { ChatMessage } from './useChatMessages'
import chatApi from '../api/chat'

export interface UseChatRequestDeps {
  messages: Ref<ChatMessage[]>
  proIntentExperienceEnabled?: Ref<boolean>
  isProMode: Ref<boolean>
  lastRequestContextSummary: Ref<string>
  plannerWriteUnlockResumeDraft: Ref<string>
  resolveEffectiveProModeState: () => boolean
  getModeScopedUserId: (proEnabled: boolean) => string
  resolveChatDbTokensForPayload: () => { db_read_token?: string; db_write_token?: string }
  injectExcelContextPayload: (ctx: Record<string, unknown>, parts: string[]) => boolean
  consumeMultimodalIntoPlannerContext: (ctx: Record<string, unknown>, parts: string[]) => void
}

export function useChatRequest(deps: UseChatRequestDeps) {
  const {
    messages,
    proIntentExperienceEnabled,
    isProMode,
    lastRequestContextSummary,
    plannerWriteUnlockResumeDraft,
    resolveEffectiveProModeState,
    getModeScopedUserId,
    resolveChatDbTokensForPayload,
    injectExcelContextPayload,
    consumeMultimodalIntoPlannerContext,
  } = deps

  const loadingProgressText = ref('处理中...')
  let waitProgressTicker: ReturnType<typeof setInterval> | null = null
  let chatBatchTimer: ReturnType<typeof setTimeout> | null = null
  const chatBatchQueue: string[] = []

'''

REQUEST_FOOTER = '''
  return {
    loadingProgressText,
    chatBatchTimer,
    chatBatchQueue,
    buildPlannerChatRequestPayload,
    requestChatByMode,
    requestChatByModeBatch,
    getChatBatchDebounceMs,
    setLoadingProgress,
    startWaitProgressTimer,
    stopLoadingProgress,
    requestChatByModeWithTimeout,
    requestChatByModeBatchWithTimeout,
    resolveChatTimeoutMs,
  }
}
'''

RESPONSE_HEADER = '''import { type Ref } from 'vue'
import type { ChatMessage } from './useChatMessages'
import type { TaskItem } from './useChatPersistence'

export interface UseChatResponseAttachDeps {
  messages: Ref<ChatMessage[]>
  lastRequestContextSummary: Ref<string>
  taskList: Ref<TaskItem[]>
  upsertTask: (item: Partial<TaskItem> & Pick<TaskItem, 'id' | 'type' | 'source' | 'title' | 'status'>) => void
  createTaskId: (prefix: string) => string
}

export function useChatResponseAttach(deps: UseChatResponseAttachDeps) {
  const { messages, lastRequestContextSummary, taskList, upsertTask, createTaskId } = deps

'''

RESPONSE_FOOTER = '''
  return {
    getLastAiMessageRef,
    attachThinkingStepsToLastAiMessage,
    attachTodoStepsToLastAiMessage,
    attachWorkflowTraceToLastAiMessage,
    attachContextSummaryToLastAiMessage,
    syncTaskFromChatResponse,
  }
}
'''

SESSION_HEADER = '''import { ref, watch, type Ref } from 'vue'
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
  const historySessions = ref<unknown[]>([])
  const historyLoading = ref(false)
  const historyError = ref('')

'''

SESSION_FOOTER = '''
  function registerHistoryModWatch(showHistoryPanelFn: () => Promise<void>) {
    watch(
      () => String(modsStore.activeModId || ''),
      () => {
        historyError.value = ''
        if (showHistory.value) {
          void showHistoryPanelFn()
        } else if (historySessions.value.length) {
          historySessions.value = mergeHistorySessions([])
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
'''

ORCH_HEADER = '''import { ref, computed, watch, onMounted, onBeforeUnmount, type Ref } from 'vue'
import { useTutorialStore } from '@/stores/tutorial'
import { useModsStore } from '@/stores/mods'
import {
  readPersistedExcelAnalysisContext,
  persistExcelAnalysisContext,
  resolveExcelFilePathFromAnalysis,
  resolveExcelSheetOptionsFromContext,
  extractLikelyProductQueryKeyword,
  useChatHistoryPersistence,
  useChatTaskPanelPersistence,
} from './useChatPersistence'
import { useChatTaskList } from './useChatTaskList'
import { useChatMessages } from './useChatMessages'
import { useShipmentTask, type ShipmentTask } from './useShipmentTask'
import { usePrintService } from './usePrintService'
import { useExcelAnalysis } from './useExcelAnalysis'
import { isStartPrintMessage, detectRuntimeModeCommand } from '../utils/textParser'
import chatApi, { parseChatStreamErrorResponse } from '../api/chat'
import productsApi from '../api/products'
import { readPlannerSseResponse, isChatStreamEnabled, type PlannerSseEvent } from '@/utils/chatSseStream'
import { fetchShipmentRecordsForUnit, summarizeShipmentRecordsForAudit } from '@/utils/shipmentMgmtPostPrint'
import { isCoreWorkflowModInstalled } from '@/constants/coreWorkflowMod'
import { dispatchCoreWorkflowModRun } from '@/workflow/coreWorkflowDispatcher'
import { FHD_DB_WRITE_UNLOCKED_EVENT } from '@/fhd/dbTokenHeaders'
import { useChatWorkflowPanel } from './useChatWorkflowPanel'
import { useChatDbTokenGate } from './useChatDbTokenGate'
import { useChatExcelContext } from './useChatExcelContext'
import { useChatRequest } from './useChatRequest'
import { useChatResponseAttach } from './useChatResponseAttach'
import { useChatSessionHistory } from './useChatSessionHistory'
import type { UseChatViewOptions } from './useChatView'

export function useChatOrchestration(options: UseChatViewOptions) {
  const tutorialStore = useTutorialStore()
  const modsStore = useModsStore()
  const { sessionId } = options
  const proIntentExperienceEnabled = options.proIntentExperienceEnabled

  const historyPersistence = useChatHistoryPersistence({
    sessionId,
    getActiveModId: () => String(modsStore.activeModId || ''),
  })
  const { toPlainText, isWelcomeMessage } = historyPersistence

  const {
    messages,
    addMessage,
    addAndSaveMessage: addAndSaveMessageRaw,
    saveMessage,
    pushStreamingAiShell,
    applyPlainTextToMessageIndex,
    clearMessages,
    loadMessages,
    syncFromServer,
    queueVoice,
    clearVoiceQueue,
  } = useChatMessages(sessionId)

  const CHAT_TTS_ENABLED_KEY = 'xcagi_chat_tts_enabled'
  const ttsEnabled = ref(localStorage.getItem(CHAT_TTS_ENABLED_KEY) !== '0')

  function setTtsEnabled(enabled: boolean) {
    ttsEnabled.value = enabled
    localStorage.setItem(CHAT_TTS_ENABLED_KEY, enabled ? '1' : '0')
    if (!enabled) clearVoiceQueue()
  }

  async function addAndSaveMessage(
    content: string,
    role: 'user' | 'ai' | 'task' = 'ai',
    extras?: Parameters<typeof addAndSaveMessageRaw>[2],
  ): Promise<void> {
    await addAndSaveMessageRaw(content, role, extras, {
      speak: ttsEnabled.value && role === 'ai',
    })
  }

  const currentTask = ref<ShipmentTask | null>(null)
  const orderNumberFetching = ref(false)
  const isLoading = ref(false)
  const isStreamingReply = ref(false)
  const isExecuting = ref(false)
  const latestAssistantPush = ref<{ title: string; description: string } | null>(null)
  const proRuntimeTask = ref<{ title: string; statusText: string; statusClass: string; description: string } | null>(null)
  const chatMessagesRef = ref<HTMLElement | null>(null)
  let persistTaskPanelStateForSession: (targetSessionId?: string) => void = () => {}

  const {
    taskList,
    activeTaskId,
    expandedTaskIds,
    taskFilter,
    activeTask,
    filteredTaskList,
    createTaskId,
    sortTaskList,
    upsertTask,
    finishTask,
    failTask,
    cancelTaskById,
    retryTask,
    toggleTaskExpanded,
    setTaskFilter,
    clearTaskHistory,
    jumpToTaskMessage,
  } = useChatTaskList({
    chatMessagesRef,
    onPersist: () => persistTaskPanelStateForSession(),
  })

  const panelPersistence = useChatTaskPanelPersistence({
    sessionId,
    taskList,
    activeTaskId,
    expandedTaskIds,
    taskFilter,
    currentTask,
    sortTaskList,
  })
  persistTaskPanelStateForSession = panelPersistence.persistTaskPanelStateForSession
  const { applyPersistedTaskPanelStateForSession, clearPersistedTaskPanelState } = panelPersistence

  const pendingDbWriteChatRetryMessages = ref<string[] | null>(null)
  const plannerWriteUnlockResumeDraft = ref('')
  const lastRequestContextSummary = ref('')
  const isProMode = ref(false)
  const pushCopied = ref(false)

  const executeRemoteChatRoundRef: {
    fn: (msgs: string[], opts?: { fromWriteUnlock?: boolean }) => Promise<void>
  } = { fn: async () => {} }

  const dbGate = useChatDbTokenGate({
    sessionId,
    isProMode,
    pendingDbWriteChatRetryMessages,
    plannerWriteUnlockResumeDraft,
    executeRemoteChatRound: (msgs, opts) => executeRemoteChatRoundRef.fn(msgs, opts),
  })

  const excelCtx = useChatExcelContext({ sessionId, addAndSaveMessage })
  const {
    lastExcelAnalysisContext,
    linkedExcelSheet,
    linkedExcelAllSheets,
    multimodalStaging,
    multimodalPendingCount,
    excelSheetOptions,
    resolveExcelAnalysisContextForRequest,
    injectExcelContextPayload,
    consumeMultimodalIntoPlannerContext,
    onMultimodalFileChange,
    bindExcelSheetToChat,
    bindAllExcelSheetsToChat,
  } = excelCtx

  const responseAttach = useChatResponseAttach({
    messages,
    lastRequestContextSummary,
    taskList,
    upsertTask,
    createTaskId,
  })
  const {
    getLastAiMessageRef,
    attachThinkingStepsToLastAiMessage,
    attachTodoStepsToLastAiMessage,
    attachWorkflowTraceToLastAiMessage,
    attachContextSummaryToLastAiMessage,
    syncTaskFromChatResponse,
  } = responseAttach

  const chatRequest = useChatRequest({
    messages,
    proIntentExperienceEnabled,
    isProMode,
    lastRequestContextSummary,
    plannerWriteUnlockResumeDraft,
    resolveEffectiveProModeState: dbGate.resolveEffectiveProModeState,
    getModeScopedUserId: dbGate.getModeScopedUserId,
    resolveChatDbTokensForPayload: dbGate.resolveChatDbTokensForPayload,
    injectExcelContextPayload,
    consumeMultimodalIntoPlannerContext,
  })

  const {
    loadingProgressText,
    chatBatchQueue,
    buildPlannerChatRequestPayload,
    requestChatByMode,
    requestChatByModeBatch,
    getChatBatchDebounceMs,
    setLoadingProgress,
    startWaitProgressTimer,
    stopLoadingProgress,
    requestChatByModeWithTimeout,
    requestChatByModeBatchWithTimeout,
    resolveChatTimeoutMs,
  } = chatRequest

  function generateSessionId(): string {
    return Date.now().toString(36) + Math.random().toString(36).substr(2)
  }

  function scrollToBottom() {
    if (chatMessagesRef.value) {
      chatMessagesRef.value.scrollTop = chatMessagesRef.value.scrollHeight
    }
  }

  function normalizeServerContentToHtml(raw: unknown): string {
    const text = String(raw || '')
    if (/<[a-z][\s\S]*>/i.test(text)) return text
    const div = document.createElement('div')
    div.textContent = text
    return div.innerHTML.replace(/\\n/g, '<br>')
  }

  const sessionHistory = useChatSessionHistory({
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
  })
  const {
    showHistory,
    historySessions,
    historyLoading,
    historyError,
    showHistoryPanel,
    loadSession,
    clearHistorySessions,
    newConversation,
    registerHistoryModWatch,
  } = sessionHistory

'''

ORCH_FOOTER = '''
  executeRemoteChatRoundRef.fn = executeRemoteChatRound

  registerHistoryModWatch(showHistoryPanel)

  const workflowPanel = useChatWorkflowPanel({
    taskList,
    activeTaskId,
    expandedTaskIds,
    taskFilter,
    currentTask,
    upsertTask,
    sortTaskList,
    createTaskId,
    persistTaskPanelStateForSession,
    showTaskConfirm,
    emitAssistantPush,
    maybeCloseAssistantFloatForShipmentTask,
  })
  workflowPanel.registerWorkflowPanelWatchers(persistTaskPanelStateForSession, currentTask)

  onMounted(() => {
    const sid = String(sessionId.value || '').trim() || 'default'
    if (!lastExcelAnalysisContext.value) {
      const restored = readPersistedExcelAnalysisContext(sid)
      if (restored) lastExcelAnalysisContext.value = restored
    }
    if (!linkedExcelSheet.value) {
      const first = excelSheetOptions.value[0]
      if (first) linkedExcelSheet.value = first
    }
    window.addEventListener(FHD_DB_WRITE_UNLOCKED_EVENT, dbGate.onDbWriteUnlockedForChatRetry)
    workflowPanel.mountWorkflowPanel()
  })

  onBeforeUnmount(() => {
    window.removeEventListener(FHD_DB_WRITE_UNLOCKED_EVENT, dbGate.onDbWriteUnlockedForChatRetry)
    workflowPanel.unmountWorkflowPanel()
  })

  return {
    messages,
    lastMessage: computed(() => messages.value[messages.value.length - 1] ?? null),
    currentTask,
    orderNumberFetching,
    isLoading,
    isStreamingReply,
    isExecuting,
    latestAssistantPush,
    proRuntimeTask,
    taskList,
    filteredTaskList,
    activeTask,
    activeTaskId,
    expandedTaskIds,
    taskFilter,
    showHistory,
    historySessions,
    historyLoading,
    historyError,
    chatMessagesRef,
    pushCopied,
    loadingProgressText,
    excelAnalyzeUploading,
    excelAnalyzeInputRef,
    multimodalPendingCount,
    excelSheetOptions,
    linkedExcelSheet,
    linkedExcelAllSheets,
    isProMode,
    isPrinting,
    taskTableColumns,
    taskTableItems,
    taskOrderNumber,
    generateSessionId,
    scrollToBottom,
    syncProModeState: dbGate.syncProModeState,
    sendMessage,
    confirmTask,
    refetchTaskOrderNumber,
    cancelTask,
    showTaskConfirm,
    triggerUpload,
    onExcelAnalyzeFileChange,
    showHistoryPanel,
    loadSession,
    clearHistorySessions,
    newConversation,
    handleShipmentDownloadClick,
    startPrintFromTaskCard,
    copyAssistantPushContent,
    openAssistantFloatFromTaskPanel,
    syncSessionMessages,
    bindExcelSheetToChat,
    bindAllExcelSheetsToChat,
    toggleTaskExpanded,
    setTaskFilter,
    clearTaskHistory,
    cancelTaskById,
    retryTask,
    jumpToTaskMessage,
    handleAutoAction,
    isStartPrintMessage,
    ttsEnabled,
    setTtsEnabled,
  }
}
'''

FACADE = '''import type { Ref } from 'vue'
import { useChatOrchestration } from './useChatOrchestration'

export interface UseChatViewOptions {
  sessionId: Ref<string>
  proIntentExperienceEnabled?: Ref<boolean>
}

/** Facade: wires extracted composables; implementation in useChatOrchestration. */
export function useChatView(options: UseChatViewOptions) {
  return useChatOrchestration(options)
}
'''

if __name__ == '__main__':
    main()
