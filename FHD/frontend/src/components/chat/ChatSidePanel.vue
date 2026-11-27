<template>
  <component
    :is="compact ? ElDrawer : 'div'"
    :class="compact ? 'chat-side-drawer' : 'chat-side-panel-host'"
    v-bind="compact ? { modelValue: open, appendToBody: true, direction: 'rtl', title: `${$t('chat.taskTab')} / ${$t('chat.conversationTab')}`, size: 'min(92vw, 420px)' } : {}"
    @update:model-value="$emit('update:open', $event)"
  >
  <div id="chat-side-panel" class="right-panel">
    <div class="panel-header panel-header-tabs" role="tablist">
      <button
        type="button"
        class="panel-tab"
        role="tab"
        :aria-selected="activeTab === 'task'"
        :class="{ 'panel-tab--active': activeTab === 'task' }"
        @click="activeTab = 'task'"
      >
        {{ $t('chat.taskTab') }}
      </button>
      <button
        type="button"
        class="panel-tab"
        role="tab"
        :aria-selected="activeTab === 'conversation'"
        data-tutorial-id="chat-conversation-tab"
        :class="{ 'panel-tab--active': activeTab === 'conversation' }"
        @click="activateConversationTab"
      >
        {{ $t('chat.conversationTab') }}
      </button>
    </div>

    <ChatTaskPanel
      v-if="activeTab === 'task'"
      :current-task="currentTask"
      :task-list="taskList"
      :task-control-states="taskControlStates"
      :task-sync-state="taskSyncState"
      @refresh-tasks="$emit('refresh-tasks')"
      :filtered-task-list="filteredTaskList"
      :active-task-id="activeTaskId"
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
      :workflow-task-dot-status-class="workflowTaskDotStatusClass"
      :workflow-task-dot-title="workflowTaskDotTitle"
      @confirm-task="$emit('confirm-task')"
      @cancel-task="$emit('cancel-task')"
      @refetch-order-number="$emit('refetch-order-number')"
      @set-custom-order-number="(value) => $emit('set-custom-order-number', value)"
      @shipment-download-click="$emit('shipment-download-click')"
      @start-print="$emit('start-print')"
      @switch-view="(view) => $emit('switch-view', view)"
      @set-task-filter="(filter) => $emit('set-task-filter', filter)"
      @clear-task-history="$emit('clear-task-history')"
      @remove-task="(id) => $emit('remove-task', id)"
      @toggle-task-expanded="(id) => $emit('toggle-task-expanded', id)"
      @select-task="(task) => $emit('select-task', task)"
      @open-shipment-records="$emit('open-shipment-records')"
      @jump-to-task-message="(task) => { $emit('jump-to-task-message', task); $emit('update:open', false) }"
      @retry-task="(id) => $emit('retry-task', id)"
      @pause-task="(id) => $emit('pause-task', id)"
      @resume-task="(id) => $emit('resume-task', id)"
      @approve-task="(id) => $emit('approve-task', id)"
      @cancel-task-by-id="(id) => $emit('cancel-task-by-id', id)"
      @copy-assistant-push="$emit('copy-assistant-push')"
      @open-assistant-float="$emit('open-assistant-float')"
    />

    <ChatConversationPanel
      v-else
      :sessions="historySessions"
      :current-session-id="currentSessionId"
      :loading="historyLoading"
      :error="historyError"
      :has-more="historyHasMore"
      :loading-more="historyLoadingMore"
      @load-more="$emit('load-more-history')"
      @new="$emit('new-conversation'); $emit('update:open', false)"
      @refresh="$emit('refresh-history')"
      @clear="$emit('clear-history-sessions')"
      @load="(sessionId) => { $emit('load-session', sessionId); $emit('update:open', false) }"
      @rename="(sessionId, title) => $emit('rename-session', sessionId, title)"
      @delete="(sessionId) => $emit('delete-session', sessionId)"
    />
  </div>
  </component>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { ElDrawer } from 'element-plus'
import 'element-plus/theme-chalk/base.css'
import 'element-plus/theme-chalk/el-overlay.css'
import 'element-plus/theme-chalk/el-drawer.css'
import { useI18n } from 'vue-i18n'
import type { ShipmentTask } from '@/composables/useShipmentTask'
import type { TaskFilter, TaskItem } from '@/composables/useChatPersistence'
import type { TaskControlState, TaskSyncState } from '@/composables/useAgentTaskWorkspace'
import type { HistorySessionItem } from '@/composables/useChatSessionHistory'
import ChatTaskPanel from './ChatTaskPanel.vue'
import ChatConversationPanel from './ChatConversationPanel.vue'

defineOptions({ name: 'ChatSidePanel' })

useI18n()

const props = defineProps<{
  compact?: boolean
  open?: boolean
  currentTask: ShipmentTask | null
  taskControlStates?: Record<string, TaskControlState>
  taskSyncState?: TaskSyncState
  taskList: TaskItem[]
  filteredTaskList: TaskItem[]
  activeTaskId: string
  expandedTaskIds: string[]
  taskFilter: TaskFilter
  latestAssistantPush: { title: string; description: string } | null
  pushCopied: boolean
  orderNumberFetching: boolean
  isExecuting: boolean
  taskTableColumns: string[]
  taskTableItems: Array<Record<string, unknown>>
  taskOrderNumber: string
  formatTaskTime: (ts: number) => string
  formatTaskSourceLabel: (source: string) => string
  workflowTaskDotStatusClass: (task: TaskItem) => string
  workflowTaskDotTitle: (task: TaskItem) => string
  historySessions: HistorySessionItem[]
  currentSessionId: string
  historyLoading: boolean
  historyHasMore?: boolean
  historyLoadingMore?: boolean
  historyError: string
}>()

const emit = defineEmits<{
  'update:open': [open: boolean]
  'refresh-tasks': []
  'confirm-task': []
  'cancel-task': []
  'refetch-order-number': []
  'set-custom-order-number': [value: string]
  'shipment-download-click': []
  'start-print': []
  'switch-view': [view: string]
  'set-task-filter': [filter: TaskFilter]
  'clear-task-history': []
  'remove-task': [id: string]
  'toggle-task-expanded': [id: string]
  'select-task': [task: TaskItem]
  'open-shipment-records': []
  'jump-to-task-message': [task: TaskItem]
  'retry-task': [id: string]
  'pause-task': [id: string]
  'resume-task': [id: string]
  'approve-task': [id: string]
  'cancel-task-by-id': [id: string]
  'copy-assistant-push': []
  'open-assistant-float': []
  'new-conversation': []
  'load-more-history': []
  'refresh-history': []
  'clear-history-sessions': []
  'load-session': [sessionId: string]
  'rename-session': [sessionId: string, title: string]
  'delete-session': [sessionId: string]
}>()

const activeTab = ref<'task' | 'conversation'>(props.currentTask || props.taskList.length ? 'task' : 'conversation')
watch(() => props.compact, (compact) => { if (!compact) emit('update:open', false) })

function activateConversationTab() {
  activeTab.value = 'conversation'
  emit('refresh-history')
}

onMounted(() => {
  if (activeTab.value === 'conversation') emit('refresh-history')
})
</script>

<style scoped>
.chat-side-panel-host { display: contents; }
:global(.chat-side-drawer .el-drawer__body) { display: flex; min-height: 0; padding: 0 0 env(safe-area-inset-bottom, 0px); }
:global(.chat-side-drawer .el-drawer__header) { margin-bottom: 0; padding: max(8px, env(safe-area-inset-top, 0px)) 12px 8px; }
:global(.chat-side-drawer .el-drawer__close-btn) { min-width: 44px; min-height: 44px; align-items: center; justify-content: center; }
.chat-side-drawer .right-panel { flex: 1; width: 100%; min-width: 0; max-width: none; border: 0; border-radius: 0; }
.chat-side-drawer .panel-tab { min-height: 44px; }

.panel-header-tabs {
  display: flex;
  gap: 12px;
  padding: 0 10px;
}

.panel-tab {
  flex: 1;
  min-height: 40px;
  margin-bottom: -1px;
  border: 0;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--app-text-muted, #64748b);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.panel-tab:hover {
  color: var(--app-text-strong, #1f2329);
}

.panel-tab--active {
  color: var(--app-interactive, #0052d9);
  border-bottom-color: currentColor;
}

.panel-tab:focus-visible {
  outline: 2px solid var(--app-interactive, #0052d9);
  outline-offset: -3px;
}
</style>
