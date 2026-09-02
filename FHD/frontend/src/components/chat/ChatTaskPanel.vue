<template>
  <div class="panel-content panel-content-task" id="taskPanel">
      <div class="task-panel-body">
        <template v-if="currentTask">
          <div class="task-card" :class="{ 'excel-import-task': currentTask?.type === 'excel_import' }">
            <div class="task-header">{{ normalizeTaskDisplayText(currentTask.title) }}</div>
            <div class="task-description">{{ normalizeTaskDisplayText(currentTask.description) }}</div>
            <div v-if="currentTask?.type === 'excel_import' && !currentTask?.completed" class="excel-import-preview">
              <div class="excel-import-stats">
                <div class="stat-item">
                  <span class="stat-label">{{ $t('chat.pendingImportRecords') }}</span>
                  <span class="stat-value">{{ currentTask?.payload?.params?.record_count || 0 }} {{ $t('chat.recordUnit') }}</span>
                </div>
              </div>
              <div class="excel-import-hint" style="margin-top:var(--app-space-sm);color:var(--app-text-caption);font-size:var(--app-font-size-caption);">
                {{ $t('chat.excelImportHint') }}
              </div>
            </div>
            <div
              v-if="currentTask?.type === 'shipment_generate' && !currentTask?.completed"
              class="task-order-number-row"
            >
              <span>{{ $t('chat.orderNumber') }}</span>
              <input
                v-model="customOrderNumberModel"
                type="text"
                class="form-control form-control-sm"
                style="max-width:180px;height:28px;"
                :placeholder="$t('chat.orderNumberPlaceholder')"
              >
              <button
                type="button"
                class="btn btn-secondary btn-sm"
                :disabled="orderNumberFetching || isExecuting"
                :title="$t('chat.refetchOrderNumberTitle')"
                @click="$emit('refetch-order-number')"
              >
                {{ orderNumberFetching ? $t('chat.fetchingOrderNumber') : $t('chat.fetchOrderNumber') }}
              </button>
            </div>
            <div v-else-if="taskOrderNumber" style="margin-top:6px;color:var(--app-text-secondary);font-size:var(--app-font-size-caption);">
              {{ $t('chat.orderNumber') }}{{ taskOrderNumber }}
            </div>
            <table v-if="currentTask.items && currentTask.items.length > 0" class="data-table" style="margin-top:10px;">
              <thead>
                <tr>
                  <th v-for="(key, idx) in taskTableColumns" :key="idx">
                    {{ key }}
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(item, iIdx) in taskTableItems" :key="iIdx">
                  <td v-for="(key, vIdx) in taskTableColumns" :key="vIdx">
                    {{ item[key] }}
                  </td>
                </tr>
              </tbody>
            </table>
            <div v-if="!currentTask.completed" class="task-actions">
              <button class="btn btn-success btn-sm" data-action="confirm-task" @click="$emit('confirm-task')" :disabled="isExecuting">
                {{ isExecuting ? $t('chat.executing') : (currentTask?.type === 'excel_import' ? $t('chat.confirmImport') : $t('chat.confirmExecute')) }}
              </button>
              <button class="btn btn-secondary btn-sm" data-action="cancel-task" @click="$emit('cancel-task')" :disabled="isExecuting">
                {{ currentTask?.type === 'excel_import' ? $t('chat.cancelImport') : $t('chat.cancel') }}
              </button>
            </div>
            <div v-else class="task-actions">
              <a
                v-if="currentTask.downloadUrl"
                class="btn btn-primary btn-sm"
                :href="currentTask.downloadUrl"
                download
                @click="$emit('shipment-download-click')"
              >
                {{ $t('chat.downloadShipment') }}
              </a>
              <button
                v-if="currentTask?.type === 'shipment_generate'"
                type="button"
                class="btn btn-success btn-sm"
                data-action="start-print"
                @click="$emit('start-print')"
              >
                {{ $t('chat.startPrint') }}
              </button>
              <button
                v-if="currentTask?.type === 'excel_import' && currentTask?.completed"
                type="button"
                class="btn btn-primary btn-sm"
                data-action="view-products"
                @click="$emit('switch-view', 'products')"
              >
                {{ $t('chat.viewProducts') }}
              </button>
              <button class="btn btn-secondary btn-sm" data-action="close-task" @click="$emit('cancel-task')">{{ $t('chat.close') }}</button>
            </div>
          </div>
        </template>
        <template v-if="taskList.length">
          <div class="task-toolbar" :class="{ 'task-toolbar-below-card': !!currentTask }">
            <div class="task-filters">
              <button class="task-filter-btn" :class="{ active: taskFilter === 'all' }" @click="$emit('set-task-filter', 'all')">{{ $t('chat.filterAll') }}</button>
              <button class="task-filter-btn" :class="{ active: taskFilter === 'running' }" @click="$emit('set-task-filter', 'running')">{{ $t('chat.filterRunning') }}</button>
              <button class="task-filter-btn" :class="{ active: taskFilter === 'blocked' }" @click="$emit('set-task-filter', 'blocked')">{{ $t('chat.filterBlocked') }}</button>
              <button class="task-filter-btn" :class="{ active: taskFilter === 'success' }" @click="$emit('set-task-filter', 'success')">{{ $t('chat.filterSuccess') }}</button>
              <button class="task-filter-btn" :class="{ active: taskFilter === 'failed' }" @click="$emit('set-task-filter', 'failed')">{{ $t('chat.filterFailed') }}</button>
            </div>
            <button class="btn btn-secondary btn-sm" @click="$emit('clear-task-history')">{{ $t('chat.clearTaskHistory') }}</button>
          </div>
          <div class="task-list" data-tutorial-id="task-workspace-list">
            <div
              v-for="task in filteredTaskList"
              :key="task.id"
              class="task-list-item"
              :class="{
                'task-list-item-active': activeTaskId === task.id,
                'task-list-item-workflow-collapsed':
                  task.type === 'workflow_employee' && !expandedTaskIds.includes(task.id),
              }"
            >
              <button
                type="button"
                class="task-list-main"
                :aria-expanded="expandedTaskIds.includes(task.id)"
                @click="$emit('select-task', task)"
              >
                <span
                  class="task-dot"
                  :class="`status-${workflowTaskDotStatusClass(task)}`"
                  :title="normalizeTaskDisplayText(workflowTaskDotTitle(task))"
                />
                <span class="task-list-title">{{ normalizeTaskDisplayText(task.title) }}</span>
                <span
                  v-if="task.type === 'workflow_employee'"
                  class="task-list-chevron"
                  aria-hidden="true"
                >{{ expandedTaskIds.includes(task.id) ? '▼' : '▶' }}</span>
                <span class="task-list-time">{{ formatTaskTime(task.updatedAt) }}</span>
              </button>
              <div
                v-if="task.type !== 'workflow_employee' || expandedTaskIds.includes(task.id)"
                class="task-list-meta"
              >
                <span>{{ formatTaskSourceLabel(task.source) }}</span>
                <span
                  v-if="typeof task.progress === 'number' && task.status !== 'failed' && task.status !== 'cancelled' && !(task.type === 'workflow_employee' && task.payload?.workflowProgressStarted === false)"
                >{{ $t('chat.progress', { pct: task.progress }) }}</span>
                <span v-if="task.stage">{{ normalizeTaskDisplayText(task.stage) }}</span>
              </div>
              <div
                v-if="task.type === 'workflow_employee' && expandedTaskIds.includes(task.id) && hasWorkflowBody(task)"
                class="task-workflow-body"
              >
                <div
                  v-if="typeof task.payload?.workflowProgressPct === 'number'"
                  class="task-wf-progress"
                >
                  <div class="task-wf-progress-head">
                    <span class="task-wf-progress-title">{{ $t('chat.taskProgress') }}</span>
                    <span class="task-wf-progress-meta">
                      <template v-if="task.payload?.workflowProgressStarted === false">
                        {{ normalizeTaskDisplayText(task.payload.workflowProgressLabel) }}
                      </template>
                      <template v-else>
                        {{ task.payload.workflowProgressPct }}%
                        <template v-if="task.payload.workflowProgressLabel">
                          · {{ normalizeTaskDisplayText(task.payload.workflowProgressLabel) }}
                        </template>
                      </template>
                    </span>
                  </div>
                  <div
                    class="task-wf-progress-track"
                    role="progressbar"
                    :aria-valuenow="workflowProgressIsIdle(task.payload) ? 0 : task.payload.workflowProgressPct"
                    aria-valuemin="0"
                    aria-valuemax="100"
                    :aria-valuetext="workflowProgressIsIdle(task.payload) ? $t('chat.progressNotStarted') : `${task.payload.workflowProgressPct}%`"
                  >
                    <div
                      class="task-wf-progress-fill"
                      :class="{ 'task-wf-progress-fill-idle': workflowProgressIsIdle(task.payload) }"
                      :style="{ width: workflowProgressIsIdle(task.payload) ? '0%' : Math.min(100, Math.max(0, task.payload.workflowProgressPct)) + '%' }"
                    />
                  </div>
                </div>
                <div v-if="task.payload?.workflowMonitorLine" class="task-wf-monitor">
                  <span class="task-wf-monitor-pulse" aria-hidden="true" />
                  <div class="task-wf-monitor-copy">
                    <div class="task-wf-monitor-kicker">{{ $t('chat.workflowMonitor') }}</div>
                    <div
                      class="task-wf-monitor-text"
                      :title="normalizeTaskDisplayText(workflowPayload(task).workflowMonitorLine)"
                    >
                      {{ normalizeTaskDisplayText(workflowPayload(task).workflowMonitorLine) }}
                    </div>
                  </div>
                </div>
                <div v-if="task.payload?.workflowCurrentHint" class="task-workflow-hint task-workflow-hint-secondary">
                  {{ normalizeTaskDisplayText(task.payload.workflowCurrentHint) }}
                </div>
                <details v-if="workflowPayload(task).workflowSteps?.length" class="task-wf-steps-details">
                  <summary>{{ $t('chat.stepDetails') }}</summary>
                  <ol class="task-workflow-steps">
                    <li
                      v-for="s in workflowPayload(task).workflowSteps"
                      :key="s.id"
                      :class="['task-workflow-step', `task-workflow-step--${s.status}`]"
                    >
                      <span class="task-workflow-step-text">{{ normalizeTaskDisplayText(s.label) }}</span>
                      <span class="task-workflow-step-state">{{
                        s.status === 'done' ? $t('chat.stepDone') : s.status === 'active' ? $t('chat.stepActive') : $t('chat.stepPending')
                      }}</span>
                    </li>
                  </ol>
                </details>
              </div>
              <div v-if="expandedTaskIds.includes(task.id)" class="task-list-detail">
                <div v-if="task.summary" class="task-summary">{{ normalizeTaskDisplayText(task.summary) }}</div>
                <div v-if="task.error" class="task-error">{{ normalizeTaskDisplayText(task.error) }}</div>
                <AgentTaskRuntimePanel v-if="task.type === 'agent_task'" :task="task" @open="$emit('select-task', task)" @approve="$emit('approve-task', task.id)" @retry="$emit('retry-task', task.id)" @pause="$emit('pause-task', task.id)" @resume="$emit('resume-task', task.id)" @cancel="$emit('cancel-task-by-id', task.id)" />
                <div
                  v-if="task.type !== 'workflow_employee' && task.type !== 'agent_task'"
                  class="task-actions"
                >
                  <button
                    v-if="task.type === 'shipment_audit_hint'"
                    type="button"
                    class="btn btn-primary btn-sm"
                    @click="$emit('open-shipment-records')"
                  >{{ $t('chat.openShipmentRecords') }}</button>
                  <button class="btn btn-secondary btn-sm" @click="$emit('jump-to-task-message', task)">{{ $t('chat.jumpToMessage') }}</button>
                  <span class="task-summary">本地状态快照，不提供伪控制</span>
                </div>
              </div>
            </div>
          </div>
        </template>
        <template v-if="!currentTask && !taskList.length && latestAssistantPush">
          <div class="task-card">
            <div class="task-header">{{ $t('chat.assistantPush') }}</div>
            <div style="display:flex;align-items:center;gap:8px;margin-top:8px;">
              <span style="font-size:18px;">🤖</span>
              <span style="font-size:13px;color:var(--app-text-strong);">{{ latestAssistantPush.title || $t('chat.newMessage') }}</span>
            </div>
            <div style="margin-top:var(--app-space-sm);color:var(--app-text-muted);font-size:13px;">
              {{ latestAssistantPush.description || $t('chat.assistantPushHint') }}
            </div>
            <div class="task-actions">
              <button class="btn btn-primary btn-sm" @click="$emit('copy-assistant-push')">
                {{ pushCopied ? $t('chat.pushCopied') : $t('chat.copyPush') }}
              </button>
              <button class="btn btn-secondary btn-sm" @click="$emit('open-assistant-float')">{{ $t('chat.openAssistantFloat') }}</button>
            </div>
          </div>
        </template>
        <div v-else-if="!currentTask && !taskList.length" class="empty-state">{{ $t('chat.noActiveTasks') }}</div>
      </div>
    </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ShipmentTask } from '@/composables/useShipmentTask'
import type { TaskFilter, TaskItem } from '@/composables/useChatPersistence'
import AgentTaskRuntimePanel from './AgentTaskRuntimePanel.vue'
import { workflowProgressIsIdle } from '@/workflow/coreWorkflowTaskUi'
import { normalizeTaskDisplayText } from '@/utils/chatTaskLabels'
useI18n()
type WorkflowTaskPayload = {
  workflowProgressPct?: number
  workflowMonitorLine?: string
  workflowCurrentHint?: string
  workflowProgressStarted?: boolean
  workflowProgressLabel?: string
  workflowSteps?: Array<{ id: string; label: string; status: string }>
}
function workflowPayload(task: TaskItem): WorkflowTaskPayload {
  return (task.payload ?? {}) as WorkflowTaskPayload
}
function hasWorkflowBody(task: TaskItem): boolean {
  const p = workflowPayload(task)
  return (
    p.workflowProgressPct != null
    || !!p.workflowMonitorLine
    || !!p.workflowCurrentHint
    || (Array.isArray(p.workflowSteps) && p.workflowSteps.length > 0)
  )
}
const props = defineProps<{
  currentTask: ShipmentTask | null
  taskList: TaskItem[]
  filteredTaskList: TaskItem[]
  activeTaskId: string; expandedTaskIds: string[]
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
}>()
const emit = defineEmits<{
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
  'pause-task': [id: string]; 'resume-task': [id: string]
  'approve-task': [id: string]
  'cancel-task-by-id': [id: string]
  'copy-assistant-push': []
  'open-assistant-float': []
}>()
const customOrderNumberModel = computed({
  get: () => props.currentTask?.customOrderNumber ?? '',
  set: (value: string) => emit('set-custom-order-number', value),
})
</script>
<style scoped src="./ChatTaskPanel.css"></style>
