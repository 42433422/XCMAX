<template>
  <div class="chat-view page-view active" id="view-chat" :style="chatPaneStyle">
    <TaskWorkspaceContextBar
      v-if="workspaceMode"
      v-bind="workspaceHeader"
      :action-pending="taskCenterStore.actionPending"
      @control="controlWorkspaceTask"
    />
    <div class="chat-header-actions">
      <ChatQuickActions :buttons="visibleQuickButtons" @quick="sendQuick" />
      <button
        v-if="!isTaskPaneResizable"
        type="button"
        class="quick-btn chat-panel-toggle"
        data-tutorial-id="chat-side-panel-toggle"
        aria-haspopup="dialog"
        aria-controls="chat-side-panel"
        :aria-expanded="mobileChatPanelOpen"
        @click="mobileChatPanelOpen = true"
      >{{ $t('chat.taskTab') }} / {{ $t('chat.conversationTab') }}</button>
    </div>
    <div v-if="cacheError" class="chat-cache-warning chat-composer-status chat-composer-status--error" role="alert">
      {{ cacheError }} <button type="button" class="btn btn-secondary btn-sm" @click="retryMessagesCache">重试本机保存</button>
    </div>
    <div class="chat-container" data-tour="chat-thread">
      <ChatMessageList
        @retry-model="retryFailedModel"
        @recall-edit="recallMessage"
        @reconcile-turn="reconcileTurn"
        @open-original-task="openOriginalTask"
        @confirm-destructive="confirmDestructiveScope"
        :session-key="messageSessionKey"
        :has-earlier="messagesHaveEarlier"
        :loading-earlier="earlierMessagesLoading"
        :earlier-error="earlierMessagesError"
        :load-earlier="loadEarlierMessages"
        :proactive-suggestions="proactiveSuggestionsByMessage"
        @pick-proactive-suggestion="pickProactiveSuggestion"
        :messages="messages"
        @retry-save="retryMessageSave"
        :is-loading="isLoading"
        :is-streaming-reply="isStreamingReply"
        :pending-turn-id="pendingTurnId"
        :stopped-turn-id="stoppedTurnId"
        :loading-progress-text="loadingProgressText"
        :message-heights="messageHeights"
        :latest-ai-message-index="latestAiMessageIndex"
        :playing-msg-idx="playingMsgIdx"
        :is-message-collapsed="isMessageCollapsed"
        :can-collapse-message="canCollapseMessage"
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
        v-model:open="mobileChatPanelOpen"
        :compact="!isTaskPaneResizable"
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
        @remove-task="removeTask"
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
      class="input-area chat-input-area"
      data-tour="chat-input-area"
      :class="{ 'input-area--dragover': composerDragOver }"
      @dragenter.prevent="onComposerDragEnter"
      @dragover.prevent="onComposerDragOver"
      @dragleave.prevent="onComposerDragLeave"
      @drop.prevent="onComposerDrop"
    >
      <div v-if="composerDragOver" class="composer-drop-overlay" role="status">松开以上传附件</div>
      <ChatModelRecovery :scope-key="messageSessionKey" />
      <div
        v-if="artifactStaging.length || multimodalStaging.length || unsupportedStaging.length"
        class="composer-attachments"
        role="list"
        aria-label="待发送附件"
      >
        <span
          v-for="row in artifactStaging"
          :key="row.artifact_id"
          class="composer-attachment"
          role="listitem"
        >
          <FileTypeIcon :name="row.filename" :size="16" />
          <span class="composer-attachment__name" :title="row.filename">{{ row.filename }}</span>
          <button
            type="button"
            class="composer-attachment__remove"
            :aria-label="`移除 ${row.filename}`"
            title="移除"
            @click="removeArtifactFile(row.artifact_id)"
          >
            ×
          </button>
        </span>
        <span
          v-for="(row, index) in multimodalStaging"
          :key="`mm-${index}-${row.filename}`"
          class="composer-attachment"
          role="listitem"
        >
          <FileTypeIcon :name="row.filename" :kind="row.kind" :size="16" />
          <span class="composer-attachment__name" :title="row.filename">{{ row.filename }}</span>
          <button
            type="button"
            class="composer-attachment__remove"
            :aria-label="`移除 ${row.filename}`"
            title="移除"
            @click="removeMultimodalFile(row)"
          >
            ×
          </button>
        </span>
        <span
          v-for="name in unsupportedStaging"
          :key="`unsupported-${name}`"
          class="composer-attachment composer-attachment--skipped"
          role="listitem"
          :title="`${name} 未添加为对话附件`"
        >
          <i class="fa fa-exclamation-triangle" aria-hidden="true"></i>
          <span class="composer-attachment__name">{{ name }}</span>
          <span class="composer-attachment__note">已跳过</span>
          <button
            type="button"
            class="composer-attachment__remove"
            :aria-label="`忽略 ${name}`"
            title="忽略"
            @click="dismissUnsupportedFile(name)"
          >
            ×
          </button>
        </span>
      </div>
      <div v-if="excelSheetOptions.length" class="sheet-link-bar">
        <button type="button" class="sheet-link-btn" :class="{ active: worksheetTemplateOpen || !!linkedExcelSheet || linkedExcelAllSheets }" @click="worksheetTemplateOpen = !worksheetTemplateOpen">
          {{ worksheetTemplateLabel }}
        </button>
        <div v-if="worksheetTemplateOpen" class="sheet-link-picker">
          <button type="button" class="sheet-link-btn" :class="{ active: !linkedExcelSheet && !linkedExcelAllSheets }" @click="clearWorksheetTemplate">不使用模板</button>
          <button type="button" class="sheet-link-btn" :class="{ active: linkedExcelAllSheets }" @click="chooseAllWorksheetTemplates">全部工作表</button>
          <button
            v-for="sheet in excelSheetOptions"
            :key="`${sheet.sheet_index}-${sheet.sheet_name}`"
            type="button"
            class="sheet-link-btn"
            :class="{
              active:
                !linkedExcelAllSheets &&
                linkedExcelSheet &&
                linkedExcelSheet.sheet_name === sheet.sheet_name &&
                linkedExcelSheet.sheet_index === sheet.sheet_index,
            }"
            @click="chooseWorksheetTemplate(sheet)"
          >
            {{ sheet.sheet_name }}
          </button>
        </div>
      </div>
      <div class="chat-speech-controls">
        <ChatSpeechToggle :enabled="ttsEnabled" @update:enabled="setTtsEnabled" />
      </div>
      <Sender
        ref="chatSender"
        v-model="messageInput"
        class="input-wrapper chat-composer"
        variant="updown"
        :auto-size="{ minRows: 1, maxRows: 6 }"
        :placeholder="inputPlaceholder"
        @compositionstart.capture="composerIme.compositionStart"
        @compositionend.capture="composerIme.compositionEnd"
        @keydown.capture="protectComposerEnter"
        @submit="sendMessage"
      >
        <template #prefix>
          <ChatInputToolbar
            :attachment-uploading="attachmentUploading"
            :multimodal-pending-count="multimodalPendingCount"
            :office-docking-processing="officeDockingProcessing"
            @trigger-office-docking="triggerOfficeDocking"
            @attachment-file-change="onAttachmentFileChange"
          />
        </template>
        <template #action-list>
          <div class="composer-primary-actions" @mousedown.stop>
            <EnterpriseIntelligencePicker ref="intelligencePicker" />
            <button
              type="button"
              class="composer-control composer-icon-button voice-call-entry-btn"
              title="语音通话"
              aria-label="语音通话"
              @click="startVoiceCallFromHost"
            >
              <Phone aria-hidden="true" />
            </button>
            <button
              type="button"
              class="composer-control composer-icon-button voice-input-btn"
              :class="voiceButtonClass"
              :disabled="voiceButtonDisabled"
              :title="voiceButtonTitle"
              :aria-label="voiceButtonText"
              data-tutorial-id="chat-voice-push-to-talk"
              @mousedown.prevent="startVoiceRecording"
              @mouseup.prevent="stopVoiceRecording(false)"
              @mouseleave="stopVoiceRecording(true)"
              @touchstart.prevent="startVoiceRecording"
              @touchend.prevent="stopVoiceRecording(false)"
              @touchcancel.prevent="stopVoiceRecording(true)"
            >
              <ElIcon :class="{ 'is-loading': voiceButtonIcon === 'fa-spinner fa-pulse' }" aria-hidden="true">
                <component :is="composerVoiceIcons[voiceButtonIcon]" />
              </ElIcon>
              <span v-if="voiceButtonIcon !== 'fa-microphone'" class="voice-input-btn-label">{{ voiceButtonText }}</span>
            </button>
            <button
              v-if="isLoading"
              type="button"
              class="composer-control composer-icon-button stop-message-btn"
              data-testid="stop-reply"
              aria-label="停止回复"
              title="停止回复"
              @click="stopReply()"
            >
              <CloseBold aria-hidden="true" />
            </button>
            <button
              type="button"
              class="composer-control composer-icon-button send-message-btn"
              id="sendMessageBtn"
              :disabled="!canSendMessage"
              :aria-disabled="!canSendMessage"
              :title="sendButtonTitle"
              :aria-label="isLoading ? '发送纠正' : '发送'"
              @click="sendMessage"
            >
              <Top aria-hidden="true" />
            </button>
          </div>
        </template>
      </Sender>
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
      :accept="intakeAcceptAttribute('office')"
      style="display: none"
      @change="onOfficeDockingFileChange"
    />
    <ChatOfficeDockingReview
      v-if="officeDockingPanelOpen"
      :items="officeDockingReviewItems"
      :processing="officeDockingProcessing"
      @toggle-target="toggleOfficeDockingTarget"
      @pick-template="pickOfficeWorksheetTemplate"
      @confirm="confirmOfficeDockingReview"
      @close="clearOfficeDockingReview"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, inject, watch, onMounted, onBeforeUnmount, onActivated, onDeactivated, nextTick } from 'vue'
import { storeToRefs } from 'pinia'
import { ElIcon } from 'element-plus'
import { CircleClose, CloseBold, Loading, Microphone, Phone, Top, Warning } from '@element-plus/icons-vue'
import { useIndustryStore } from '@/stores/industry'
import { useAgentTaskCenterStore } from '@/stores/agentTaskCenter'
import { showAppToast } from '@/composables/useAppToast'
import { getIndustryPreset, getIndustryQuickButtons } from '@/constants/industryPresets'
import { useRouter } from 'vue-router'
import PaneResizeHandle from '@/components/PaneResizeHandle.vue'
import ChatQuickActions from '@/components/chat/ChatQuickActions.vue'
import ChatMessageList from '@/components/chat/ChatMessageList.vue'
import ChatModelRecovery from '@/components/chat/ChatModelRecovery.vue'
import ChatSidePanel from '@/components/chat/ChatSidePanel.vue'
import ChatInputToolbar from '@/components/chat/ChatInputToolbar.vue'
import ChatSpeechToggle from '@/components/chat/ChatSpeechToggle.vue'
import EnterpriseIntelligencePicker from '@/components/chat/EnterpriseIntelligencePicker.vue'
import Sender from 'vue-element-plus-x/es/Sender/index.js'
import FileTypeIcon from '@/components/common/FileTypeIcon.vue'
import ChatHistoryModal from '@/components/chat/ChatHistoryModal.vue'
import ChatOfficeDockingReview from '@/components/chat/ChatOfficeDockingReview.vue'
import TaskWorkspaceContextBar from '@/components/chat/TaskWorkspaceContextBar.vue'
import { useChatOfficeDocking } from '@/composables/useChatOfficeDocking'
import { intakeAcceptAttribute, isChatWordAttachment } from '@/utils/documentIntake'
import { useResizablePane } from '@/composables/useResizablePane'
import { useModsStore } from '@/stores/mods'
import { useChatView } from '@/composables/useChatView'
import { useChatVoiceInput } from '@/composables/useChatVoiceInput'
import { requestVoiceCallStart, voiceChatBridge } from '@/composables/voiceCallHost'
import { isFailedChatReply, useProactiveReplySuggestions } from '@/composables/useProactiveReplySuggestions'
import { useChatMessageUi } from '@/composables/useChatMessageUi'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { useChatViewHost } from '@/composables/useChatViewHost'
import { startupReadyKey } from '@/composables/useStartupSplash'
import { workflowTaskDotStatusClassForTask, workflowTaskDotTitleForTask } from '@/workflow/coreWorkflowTaskUi'
import { formatTaskTime, formatTaskSourceLabel } from '@/utils/chatTaskLabels'
import { buildChatMessagesKey, buildChatScopedKey, readAiSessionIdFromStorage, resolveChatStorageScope, writeAiSessionIdToStorage } from '@/utils/chatStorageKeys'
import { captureAuthSession } from '@/utils/authSessionCache'
import { readChatComposerDraft, writeChatComposerDraft } from '@/utils/chatComposerDraft'
import { createChatComposerImeGuard } from '@/utils/chatComposerIme'
import { plainTextFromChatHtml } from '@/utils/sanitizeHtml'
import chatApi from '@/api/chat'
import { ApiError } from '@/api/core'
import { isDurableChatScope } from '@/utils/chatSessionRestore'
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
const shellReady = inject(startupReadyKey, null)
const modsStore = useModsStore()
const { mods: modsFromStore } = storeToRefs(modsStore)
const taskCenterStore = useAgentTaskCenterStore()
const industryStore = useIndustryStore()
const { currentIndustryId } = storeToRefs(industryStore)

// Chat toolbar「主动意识」uses proactive suggestions storage — NOT starred WeChat polling.
// Keep WeChat star-refresh forced off here so old checkbox events cannot misfire workflow polls.
const autoRefreshStarredWechat = ref(false)
const isTaskPaneResizable = ref(true)
const mobileChatPanelOpen = ref(false)
onDeactivated(() => { mobileChatPanelOpen.value = false })
function generateSessionId(): string {
  return Date.now().toString(36) + Math.random().toString(36).substr(2)
}

const initialWorkspaceSessionId = resolveWorkspaceSessionId(props)
const openedScope = resolveChatStorageScope()
const openedStoredId = isDurableChatScope(openedScope) ? readAiSessionIdFromStorage() : ''
const currentSessionId = ref(initialWorkspaceSessionId || openedStoredId || generateSessionId())
const messageSessionKey = computed(() => JSON.stringify([currentSessionId.value, modsStore.activeModId, productReadAccountEpoch.value]))
if (!initialWorkspaceSessionId && isDurableChatScope(openedScope) && !openedStoredId) writeAiSessionIdToStorage(currentSessionId.value)
const chatScope = computed(() => resolveChatStorageScope())

const chatViewApi = useChatView({ sessionId: currentSessionId })
const chatRefBag = {
  chatMessagesRef: chatViewApi.chatMessagesRef,
}

const {
  messages,
  messagesHaveEarlier, earlierMessagesLoading, earlierMessagesError, loadEarlierMessages,
  cacheError,
  retryMessagesCache,
  retryMessageSave,
  currentTask,
  orderNumberFetching,
  isLoading,
  isRecalling,
  isStreamingReply,
  pendingTurnId,
  stoppedTurnId,
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
  attachmentUploading,
  multimodalPendingCount,
  multimodalStaging,
  artifactStaging,
  unsupportedStaging,
  removeArtifactFile,
  removeMultimodalFile,
  dismissUnsupportedFile,
  excelSheetOptions,
  linkedExcelSheet,
  linkedExcelAllSheets,
  taskTableColumns,
  taskTableItems,
  taskOrderNumber,
  sendMessage: chatSendMessage,
  retryModelOnly,
  confirmDestructive,
  stopReply,
  confirmWorkflowFromCard,
  cancelWorkflowFromCard,
  confirmTask,
  refetchTaskOrderNumber,
  setCustomOrderNumber,
  cancelTask,
  onAttachmentFileChange,
  bindExcelSheetToChat,
  bindAllExcelSheetsToChat,
  toggleTaskExpanded,
  selectTask,
  setTaskFilter,
  clearTaskHistory,
  removeTask,
  retryTask,
  pauseTask,
  resumeTask,
  approveTask,
  cancelTaskById,
  jumpToTaskMessage,
  refreshHistorySessions,
  restoreLatestOwnedSession,
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

/** 智能对话页只在悬浮球内通话，不展开悬浮窗面板。 */
const startVoiceCallFromHost = () => {
  requestVoiceCallStart({ expandPanel: false })
}

/**
 * 通话轮复用本页的消息与发送通道，语音对话直接出现在当前对话里。
 * 任务工作区与主对话都复用 ChatView；以「最近激活」的实例作为唯一消息源，
 * 避免通话内容写进一个列表、用户却盯着另一个列表。
 */
const registerVoiceChatBridge = () => {
  voiceChatBridge.value = {
    messages,
    send: (text: string) => chatSendMessage(text),
    isLoading,
  }
}
const unregisterVoiceChatBridge = () => {
  if (voiceChatBridge.value?.messages !== messages) return
  voiceChatBridge.value = { messages: null, send: null, isLoading: null }
}
onMounted(registerVoiceChatBridge)
onActivated(registerVoiceChatBridge)
onMounted(() => window.addEventListener('xcagi:retry-last-failed-turn', retryLastFailedTurn))
onBeforeUnmount(unregisterVoiceChatBridge)
onBeforeUnmount(() => window.removeEventListener('xcagi:retry-last-failed-turn', retryLastFailedTurn))

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

// Workspace commands are UI intents, not agent or business execution routes.
// Ignore deactivated keep-alive instances and routed task workspaces.
let workspaceChatActive = true
function isActiveWorkspaceChat() {
  return workspaceChatActive && !workspaceMode.value && router.currentRoute.value.name === 'chat'
}
async function onWorkspaceNewConversation() {
  if (!isActiveWorkspaceChat()) return
  if (isLoading.value || isStreamingReply.value || isExecuting.value || attachmentUploading.value) {
    showAppToast('当前对话或附件仍在处理中，请结束后再新建会话', 'warning')
    return
  }
  try {
    await Promise.resolve(newConversation())
    await nextTick()
    if (isActiveWorkspaceChat()) document.getElementById('messageInput')?.focus({ preventScroll: true })
  } catch {
    showAppToast('新建会话失败，请保留当前内容并重试', 'error')
  }
}
async function onWorkspaceNewTask() {
  if (!isActiveWorkspaceChat()) return
  if (isLoading.value || isStreamingReply.value || isExecuting.value || attachmentUploading.value) {
    showAppToast('当前任务仍在执行或上传中，无法新建任务', 'warning')
    return
  }
  if (messageInput.value.trim() || artifactStaging.value.length || multimodalStaging.value.length ||
    unsupportedStaging.value.length) {
    showAppToast('当前草稿或附件尚未发送，请先处理后再新建任务', 'warning')
    document.getElementById('messageInput')?.focus({ preventScroll: true })
    return
  }
  try {
    await Promise.resolve(newConversation())
    await nextTick()
    if (!isActiveWorkspaceChat()) return
    document.getElementById('messageInput')?.focus({ preventScroll: true })
    showAppToast('请描述任务目标并发送；执行仍按原授权与审批流程进行', 'info')
  } catch {
    showAppToast('新建任务草稿失败，未创建业务任务', 'error')
  }
}
function onWorkspaceOpenSessions() {
  if (!isActiveWorkspaceChat()) return
  showHistoryPanel()
}
onMounted(() => {
  window.addEventListener('xcagi:workspace-new-conversation', onWorkspaceNewConversation)
  window.addEventListener('xcagi:workspace-new-task', onWorkspaceNewTask)
  window.addEventListener('xcagi:workspace-open-sessions', onWorkspaceOpenSessions)
})
onBeforeUnmount(() => {
  window.removeEventListener('xcagi:workspace-new-conversation', onWorkspaceNewConversation)
  window.removeEventListener('xcagi:workspace-new-task', onWorkspaceNewTask)
  window.removeEventListener('xcagi:workspace-open-sessions', onWorkspaceOpenSessions)
})
onDeactivated(() => { workspaceChatActive = false })
onActivated(() => { workspaceChatActive = true })

async function controlWorkspaceTask(action: 'approve' | 'pause' | 'cancel' | 'resume' | 'retry'): Promise<void> {
  await taskCenterStore.controlTask(workspaceTaskId.value, action)
  if (taskCenterStore.error) showAppToast(taskCenterStore.error, 'error', { duration: 8000 })
}

const { approveTaskWithFeedback, approveRunFromChat } = useTaskApprovalFeedback({
  currentSessionId, approveTask, syncSessionMessages,
})

const messageInput = ref('')
const chatSender = ref<{ inputInstance?: HTMLTextAreaElement } | null>(null)
watch(() => chatSender.value?.inputInstance, (input) => {
  if (!input) return
  input.id = 'messageInput'
  input.setAttribute('aria-label', '消息')
  input.setAttribute('aria-describedby', 'chat-composer-status')
}, { flush: 'post' })
// Compose text is scoped to the same account, Mod, and original conversation.
// Never persist file bytes, upload handles, or approval grants with a draft.
const composerDraftKey = computed(() => isDurableChatScope(chatScope.value)
  ? buildChatScopedKey('xcagi_chat_composer_draft_', currentSessionId.value,
    modsStore.activeModId, chatScope.value)
  : '')
let composerDraftTimer: ReturnType<typeof setTimeout> | undefined
const flushComposerDraft = () => {
  if (composerDraftTimer !== undefined) clearTimeout(composerDraftTimer)
  composerDraftTimer = undefined
  writeChatComposerDraft(composerDraftKey.value, messageInput.value)
}
watch(messageInput, (text) => {
  if (composerDraftTimer !== undefined) clearTimeout(composerDraftTimer)
  const key = composerDraftKey.value
  composerDraftTimer = setTimeout(() => writeChatComposerDraft(key, text), 250)
})
watch(composerDraftKey, (key, previous) => {
  if (composerDraftTimer !== undefined) clearTimeout(composerDraftTimer)
  composerDraftTimer = undefined
  if (previous) writeChatComposerDraft(previous, messageInput.value)
  messageInput.value = readChatComposerDraft(key)
}, { flush: 'sync' })
onMounted(() => {
  if (!messageInput.value) messageInput.value = readChatComposerDraft(composerDraftKey.value)
})
onBeforeUnmount(flushComposerDraft)
onDeactivated(flushComposerDraft)
async function recallMessage(index: number) {
  if (isRecalling.value || !window.confirm('撤回这条消息及后续对话，同时撤销可核实的业务操作？原消息将放回输入框。')) return
  const result = await chatViewApi.recallUserMessage(index)
  if (!result.ok) {
    if (result.message) window.alert(result.message)
    return
  }
  messageInput.value = result.text
  if (result.message) showAppToast(result.message, 'info')
  document.getElementById('messageInput')?.focus()
}
async function reconcileTurn(index: number) {
  const result = await chatViewApi.reconcileTurnMessage(index)
  if (!result.ok && result.message) window.alert(result.message)
}
function openOriginalTask(taskId: string) {
  void router.push({ name: 'task-workspace', params: { taskId }, query: { conversation: currentSessionId.value } })
}
function retryFailedModel(payload: { text: string; turnId: string }) {
  if (isRecalling.value) return
  messageInput.value = ''
  void retryModelOnly(payload.text, payload.turnId)
}
/** 侧边栏「模型服务异常」徽标的重试入口：找回最近一次失败轮次并重发。 */
function retryLastFailedTurn() {
  for (let index = messages.value.length - 1; index >= 0; index--) {
    const reply = messages.value[index]
    if (reply.role !== 'ai' || reply.streamingShell) continue
    if (reply.workflowAction !== 'failed' && reply.workflowAction !== 'unknown' && !isFailedChatReply(reply)) continue
    const turnId = String(reply.turnId || '').trim()
    const user = messages.value.slice(0, index).reverse()
      .find(item => item.role === 'user' && (!turnId || item.turnId === turnId))
    if (!turnId || !user) continue
    retryFailedModel({ text: plainTextFromChatHtml(user.content), turnId })
    return
  }
  showAppToast('没有可重试的失败轮次，请重新输入。', 'info')
}
function confirmDestructiveScope(payload: { text: string; idempotencyKey: string }) {
  void confirmDestructive(payload.text, payload.idempotencyKey)
}
const composerDragOver = ref(false)
let composerDragDepth = 0

const COMPOSER_ACCEPT_RE = /\.(xlsx|xlsm|pdf|jpe?g|png|webp|gif|txt|log)$/i
const COMPOSER_ACCEPT_MIME = /^(image\/(jpeg|png|webp|gif)|application\/pdf|text\/plain)/i
/** 拖入文件夹时的递归扫描上限，避免误拖大目录导致卡顿。 */
const COMPOSER_MAX_DROP_FILES = 200

async function collectEntryFiles(entry: FileSystemEntry, out: File[]): Promise<void> {
  if (out.length >= COMPOSER_MAX_DROP_FILES) return
  if (entry.isFile) {
    const file = await new Promise<File | null>((resolve) => {
      (entry as FileSystemFileEntry).file(
        (f) => resolve(f),
        () => resolve(null),
      )
    })
    if (file) out.push(file)
    return
  }
  if (!entry.isDirectory) return
  const reader = (entry as FileSystemDirectoryEntry).createReader()
  for (;;) {
    const batch = await new Promise<FileSystemEntry[]>((resolve) => {
      reader.readEntries(
        (items) => resolve(items),
        () => resolve([]),
      )
    })
    if (!batch.length) return
    for (const child of batch) {
      if (out.length >= COMPOSER_MAX_DROP_FILES) return
      await collectEntryFiles(child, out)
    }
  }
}

async function filesFromDataTransfer(dt: DataTransfer | null): Promise<File[]> {
  if (!dt) return []
  const entries = Array.from(dt.items || [])
    .filter((item) => item.kind === 'file')
    .map((item) => (typeof item.webkitGetAsEntry === 'function' ? item.webkitGetAsEntry() : null))
    .filter((entry): entry is FileSystemEntry => Boolean(entry))
  if (!entries.length) return Array.from(dt.files || [])
  const out: File[] = []
  for (const entry of entries) {
    await collectEntryFiles(entry, out)
    if (out.length >= COMPOSER_MAX_DROP_FILES) break
  }
  return out.length ? out : Array.from(dt.files || [])
}

function isComposerAcceptedFile(file: File): boolean {
  return isChatWordAttachment(file.name) || COMPOSER_ACCEPT_RE.test(file.name) || COMPOSER_ACCEPT_MIME.test(file.type || '')
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
  if (isLoading.value || attachmentUploading.value) return
  const files = await filesFromDataTransfer(e.dataTransfer)
  if (!files.length) return
  const accepted = files.filter(isComposerAcceptedFile)
  if (!accepted.length) {
    await addAndSaveMessage('[附件] 不支持的文件类型，请拖入 Excel、Word（.docx）、图片、PDF 或包含它们的文件夹', 'ai')
    return
  }
  // The picker snapshots these files and applies the existing session/identity guard.
  await onAttachmentFileChange({ target: { files: accepted, value: '' } } as unknown as Event)
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
let restoreGeneration = 0
let restoreActive = true
async function restoreOwnedConversation() {
  const generation = ++restoreGeneration
  const scope = chatScope.value
  const mod = modsStore.activeModId
  const originalSession = currentSessionId.value
  const isOwnerCurrent = captureAuthSession()
  const canApply = () => restoreActive && shellReady?.value !== false && generation === restoreGeneration && isOwnerCurrent()
    && scope === chatScope.value && mod === modsStore.activeModId && !resolveWorkspaceSessionId(props) && !isLoading.value
  if (!isDurableChatScope(scope) || !canApply()) return
  let serverId = ''
  try {
    const data = await chatApi.getActiveConversation()
    const body = data as { conversation_id?: string; data?: { conversation_id?: string } }
    serverId = String(body.conversation_id || body.data?.conversation_id || '').trim()
  } catch {
    // An unavailable active pointer may still have an owned local/history fallback.
  }
  if (!canApply() || currentSessionId.value !== originalSession) return
  if (serverId) {
    currentSessionId.value = serverId
    writeAiSessionIdToStorage(serverId)
    await syncSessionMessages().catch(() => undefined)
    return
  }
  const hasRealTurn = messages.value.some((msg) => {
    const text = plainTextFromChatHtml(msg.content).replace(/\s+/g, ' ').trim()
    return text && (msg.role === 'user' || msg.role === 'task' || !/^(你好，我是|您好！我是)/.test(text))
  })
  if (hasRealTurn) {
    await syncSessionMessages({ isCurrent: canApply }).catch(() => undefined)
  } else {
    try { await restoreLatestOwnedSession?.(canApply) } catch { /* History exposes its own retry state. */ }
  }
}

let assistantRefreshPending = false
function refreshAfterDesktopAssistant() {
  if (!assistantRefreshPending || !document.hasFocus() || !restoreActive || isLoading.value) return
  assistantRefreshPending = false
  void restoreOwnedConversation()
}
function onDesktopAssistantStorage(event: StorageEvent) {
  if (event.storageArea !== localStorage || !event.url || new URL(event.url).pathname !== '/desktop-assistant') return
  const scope = chatScope.value
  const mod = modsStore.activeModId
  if (event.key !== buildChatMessagesKey(currentSessionId.value, mod, scope)
    && event.key !== buildChatScopedKey('ai_session_id_', 'current', mod, scope)) return
  assistantRefreshPending = true
  refreshAfterDesktopAssistant()
}
onMounted(() => {
  if (window.xcagiDesktop) {
    window.addEventListener('storage', onDesktopAssistantStorage)
    window.addEventListener('focus', refreshAfterDesktopAssistant)
  }
  voiceWarmTimer = window.setTimeout(() => {
    void warmVoiceModel()
  }, 2500)
})
watch(() => [chatScope.value, modsStore.activeModId, productReadAccountEpoch.value], (_, previous) => {
  const workspaceSession = resolveWorkspaceSessionId(props)
  if (previous) {
    currentSessionId.value = workspaceSession || readAiSessionIdFromStorage() || generateSessionId()
    if (workspaceSession && isDurableChatScope(chatScope.value) && shellReady?.value !== false) void syncSessionMessages().catch(() => undefined)
  }
  void restoreOwnedConversation()
}, { immediate: true, flush: 'post' })
// Optional restoration must not replace the required startup read's scope or messages.
watch(() => shellReady?.value, () => { void restoreOwnedConversation() }, { flush: 'sync' })
watch(isLoading, (loading) => {
  if (loading) restoreGeneration += 1
  else refreshAfterDesktopAssistant()
}, { flush: 'sync' })
function retireRestore() {
  restoreActive = false
  restoreGeneration += 1
  window.clearTimeout(voiceWarmTimer)
}
onBeforeUnmount(() => {
  retireRestore()
  window.removeEventListener('storage', onDesktopAssistantStorage)
  window.removeEventListener('focus', refreshAfterDesktopAssistant)
})
onDeactivated(retireRestore)
onActivated(() => {
  if (!restoreActive) { restoreActive = true; void restoreOwnedConversation() }
})

const {
  messageHeights,
  playingMsgIdx,
  latestAiMessageIndex,
  isMessageCollapsed,
  canCollapseMessage,
  expandMessage,
  collapseMessage,
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

const canSendMessage = computed(() => !isRecalling.value && !!messageInput.value.trim())
const sendButtonTitle = computed(() => {
  if (isRecalling.value) return '正在撤回操作'
  if (isLoading.value) return '可停止回复或发送纠正；已执行的工具不会撤销'
  if (!messageInput.value.trim()) return '请先输入内容'
  return '发送消息'
})
const composerStatusText = computed(() => {
  if (voiceFeedbackText.value) return voiceFeedbackText.value
  if (isRecalling.value) return '正在撤回操作…'
  if (isLoading.value) return '可停止回复或发送纠正；已执行的工具不会撤销'
  return ''
})

const composerVoiceIcons = {
  'fa-microphone': Microphone,
  'fa-stop-circle': CircleClose,
  'fa-spinner fa-pulse': Loading,
  'fa-exclamation-circle': Warning,
}

const composerIme = createChatComposerImeGuard()
const sendMessage = async () => {
  if (isRecalling.value || composerIme.composing) return
  const domInput = document.getElementById('messageInput') as HTMLTextAreaElement | null
  const raw = messageInput.value || (domInput && domInput.value) || ''
  const message = raw.trim()
  if (!message) return
  restoreGeneration += 1
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
  pickOfficeWorksheetTemplate,
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

const worksheetTemplateOpen = ref(false)
const worksheetTemplateLabel = computed(() => {
  if (linkedExcelAllSheets.value) return '全部工作表'
  if (linkedExcelSheet.value?.sheet_name) return String(linkedExcelSheet.value.sheet_name)
  return excelSheetOptions.value.length ? '选择工作表模板' : '暂无可选模板'
})
function clearWorksheetTemplate() {
  linkedExcelSheet.value = null
  linkedExcelAllSheets.value = false
  worksheetTemplateOpen.value = false
}
function chooseWorksheetTemplate(sheet: { sheet_name: string; sheet_index: number }) {
  worksheetTemplateOpen.value = false
  void bindExcelSheetToChat(sheet)
}
function chooseAllWorksheetTemplates() {
  worksheetTemplateOpen.value = false
  void bindAllExcelSheetsToChat()
}

const sendQuick = (text: string) => {
  // 顶部快捷按钮只填入输入框，由用户确认后再发送，避免误触直接执行。
  messageInput.value = text
  void nextTick(() => {
    const el = document.getElementById('messageInput') as HTMLTextAreaElement | null
    if (!el) return
    el.focus()
    el.setSelectionRange(text.length, text.length)
  })
}

function protectComposerEnter(event: KeyboardEvent) {
  if (event.target !== chatSender.value?.inputInstance || event.key !== 'Enter') return
  // Sender processes Enter itself. Keep native newline and protect interrupted IME composition.
  if (composerIme.shouldSuppressEnter(event) || event.shiftKey || event.ctrlKey || event.altKey || event.metaKey) {
    event.stopPropagation()
  }
}

const { onAutoRefreshToolbarChange: _legacyWechatToolbarChange } = useChatViewHost({
  pageScopeKey: () => messageSessionKey.value,
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

const intelligencePicker = ref<{ level: number | null } | null>(null)
const {
  proactiveSuggestionsByMessage,
  pickProactiveSuggestion,
} = useProactiveReplySuggestions({
  enterpriseLevel: computed(() => intelligencePicker.value?.level ?? null),
  messages,
  messageInput,
  isLoading,
  scopeKey: messageSessionKey,
  isStreamingReply,
})

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

.chat-view .chat-composer :deep(.el-sender),
.chat-view .chat-composer :deep(.el-sender:focus-within) {
  border-radius: 14px;
  background: var(--xc-color-surface);
  box-shadow: var(--xc-shadow-sm);
  border-color: transparent;
}

.chat-view .chat-composer :deep(.el-sender::after) { display: none; }

.chat-composer :deep(.el-sender .el-sender-content) { padding: 10px 12px 8px; gap: 7px; }
.chat-composer :deep(.el-sender-updown-wrap) {
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 12px;
}

.composer-primary-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  align-items: center;
  gap: 6px;
}

.chat-composer :deep(.el-sender .el-sender-content .el-sender-input .el-textarea__inner) {
  padding: 7px 3px;
  font-size: 16px;
  line-height: 1.55;
  caret-color: var(--xc-color-primary);
}

.chat-composer :deep(.el-textarea__inner:focus-visible) {
  outline: none;
  box-shadow: none;
}

.composer-attachments {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 4px 2px;
  max-height: 96px;
  overflow-y: auto;
}

.composer-attachment {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 240px;
  padding: 2px 4px 2px 8px;
  border: 1px solid var(--app-border-subtle, #d0d5dd);
  border-radius: 999px;
  background: var(--app-surface-muted, #f5f7fa);
  color: var(--app-text, #344054);
  font-size: var(--app-font-size-caption, 12px);
  line-height: 1.6;
}

.composer-attachment__name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.composer-attachment__remove {
  border: none;
  background: transparent;
  color: var(--app-text-muted, #667085);
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
  padding: 0 2px;
}

.composer-attachment__remove:hover {
  color: #b42318;
}

.composer-attachment--skipped {
  border-color: #f7c948;
  background: #fffaeb;
  color: #93370d;
}

.composer-attachment__note {
  flex: none;
  color: #93370d;
  font-size: 11px;
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
