<template>
  <div class="right-panel">
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
        :class="{ 'panel-tab--active': activeTab === 'conversation' }"
        @click="activeTab = 'conversation'"
      >
        {{ $t('chat.conversationTab') }}
      </button>
    </div>

    <ChatTaskPanel
      v-if="activeTab === 'task'"
      :current-task="currentTask"
      :task-list="taskList"
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
      @toggle-task-expanded="(id) => $emit('toggle-task-expanded', id)"
      @select-task="(task) => $emit('select-task', task)"
      @open-shipment-records="$emit('open-shipment-records')"
      @jump-to-task-message="(task) => $emit('jump-to-task-message', task)"
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
      @new="$emit('new-conversation')"
      @refresh="$emit('show-history')"
      @clear="$emit('clear-history-sessions')"
      @load="(sessionId) => $emit('load-session', sessionId)"
      @rename="(sessionId, title) => $emit('rename-session', sessionId, title)"
      @delete="(sessionId) => $emit('delete-session', sessionId)"
    />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ShipmentTask } from '@/composables/useShipmentTask'
import type { TaskFilter, TaskItem } from '@/composables/useChatPersistence'
import type { HistorySessionItem } from '@/composables/useChatSessionHistory'
import ChatTaskPanel from './ChatTaskPanel.vue'
import ChatConversationPanel from './ChatConversationPanel.vue'

defineOptions({ name: 'ChatSidePanel' })

useI18n()

const props = defineProps<{
  currentTask: ShipmentTask | null
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
  historyError: string
}>()

defineEmits<{
  'confirm-task': []
  'cancel-task': []
  'refetch-order-number': []
  'set-custom-order-number': [value: string]
  'shipment-download-click': []
  'start-print': []
  'switch-view': [view: string]
  'set-task-filter': [filter: TaskFilter]
  'clear-task-history': []
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
  'show-history': []
  'clear-history-sessions': []
  'load-session': [sessionId: string]
  'rename-session': [sessionId: string, title: string]
  'delete-session': [sessionId: string]
}>()

const activeTab = ref<'task' | 'conversation'>(props.currentTask || props.taskList.length ? 'task' : 'conversation')
</script>

<style scoped>
.panel-header-tabs {
  display: flex;
  gap: 6px;
  align-items: center;
  padding: 10px 12px;
}

.panel-tab {
  flex: 1;
  border: 1px solid transparent;
  background: transparent;
  color: var(--app-text-muted, #64748b);
  border-radius: 8px;
  padding: 7px 10px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition:
    background 150ms ease,
    color 150ms ease,
    border-color 150ms ease;
}

.panel-tab:hover {
  background: rgba(0, 0, 0, 0.04);
  color: var(--app-text-strong, #1f2329);
}

.panel-tab--active {
  background: rgba(0, 82, 217, 0.08);
  color: var(--app-interactive, #0052d9);
  border-color: rgba(0, 82, 217, 0.18);
}
</style>