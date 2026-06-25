<template>
  <div class="chat-view page-view active" id="view-chat">
    <ChatQuickActions :buttons="visibleQuickButtons" @quick="sendQuick" />
    <div class="chat-container" data-tour="chat-thread" :style="chatPaneStyle">
      <ChatMessageList
        :messages="messages"
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
      />
      <div v-if="isTaskPaneResizable" class="chat-pane-handle-slot">
        <PaneResizeHandle
          orientation="vertical"
          label="调整任务面板宽度"
          @resize-start="onTaskPaneResizeStart"
          @reset="resetTaskPaneWidth"
        />
      </div>
      <ChatTaskPanel
        :current-task="currentTask"
        :task-list="taskList"
        :filtered-task-list="filteredTaskList"
        :expanded-task-ids="expandedTaskIds"
        :task-filter="taskFilter"
        :is-pro-mode="isProMode"
        :pro-runtime-task="proRuntimeTask"
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
        @open-shipment-records="openShipmentRecordsFromAuditTask"
        @jump-to-task-message="jumpToTaskMessage"
        @retry-task="retryTask"
        @cancel-task-by-id="cancelTaskById"
        @copy-assistant-push="copyAssistantPushContent"
        @open-assistant-float="openAssistantFloatFromTaskPanel"
      />
    </div>
    <div class="input-area" data-tour="chat-input-area">
      <ChatInputToolbar
        :excel-analyze-uploading="excelAnalyzeUploading"
        :multimodal-pending-count="multimodalPendingCount"
        :client-mode-tiers-ui-enabled="clientModeTiersUiEnabled"
        :pro-intent-experience-enabled="proIntentExperienceEnabled"
        :auto-refresh-starred-wechat="autoRefreshStarredWechat"
        :tts-enabled="ttsEnabled"
        :excel-analyze-input-ref="chatRefBag.excelAnalyzeInputRef"
        @new-conversation="newConversation"
        @show-history="showHistoryPanel"
        @trigger-upload="triggerUpload"
        @excel-file-change="onExcelAnalyzeFileChange"
        @pro-intent-change="onProIntentToolbarChange"
        @auto-refresh-change="onAutoRefreshToolbarChange"
        @toggle-tts="setTtsEnabled"
      />
      <div v-if="excelSheetOptions.length" class="sheet-link-bar">
        <span class="sheet-link-label">关联工作表：</span>
        <button
          class="sheet-link-btn"
          :class="{ active: linkedExcelAllSheets }"
          @click="bindAllExcelSheetsToChat"
        >
          全部（{{ excelSheetOptions.length }}）
        </button>
        <button
          v-for="sheet in excelSheetOptions"
          :key="`${sheet.sheet_index}-${sheet.sheet_name}`"
          class="sheet-link-btn"
          :class="{ active: !linkedExcelAllSheets && linkedExcelSheet && linkedExcelSheet.sheet_name === sheet.sheet_name && linkedExcelSheet.sheet_index === sheet.sheet_index }"
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
        <button
          class="btn btn-primary send-message-btn"
          id="sendMessageBtn"
          :disabled="isLoading"
          @click="sendMessage"
        >
          {{ isLoading ? '发送中...' : '发送' }}
        </button>
      </div>
    </div>
    <ChatHistoryModal
      :show="showHistory"
      :history-sessions="historySessions"
      :history-loading="historyLoading"
      :history-error="historyError"
      :current-session-id="currentSessionId"
      :format-task-time="formatTaskTime"
      @close="showHistory = false"
      @refresh="showHistoryPanel"
      @clear="clearHistorySessions"
      @load-session="loadSession"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useIndustryStore } from '@/stores/industry'
import { getIndustryPreset, getIndustryQuickButtons } from '@/constants/industryPresets'
import { isClientModeTiersUiEnabled, PRO_INTENT_EXPERIENCE_KEY } from '@/constants/clientModeTiers'
import { useRouter } from 'vue-router'
import PaneResizeHandle from '@/components/PaneResizeHandle.vue'
import ChatQuickActions from '@/components/chat/ChatQuickActions.vue'
import ChatMessageList from '@/components/chat/ChatMessageList.vue'
import ChatTaskPanel from '@/components/chat/ChatTaskPanel.vue'
import ChatInputToolbar from '@/components/chat/ChatInputToolbar.vue'
import ChatHistoryModal from '@/components/chat/ChatHistoryModal.vue'
import { useResizablePane } from '@/composables/useResizablePane'
import { useModsStore } from '@/stores/mods'
import { useChatView } from '@/composables/useChatView'
import { useChatVoiceInput } from '@/composables/useChatVoiceInput'
import { useChatMessageUi } from '@/composables/useChatMessageUi'
import { useChatViewHost } from '@/composables/useChatViewHost'
import { workflowTaskDotStatusClassForTask, workflowTaskDotTitleForTask } from '@/workflow/coreWorkflowTaskUi'
import { formatTaskTime, formatTaskSourceLabel } from '@/utils/chatTaskLabels'
import { readAiSessionIdFromStorage, writeAiSessionIdToStorage } from '@/utils/xcagiStorageKeys'

const router = useRouter()
const modsStore = useModsStore()
const { mods: modsFromStore } = storeToRefs(modsStore)
const industryStore = useIndustryStore()
const { currentIndustryId } = storeToRefs(industryStore)

const clientModeTiersUiEnabled = isClientModeTiersUiEnabled()
const autoRefreshStarredWechat = ref(localStorage.getItem('xcagi_auto_refresh_starred_wechat') !== '0')
const proIntentExperienceEnabled = ref(
  clientModeTiersUiEnabled && localStorage.getItem(PRO_INTENT_EXPERIENCE_KEY) === '1',
)
const isTaskPaneResizable = ref(true)

function generateSessionId(): string {
  return Date.now().toString(36) + Math.random().toString(36).substr(2)
}

const _storedSessionId = readAiSessionIdFromStorage()
const currentSessionId = ref(_storedSessionId || generateSessionId())
if (!_storedSessionId) writeAiSessionIdToStorage(currentSessionId.value)

const chatViewApi = useChatView({ sessionId: currentSessionId, proIntentExperienceEnabled })
const chatRefBag = {
  chatMessagesRef: chatViewApi.chatMessagesRef,
  excelAnalyzeInputRef: chatViewApi.excelAnalyzeInputRef,
}

const {
  messages,
  currentTask,
  orderNumberFetching,
  isLoading,
  isStreamingReply,
  isExecuting,
  latestAssistantPush,
  proRuntimeTask,
  taskList,
  filteredTaskList,
  expandedTaskIds,
  taskFilter,
  showHistory,
  historySessions,
  historyLoading,
  historyError,
  pushCopied,
  loadingProgressText,
  excelAnalyzeUploading,
  multimodalPendingCount,
  excelSheetOptions,
  linkedExcelSheet,
  linkedExcelAllSheets,
  isProMode,
  taskTableColumns,
  taskTableItems,
  taskOrderNumber,
  sendMessage: chatSendMessage,
  confirmTask,
  refetchTaskOrderNumber,
  setCustomOrderNumber,
  cancelTask,
  showTaskConfirm,
  triggerUpload,
  onExcelAnalyzeFileChange,
  bindExcelSheetToChat,
  bindAllExcelSheetsToChat,
  toggleTaskExpanded,
  setTaskFilter,
  clearTaskHistory,
  retryTask,
  cancelTaskById,
  jumpToTaskMessage,
  showHistoryPanel,
  loadSession,
  clearHistorySessions,
  newConversation,
  handleShipmentDownloadClick,
  startPrintFromTaskCard,
  copyAssistantPushContent,
  openAssistantFloatFromTaskPanel,
  syncProModeState,
  syncSessionMessages,
  handleAutoAction: chatHandleAutoAction,
  ttsEnabled,
  setTtsEnabled,
} = chatViewApi

const messageInput = ref('')

const {
  voiceButtonDisabled,
  voiceButtonClass,
  voiceButtonIcon,
  voiceButtonText,
  voiceButtonTitle,
  startVoiceRecording,
  stopVoiceRecording,
  cleanupVoiceInput,
} = useChatVoiceInput({ messageInput, isLoading })

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
} = useChatMessageUi({ messages, chatMessagesRef: chatRefBag.chatMessagesRef })

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
  if (isProMode.value) return list
  return list.filter((btn) => btn.text !== '测试预览')
})
const inputPlaceholder = computed(() => {
  const preset = getIndustryPreset(currentIndustryId.value)
  return isProMode.value ? preset.placeholderPro : preset.placeholderNormal
})

const sendMessage = async () => {
  const domInput = document.getElementById('messageInput') as HTMLTextAreaElement | null
  const raw = messageInput.value || (domInput && domInput.value) || ''
  const message = raw.trim()
  if (!message || isLoading.value) return
  messageInput.value = ''
  await chatSendMessage(message)
}

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

const { onProIntentToolbarChange, onAutoRefreshToolbarChange } = useChatViewHost({
  router,
  modsStore,
  modsFromStore,
  clientModeTiersUiEnabled,
  proIntentExperienceEnabled,
  autoRefreshStarredWechat,
  isTaskPaneResizable,
  messageInput,
  isProMode,
  currentTask,
  proRuntimeTask,
  latestAssistantPush,
  syncProModeState,
  syncSessionMessages,
  chatHandleAutoAction,
  sendMessage,
  batchCalculateHeights,
  stopMessageTts,
  cleanupVoiceInput,
  stopTaskPaneResize,
})

function openShipmentRecordsFromAuditTask() {
  window.dispatchEvent(new CustomEvent('xcagi:switch-view', { detail: { view: 'shipment-records' } }))
}

function emitSwitchView(view: string) {
  window.dispatchEvent(new CustomEvent('xcagi:switch-view', { detail: { view } }))
}
</script>
