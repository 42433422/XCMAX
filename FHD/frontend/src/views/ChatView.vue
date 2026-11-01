<template>
  <div class="chat-view page-view active" id="view-chat">
    <TaskWorkspaceContextBar
      v-if="workspaceMode"
      v-bind="workspaceHeader"
      :action-pending="taskCenterStore.actionPending"
      @control="controlWorkspaceTask"
    />
    <ChatQuickActions :buttons="visibleQuickButtons" @quick="sendQuick" />
    <div v-if="cacheError" class="chat-cache-warning chat-composer-status chat-composer-status--error" role="alert">
      {{ cacheError }} <button type="button" class="btn btn-secondary btn-sm" @click="retryMessagesCache">重试本机保存</button>
    </div>
    <div class="chat-container" data-tour="chat-thread" :style="chatPaneStyle">
      <ChatMessageList
        :empty-intro="getIndustryPreset(currentIndustryId).scenario"
        @fill-example="fillComposer"
        @model-settings="openModelSettings"
        :session-key="messageSessionKey"
        :proactive-suggestions="proactiveSuggestionsByMessage"
        @pick-proactive-suggestion="pickProactiveSuggestion"
        :messages="messages"
        @retry-save="retryMessageSave"
        :is-loading="isLoading"
        :is-streaming-reply="isStreamingReply"
        :loading-progress-text="loadingProgressText"
        :message-heights="messageHeights"
        :latest-ai-message-index="latestAiMessageIndex"
        :playing-msg-idx="playingMsgIdx"
        :is-message-collapsed="isMessageCollapsed"
        :get-collapsed-preview="getCollapsedPreview"
        :can-speak-message="canSpeakMessage"
        :chat-messages-ref="chatRefBag.chatMessagesRef"
        @expand-message="expandMessage"
        @collapse-message="collapseMessage"
        @toggle-message-tts="toggleMessageTts"
        @shipment-download-click="handleShipmentDownloadClick"
        @approval-confirm="confirmWorkflowFromCard"
        @approval-cancel="cancelWorkflowFromCard"
        @approve-run="approveRunFromChat"
      />
      <div v-if="isTaskPaneResizable" class="chat-pane-handle-slot">
        <PaneResizeHandle
          orientation="vertical"
          label="调整任务面板宽度"
          @resize-start="onTaskPaneResizeStart"
          @reset="resetTaskPaneWidth"
        />
      </div>
      <ChatSidePanel
        :current-task="currentTask"
        :task-list="visibleTaskList"
        :task-control-states="taskControlStates"
        :task-sync-state="taskSyncState"
        @refresh-tasks="refreshTasks"
        :filtered-task-list="visibleFilteredTaskList"
        :active-task-id="visibleActiveTaskId"
        :expanded-task-ids="expandedTaskIds"
        :task-filter="taskFilter"
        :latest-assistant-push="latestAssistantPush"
        :push-copied="pushCopied"
        :order-number-fetching="orderNumberFetching"
        :is-executing="isExecuting"
        :task-table-columns="taskTableColumns"
        :task-table-items="taskTableItems"
        :task-order-number="taskOrderNumber"
        :format-task-time="formatTaskTime"
        :format-task-source-label="formatTaskSourceLabel"
        :workflow-task-dot-status-class="workflowTaskDotStatusClassForTask"
        :workflow-task-dot-title="workflowTaskDotTitleForTask"
        :history-sessions="historySessions"
        :current-session-id="currentSessionId"
        :history-loading="historyLoading"
        :history-error="historyError"
        :history-has-more="historyHasMore"
        :history-loading-more="historyLoadingMore"
        @load-more-history="loadMoreHistorySessions"
        @confirm-task="confirmTask"
        @cancel-task="cancelTask"
        @refetch-order-number="refetchTaskOrderNumber"
        @set-custom-order-number="setCustomOrderNumber"
        @shipment-download-click="handleShipmentDownloadClick"
        @start-print="startPrintFromTaskCard"
        @switch-view="emitSwitchView"
        @set-task-filter="setTaskFilter"
        @clear-task-history="clearTaskHistory"
        @toggle-task-expanded="toggleTaskExpanded"
        @select-task="selectTask"
        @open-shipment-records="openShipmentRecordsFromAuditTask"
        @jump-to-task-message="jumpToTaskMessage"
        @retry-task="retryTask"
        @pause-task="pauseTask"
        @resume-task="resumeTask"
        @approve-task="approveTaskWithFeedback"
        @cancel-task-by-id="cancelTaskById"
        @copy-assistant-push="copyAssistantPushContent"
        @open-assistant-float="openAssistantFloatFromTaskPanel"
        @new-conversation="newConversation"
        @refresh-history="refreshHistorySessions"
        @clear-history-sessions="clearHistorySessions"
        @load-session="loadSession"
        @rename-session="renameSession"
        @delete-session="deleteSession"
      />
    </div>
    <div
      class="input-area"
      data-tour="chat-input-area"
      :class="{ 'input-area--dragover': composerDragOver }"
      @dragenter.prevent="onComposerDragEnter"
      @dragover.prevent="onComposerDragOver"
      @dragleave.prevent="onComposerDragLeave"
      @drop.prevent="onComposerDrop"
    >
      <div v-if="composerDragOver" class="composer-drop-overlay" role="status">松开以上传附件</div>
      <ChatInputToolbar
        :excel-analyze-uploading="excelAnalyzeUploading"
        :multimodal-pending-count="multimodalPendingCount"
        :proactive-suggestions-enabled="proactiveEnabled"
        :tts-enabled="ttsEnabled"
        :excel-analyze-input-ref="chatRefBag.excelAnalyzeInputRef"
        :office-docking-processing="officeDockingProcessing"
        @new-conversation="newConversation"
        @trigger-office-docking="triggerOfficeDocking"
        @excel-file-change="onExcelAnalyzeFileChange"
        @proactive-suggestions-change="onProactiveSuggestionsChange"
        @toggle-tts="setTtsEnabled"
      />
      <ChatModelStatus ref="modelStatusRef" :session-id="currentSessionId" :mod-id="String(modsStore.activeModId || '')" />
      <div v-if="excelSheetOptions.length" class="sheet-link-bar">
        <span class="sheet-link-label">关联工作表：</span>
        <button class="sheet-link-btn" :class="{ active: linkedExcelAllSheets }" @click="bindAllExcelSheetsToChat">
          全部（{{ excelSheetOptions.length }}）
        </button>
        <button
          v-for="sheet in excelSheetOptions"
          :key="`${sheet.sheet_index}-${sheet.sheet_name}`"
          class="sheet-link-btn"
          :class="{
            active:
              !linkedExcelAllSheets &&
              linkedExcelSheet &&
              linkedExcelSheet.sheet_name === sheet.sheet_name &&
              linkedExcelSheet.sheet_index === sheet.sheet_index,
          }"
          @click="bindExcelSheetToChat(sheet)"
        >
          Sheet {{ sheet.sheet_index }}（{{ sheet.sheet_name }}）
        </button>
      </div>
      <div class="input-wrapper">
        <textarea
          id="messageInput"
          rows="2"
          :placeholder="inputPlaceholder"
          v-model="messageInput"
          aria-describedby="chat-composer-status"
          @keydown="handleKeyDown"
        ></textarea>
        <button
          type="button"
          class="btn voice-input-btn"
          :class="voiceButtonClass"
          :disabled="voiceButtonDisabled"
          :title="voiceButtonTitle"
          data-tutorial-id="chat-voice-push-to-talk"
          @mousedown.prevent="startVoiceRecording"
          @mouseup.prevent="stopVoiceRecording(false)"
          @mouseleave="stopVoiceRecording(true)"
          @touchstart.prevent="startVoiceRecording"
          @touchend.prevent="stopVoiceRecording(false)"
          @touchcancel.prevent="stopVoiceRecording(true)"
        >
          <i class="fa" :class="voiceButtonIcon" aria-hidden="true"></i>
          <span class="voice-input-btn-label">{{ voiceButtonText }}</span>
        </button>
        <button v-if="isLoading" type="button" class="btn" data-testid="stop-reply" @click="stopReply">停止回复</button>
        <button
          class="btn btn-primary send-message-btn"
          id="sendMessageBtn"
          :disabled="!canSendMessage"
          :aria-disabled="!canSendMessage"
          :title="sendButtonTitle"
          @click="sendMessage"
        >
          {{ isLoading ? '发送纠正' : '发送' }}
        </button>
      </div>
      <div
        v-if="composerStatusText"
        id="chat-composer-status"
        class="chat-composer-status"
        :class="{ 'chat-composer-status--error': !!voiceFeedbackText }"
        role="status"
        aria-live="polite"
      >
        {{ composerStatusText }}
      </div>
    </div>
    <ChatHistoryModal
      :history-has-more="historyHasMore"
      :history-loading-more="historyLoadingMore"
      @load-more="loadMoreHistorySessions"
      :show="showHistory"
      :history-sessions="historySessions"
      :history-loading="historyLoading"
      :history-error="historyError"
      :current-session-id="currentSessionId"
      @close="showHistory = false"
      @refresh="showHistoryPanel"
      @clear="clearHistorySessions"
      @load-session="loadSession"
    />
    <input
      ref="officeDockingInputRef"
      type="file"
      multiple
      accept=".xlsx,.xlsm,.xls,.csv,.docx,.doc,.pdf,.pptx,.ppt"
      style="display: none"
      @change="onOfficeDockingFileChange"
    />
    <ChatOfficeDockingReview
      v-if="officeDockingPanelOpen"
      :items="officeDockingReviewItems"
      :processing="officeDockingProcessing"
      @toggle-target="toggleOfficeDockingTarget"
      @confirm="confirmOfficeDockingReview"
      @close="clearOfficeDockingReview"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, onDeactivated } from 'vue'
import { storeToRefs } from 'pinia'
import { useIndustryStore } from '@/stores/industry'
import { useAgentTaskCenterStore } from '@/stores/agentTaskCenter'
import { showAppToast } from '@/composables/useAppToast'
import { getIndustryPreset, getIndustryQuickButtons } from '@/constants/industryPresets'
import { useRouter } from 'vue-router'
import PaneResizeHandle from '@/components/PaneResizeHandle.vue'
import ChatQuickActions from '@/components/chat/ChatQuickActions.vue'
import ChatMessageList from '@/components/chat/ChatMessageList.vue'
import ChatSidePanel from '@/components/chat/ChatSidePanel.vue'
import ChatInputToolbar from '@/components/chat/ChatInputToolbar.vue'
import ChatHistoryModal from '@/components/chat/ChatHistoryModal.vue'
import ChatOfficeDockingReview from '@/components/chat/ChatOfficeDockingReview.vue'
import TaskWorkspaceContextBar from '@/components/chat/TaskWorkspaceContextBar.vue'
import { useChatOfficeDocking } from '@/composables/useChatOfficeDocking'
import { useResizablePane } from '@/composables/useResizablePane'
import { useModsStore } from '@/stores/mods'
import { useChatView } from '@/composables/useChatView'
import { useChatVoiceInput } from '@/composables/useChatVoiceInput'
import { useProactiveReplySuggestions } from '@/composables/useProactiveReplySuggestions'
import { useChatMessageUi } from '@/composables/useChatMessageUi'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { useChatViewHost } from '@/composables/useChatViewHost'
import ChatModelStatus from '@/components/chat/ChatModelStatus.vue'
import { workflowTaskDotStatusClassForTask, workflowTaskDotTitleForTask } from '@/workflow/coreWorkflowTaskUi'
import { formatTaskTime, formatTaskSourceLabel } from '@/utils/chatTaskLabels'
import { readAiSessionIdFromStorage, writeAiSessionIdToStorage } from '@/utils/chatStorageKeys'
import { resolveWorkspaceSessionId, useRoutedTaskWorkspace, useTaskApprovalFeedback } from '@/composables/useRoutedTaskWorkspace'

const props = withDefaults(
  defineProps<{
    workspaceTaskId?: string
    workspaceConversationId?: string
  }>(),
  {
    workspaceTaskId: '',
    workspaceConversationId: '',
  },
)

const router = useRouter()
const modelStatusRef = ref<InstanceType<typeof ChatModelStatus> | null>(null)
function openModelSettings() { modelStatusRef.value?.refreshAndReveal() }
const modsStore = useModsStore()
const { mods: modsFromStore } = storeToRefs(modsStore)
const taskCenterStore = useAgentTaskCenterStore()
const industryStore = useIndustryStore()
const { currentIndustryId } = storeToRefs(industryStore)

// Chat toolbar「主动意识」uses proactive suggestions storage — NOT starred WeChat polling.
// Keep WeChat star-refresh forced off here so old checkbox events cannot misfire workflow polls.
const autoRefreshStarredWechat = ref(false)
const isTaskPaneResizable = ref(true)
function generateSessionId(): string {
  return Date.now().toString(36) + Math.random().toString(36).substr(2)
}

const _storedSessionId = readAiSessionIdFromStorage()
const initialWorkspaceSessionId = resolveWorkspaceSessionId(props)
const currentSessionId = ref(initialWorkspaceSessionId || _storedSessionId || generateSessionId())
const messageSessionKey = computed(() => JSON.stringify([currentSessionId.value, modsStore.activeModId, productReadAccountEpoch.value]))
if (!_storedSessionId) writeAiSessionIdToStorage(currentSessionId.value)

const chatViewApi = useChatView({ sessionId: currentSessionId })
const chatRefBag = {
  chatMessagesRef: chatViewApi.chatMessagesRef,
  excelAnalyzeInputRef: chatViewApi.excelAnalyzeInputRef,
}

const {
  messages,
  cacheError,
  retryMessagesCache,
  retryMessageSave,
  currentTask,
  orderNumberFetching,
  isLoading,
  isStreamingReply,
  isExecuting,
  latestAssistantPush,
  taskList,
  taskControlStates,
  taskSyncState,
  refreshTasks,
  activeTaskId,
  filteredTaskList,
  expandedTaskIds,
  taskFilter,
  showHistory,
  historySessions,
  historyLoading,
  historyError,
  historyHasMore,
  historyLoadingMore,
  loadMoreHistorySessions,
  pushCopied,
  loadingProgressText,
  excelAnalyzeUploading,
  multimodalPendingCount,
  excelSheetOptions,
  linkedExcelSheet,
  linkedExcelAllSheets,
  taskTableColumns,
  taskTableItems,
  taskOrderNumber,
  sendMessage: chatSendMessage,
  stopReply,
  confirmWorkflowFromCard,
  cancelWorkflowFromCard,
  confirmTask,
  refetchTaskOrderNumber,
  setCustomOrderNumber,
  cancelTask,
  onExcelAnalyzeFileChange,
  bindExcelSheetToChat,
  bindAllExcelSheetsToChat,
  toggleTaskExpanded,
  selectTask,
  setTaskFilter,
  clearTaskHistory,
  retryTask,
  pauseTask,
  resumeTask,
  approveTask,
  cancelTaskById,
  jumpToTaskMessage,
  refreshHistorySessions,
  showHistoryPanel,
  loadSession,
  clearHistorySessions,
  renameSession,
  deleteSession,
  newConversation,
  handleShipmentDownloadClick,
  startPrintFromTaskCard,
  copyAssistantPushContent,
  openAssistantFloatFromTaskPanel,
  syncSessionMessages,
  handleAutoAction: chatHandleAutoAction,
  ttsEnabled,
  setTtsEnabled,
  addAndSaveMessage,
  stageExcelAnalysisContext,
} = chatViewApi

const { workspaceTaskId, workspaceMode, visibleTaskList, visibleFilteredTaskList, visibleActiveTaskId, workspaceHeader } =
  useRoutedTaskWorkspace({
    props,
    currentSessionId,
    taskList,
    filteredTaskList,
    activeTaskId,
    loadSession,
    taskSummaries: storeToRefs(taskCenterStore).tasks,
    markTaskRead: taskCenterStore.markTaskRead,
  })

async function controlWorkspaceTask(action: 'approve' | 'pause' | 'cancel' | 'resume' | 'retry'): Promise<void> {
  await taskCenterStore.controlTask(workspaceTaskId.value, action)
  if (taskCenterStore.error) showAppToast(taskCenterStore.error, 'error', { duration: 8000 })
}

const { approveTaskWithFeedback, approveRunFromChat } = useTaskApprovalFeedback({
  currentSessionId, approveTask, syncSessionMessages,
})

const messageInput = ref('')
function fillComposer(text: string) {
  messageInput.value = text
  document.getElementById('messageInput')?.focus()
}
const composerDragOver = ref(false)
let composerDragDepth = 0

const COMPOSER_ACCEPT_RE = /\.(xlsx|xlsm|pdf|jpe?g|png|webp|gif)$/i
const COMPOSER_ACCEPT_MIME = /^(image\/(jpeg|png|webp|gif)|application\/pdf)/i

function filesFromDataTransfer(dt: DataTransfer | null): File[] {
  if (!dt?.files?.length) return []
  return Array.from(dt.files)
}

function isComposerAcceptedFile(file: File): boolean {
  return COMPOSER_ACCEPT_RE.test(file.name) || COMPOSER_ACCEPT_MIME.test(file.type || '')
}

function onComposerDragEnter(e: DragEvent) {
  if (!e.dataTransfer?.types?.includes('Files')) return
  composerDragDepth += 1
  composerDragOver.value = true
}

function onComposerDragOver(e: DragEvent) {
  if (!e.dataTransfer?.types?.includes('Files')) return
  e.dataTransfer.dropEffect = 'copy'
  composerDragOver.value = true
}

function onComposerDragLeave() {
  composerDragDepth = Math.max(0, composerDragDepth - 1)
  if (composerDragDepth === 0) composerDragOver.value = false
}

async function onComposerDrop(e: DragEvent) {
  composerDragDepth = 0
  composerDragOver.value = false
  if (isLoading.value || excelAnalyzeUploading.value) return
  const files = filesFromDataTransfer(e.dataTransfer)
  if (!files.length) return
  const accepted = files.filter(isComposerAcceptedFile)
  if (!accepted.length) {
    await addAndSaveMessage('[附件] 不支持的文件类型，请拖入 Excel、图片或 PDF', 'ai')
    return
  }
  // The picker snapshots these files and applies the existing session/identity guard.
  await onExcelAnalyzeFileChange({ target: { files: accepted, value: '' } } as unknown as Event)
}

const {
  voiceButtonDisabled,
  voiceButtonClass,
  voiceButtonIcon,
  voiceButtonText,
  voiceButtonTitle,
  voiceFeedbackText,
  startVoiceRecording,
  stopVoiceRecording,
  cleanupVoiceInput,
  warmVoiceModel,
} = useChatVoiceInput({ messageInput, isLoading, sessionId: currentSessionId })

// Best-effort ASR warm so first push-to-talk is not a 6–7s cold load (item 4 latency).
let voiceWarmTimer: number | undefined
onMounted(() => {
  voiceWarmTimer = window.setTimeout(() => {
    void warmVoiceModel()
  }, 2500)
})
onBeforeUnmount(() => window.clearTimeout(voiceWarmTimer))
onDeactivated(() => window.clearTimeout(voiceWarmTimer))

const {
  messageHeights,
  playingMsgIdx,
  latestAiMessageIndex,
  isMessageCollapsed,
  expandMessage,
  collapseMessage,
  getCollapsedPreview,
  canSpeakMessage,
  toggleMessageTts,
  batchCalculateHeights,
  stopMessageTts,
} = useChatMessageUi({ messages, chatMessagesRef: chatRefBag.chatMessagesRef, sessionKey: messageSessionKey })

const {
  paneStyle: chatPaneStyle,
  startResize: onTaskPaneResizeStart,
  resetSize: resetTaskPaneWidth,
  stopResize: stopTaskPaneResize,
} = useResizablePane({
  paneKey: 'chat.task-panel',
  cssVarName: '--chat-right-pane-width',
  orientation: 'vertical',
  invertDelta: true,
  defaultSize: 300,
  minSize: 240,
  maxSize: 420,
  enabled: () => isTaskPaneResizable.value,
})

const quickButtons = computed(() => getIndustryQuickButtons(currentIndustryId.value))
const visibleQuickButtons = computed(() => {
  const list = quickButtons.value || []
  return list.filter((btn) => btn.text !== '测试预览')
})
const inputPlaceholder = computed(() => {
  const preset = getIndustryPreset(currentIndustryId.value)
  return preset.placeholderNormal
})

const canSendMessage = computed(() => !!messageInput.value.trim())
const sendButtonTitle = computed(() => {
  if (isLoading.value) return '可停止回复或发送纠正；已执行的工具不会撤销'
  if (!messageInput.value.trim()) return '请先输入内容'
  return '发送消息'
})
const composerStatusText = computed(() => {
  if (voiceFeedbackText.value) return voiceFeedbackText.value
  if (isLoading.value) return '可停止回复或发送纠正；已执行的工具不会撤销'
  if (!messageInput.value.trim()) return '请输入内容后再发送'
  return ''
})

const sendMessage = async () => {
  const domInput = document.getElementById('messageInput') as HTMLTextAreaElement | null
  const raw = messageInput.value || (domInput && domInput.value) || ''
  const message = raw.trim()
  if (!message) return
  messageInput.value = ''
  await chatSendMessage(message)
}

const {
  officeDockingInputRef,
  officeDockingProcessing,
  officeDockingPanelOpen,
  officeDockingReviewItems,
  triggerOfficeDocking,
  onOfficeDockingFileChange,
  toggleOfficeDockingTarget,
  confirmOfficeDockingReview,
  clearOfficeDockingReview,
} = useChatOfficeDocking({
  addAndSaveMessage,
  stageExcelAnalysisContext,
  sendDatabaseImportMessage: async (message: string) => {
    messageInput.value = message
    await sendMessage()
  },
})

const sendQuick = (text: string) => {
  messageInput.value = text
  void sendMessage()
}

const handleKeyDown = (e: KeyboardEvent) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    void sendMessage()
  }
}

const { onAutoRefreshToolbarChange: _legacyWechatToolbarChange } = useChatViewHost({
  modsStore,
  modsFromStore,
  autoRefreshStarredWechat,
  isTaskPaneResizable,
  messageInput,
  latestAssistantPush,
  syncSessionMessages,
  chatHandleAutoAction,
  sendMessage,
  batchCalculateHeights,
  stopMessageTts,
  cleanupVoiceInput,
  stopTaskPaneResize,
})
void _legacyWechatToolbarChange

const {
  proactiveEnabled,
  proactiveSuggestionsByMessage,
  persistProactiveEnabled,
  pickProactiveSuggestion,
} = useProactiveReplySuggestions({
  messages,
  messageInput,
  isLoading,
  scopeKey: messageSessionKey,
  isStreamingReply,
})

function onProactiveSuggestionsChange(enabled: boolean) {
  persistProactiveEnabled(enabled)
}

function openShipmentRecordsFromAuditTask() {
  window.dispatchEvent(new CustomEvent('xcagi:switch-view', { detail: { view: 'shipment-records' } }))
}

function emitSwitchView(view: string) {
  window.dispatchEvent(new CustomEvent('xcagi:switch-view', { detail: { view } }))
}
</script>

<style scoped>
.chat-composer-status {
  min-height: 18px;
  padding: 4px 2px 0;
  color: var(--app-text-muted, #667085);
  font-size: var(--app-font-size-caption, 12px);
  line-height: 1.4;
}

.chat-composer-status--error {
  color: #b42318;
}

.input-area {
  position: relative;
}
.input-area--dragover {
  outline: 2px dashed var(--xc-color-primary, #0d47a1);
  outline-offset: -2px;
  background: rgba(13, 71, 161, 0.04);
}
.composer-drop-overlay {
  position: absolute;
  inset: 0;
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
  background: rgba(255, 255, 255, 0.72);
  color: var(--xc-color-primary, #0d47a1);
  font-size: var(--app-font-size-caption, 13px);
  font-weight: 600;
}
</style>
