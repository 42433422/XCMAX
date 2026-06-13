<template>
  <div class="right-panel">
    <div class="panel-header">{{ $t('chat.currentTask') }}</div>
    <div class="panel-content panel-content-task" id="taskPanel">
      <div class="task-panel-body">
        <template v-if="currentTask">
          <div class="task-card" :class="{ 'excel-import-task': currentTask?.type === 'excel_import' }">
            <div class="task-header">{{ currentTask.title }}</div>
            <div class="task-description">{{ currentTask.description }}</div>
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
                v-model="currentTask.customOrderNumber"
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
              <button class="task-filter-btn" :class="{ active: taskFilter === 'success' }" @click="$emit('set-task-filter', 'success')">{{ $t('chat.filterSuccess') }}</button>
              <button class="task-filter-btn" :class="{ active: taskFilter === 'failed' }" @click="$emit('set-task-filter', 'failed')">{{ $t('chat.filterFailed') }}</button>
            </div>
            <button class="btn btn-secondary btn-sm" @click="$emit('clear-task-history')">{{ $t('chat.clearTaskHistory') }}</button>
          </div>
          <div class="task-list">
            <div
              v-for="task in filteredTaskList"
              :key="task.id"
              class="task-list-item"
              :class="{
                'task-list-item-workflow-collapsed':
                  task.type === 'workflow_employee' && !expandedTaskIds.includes(task.id),
              }"
            >
              <button
                type="button"
                class="task-list-main"
                :aria-expanded="expandedTaskIds.includes(task.id)"
                @click="$emit('toggle-task-expanded', task.id)"
              >
                <span
                  class="task-dot"
                  :class="`status-${workflowTaskDotStatusClass(task)}`"
                  :title="workflowTaskDotTitle(task)"
                />
                <span class="task-list-title">{{ task.title }}</span>
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
                <span v-if="task.stage">{{ task.stage }}</span>
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
                        {{ task.payload.workflowProgressLabel }}
                      </template>
                      <template v-else>
                        {{ task.payload.workflowProgressPct }}%
                        <template v-if="task.payload.workflowProgressLabel">
                          · {{ task.payload.workflowProgressLabel }}
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
                      :title="workflowPayload(task).workflowMonitorLine"
                    >
                      {{ workflowPayload(task).workflowMonitorLine }}
                    </div>
                  </div>
                </div>
                <div v-if="task.payload?.workflowCurrentHint" class="task-workflow-hint task-workflow-hint-secondary">
                  {{ task.payload.workflowCurrentHint }}
                </div>
                <details v-if="workflowPayload(task).workflowSteps?.length" class="task-wf-steps-details">
                  <summary>{{ $t('chat.stepDetails') }}</summary>
                  <ol class="task-workflow-steps">
                    <li
                      v-for="s in workflowPayload(task).workflowSteps"
                      :key="s.id"
                      :class="['task-workflow-step', `task-workflow-step--${s.status}`]"
                    >
                      <span class="task-workflow-step-text">{{ s.label }}</span>
                      <span class="task-workflow-step-state">{{
                        s.status === 'done' ? $t('chat.stepDone') : s.status === 'active' ? $t('chat.stepActive') : $t('chat.stepPending')
                      }}</span>
                    </li>
                  </ol>
                </details>
              </div>
              <div v-if="expandedTaskIds.includes(task.id)" class="task-list-detail">
                <div v-if="task.summary" class="task-summary">{{ task.summary }}</div>
                <div v-if="task.error" class="task-error">{{ task.error }}</div>
                <div
                  v-if="task.type !== 'workflow_employee'"
                  class="task-actions"
                >
                  <button
                    v-if="task.type === 'shipment_audit_hint'"
                    type="button"
                    class="btn btn-primary btn-sm"
                    @click="$emit('open-shipment-records')"
                  >{{ $t('chat.openShipmentRecords') }}</button>
                  <button class="btn btn-secondary btn-sm" @click="$emit('jump-to-task-message', task)">{{ $t('chat.jumpToMessage') }}</button>
                  <button v-if="task.status === 'failed' || task.status === 'cancelled'" class="btn btn-primary btn-sm" @click="$emit('retry-task', task.id)">{{ $t('chat.retryTask') }}</button>
                  <button v-if="task.status === 'running' || task.status === 'queued'" class="btn btn-secondary btn-sm" @click="$emit('cancel-task-by-id', task.id)">{{ $t('chat.cancel') }}</button>
                </div>
              </div>
            </div>
          </div>
        </template>
        <template v-if="!currentTask && !taskList.length && isProMode && proRuntimeTask">
          <div class="task-card">
            <div class="task-header">{{ proRuntimeTask.title }}</div>
            <div style="margin-top:6px;">
              <span :class="['task-item-status', proRuntimeTask.statusClass]">
                {{ proRuntimeTask.statusText }}
              </span>
            </div>
            <div style="margin-top:10px; color:var(--app-text-muted); font-size:13px;">
              {{ proRuntimeTask.description }}
            </div>
          </div>
        </template>
        <template v-else-if="!currentTask && !taskList.length && latestAssistantPush">
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
  </div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { ShipmentTask } from '@/composables/useShipmentTask'
import type { TaskItem } from '@/composables/useChatPersistence'
import { workflowProgressIsIdle } from '@/workflow/coreWorkflowTaskUi'

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

defineProps<{
  currentTask: ShipmentTask | null
  taskList: TaskItem[]
  filteredTaskList: TaskItem[]
  expandedTaskIds: string[]
  taskFilter: 'all' | 'running' | 'success' | 'failed'
  isProMode: boolean
  proRuntimeTask: { title: string; statusText: string; statusClass: string; description: string } | null
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

defineEmits<{
  'confirm-task': []
  'cancel-task': []
  'refetch-order-number': []
  'shipment-download-click': []
  'start-print': []
  'switch-view': [view: string]
  'set-task-filter': [filter: 'all' | 'running' | 'success' | 'failed']
  'clear-task-history': []
  'toggle-task-expanded': [id: string]
  'open-shipment-records': []
  'jump-to-task-message': [task: TaskItem]
  'retry-task': [id: string]
  'cancel-task-by-id': [id: string]
  'copy-assistant-push': []
  'open-assistant-float': []
}>()
</script>

<style scoped>
.panel-content.panel-content-task {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.task-panel-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.task-list {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-sm);
}

.task-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--app-space-sm);
  gap: var(--app-space-sm);
}

.task-toolbar-below-card {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--app-border-subtle);
}

.task-filters {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.task-order-number-row {
  margin-top: 6px;
  color: var(--app-text-secondary);
  font-size: var(--app-font-size-caption);
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.task-filter-btn {
  border: 1px solid var(--app-border-strong);
  background: var(--card-bg);
  color: var(--app-text-strong);
  border-radius: 6px;
  padding: 2px var(--app-space-sm);
  font-size: var(--app-font-size-caption);
  cursor: pointer;
}

.task-filter-btn.active {
  border-color: var(--app-interactive);
  background: var(--app-interactive-bg);
  color: var(--app-interactive-text);
}

.task-list-item {
  border: 1px solid var(--app-border-subtle);
  border-radius: 8px;
  padding: var(--app-space-sm);
  background: var(--card-bg);
}

.task-list-main {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  border: none;
  background: transparent;
  text-align: left;
  padding: 0;
  cursor: pointer;
}

.task-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  flex: none;
}

.status-queued { background: #9ca3af; }
.status-running { background: #3b82f6; }
.status-success { background: #10b981; }
.status-failed { background: #ef4444; }
.status-cancelled { background: #6b7280; }
.status-workflow-warn { background: #f59e0b; }

.task-list-chevron {
  flex: none;
  width: 14px;
  text-align: center;
  font-size: 10px;
  color: #9ca3af;
  user-select: none;
}

.task-list-item-workflow-collapsed {
  padding-bottom: 6px;
}

.task-list-title {
  flex: 1;
  font-size: 13px;
  color: #111827;
}

.task-list-time {
  font-size: 12px;
  color: #6b7280;
}

.task-list-meta {
  margin-top: 4px;
  display: flex;
  gap: 8px;
  font-size: 12px;
  color: #6b7280;
  flex-wrap: wrap;
}

.task-workflow-body {
  margin-top: 10px;
  padding: 10px 10px 8px;
  border-radius: 8px;
  background: linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%);
  border: 1px solid #e2e8f0;
}

.task-wf-progress {
  margin-bottom: 10px;
}

.task-wf-progress-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 6px;
}

.task-wf-progress-title {
  font-size: 12px;
  font-weight: 700;
  color: #0f172a;
}

.task-wf-progress-meta {
  font-size: 11px;
  color: #475569;
  font-variant-numeric: tabular-nums;
}

.task-wf-progress-track {
  height: 8px;
  border-radius: 999px;
  background: #e2e8f0;
  overflow: hidden;
}

.task-wf-progress-fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #3b82f6, #6366f1);
  transition: width 0.35s ease;
}

.task-wf-progress-fill-idle {
  background: transparent;
}

.task-wf-monitor {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 10px 10px;
  margin-bottom: 8px;
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 8px;
}

.task-wf-monitor-pulse {
  flex: none;
  width: 10px;
  height: 10px;
  margin-top: 4px;
  border-radius: 50%;
  background: #22c55e;
  box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.5);
  animation: task-wf-pulse 1.8s ease-out infinite;
}

@keyframes task-wf-pulse {
  0% { box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.45); }
  70% { box-shadow: 0 0 0 8px rgba(34, 197, 94, 0); }
  100% { box-shadow: 0 0 0 0 rgba(34, 197, 94, 0); }
}

.task-wf-monitor-kicker {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: #94a3b8;
  margin-bottom: 4px;
}

.task-wf-monitor-text {
  font-size: 12px;
  line-height: 1.5;
  color: #f1f5f9;
  white-space: pre-line;
  word-break: break-word;
  min-width: 0;
}

.task-workflow-hint {
  font-size: 12px;
  line-height: 1.5;
  color: #0f172a;
  margin: 0 0 10px;
  padding: 8px 10px;
  background: #fff;
  border-radius: 6px;
  border-left: 3px solid #3b82f6;
}

.task-workflow-hint-secondary {
  border-left-color: #94a3b8;
  color: #334155;
  margin-bottom: 8px;
}

.task-wf-steps-details {
  font-size: 12px;
  color: #475569;
}

.task-wf-steps-details summary {
  cursor: pointer;
  font-weight: 600;
  color: #334155;
  padding: 4px 0;
  list-style: none;
}

.task-wf-steps-details summary::-webkit-details-marker {
  display: none;
}

.task-wf-steps-details[open] summary {
  margin-bottom: 6px;
}

.task-workflow-steps {
  margin: 0;
  padding-left: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.task-workflow-step {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  font-size: 12px;
  line-height: 1.45;
  padding: 6px 8px;
  border-radius: 6px;
  background: #fff;
  border: 1px solid #e5e7eb;
}

.task-workflow-step--done {
  border-color: #bbf7d0;
  background: #f0fdf4;
}

.task-workflow-step--active {
  border-color: #93c5fd;
  background: #eff6ff;
  box-shadow: 0 0 0 1px rgba(59, 130, 246, 0.12);
}

.task-workflow-step--pending {
  opacity: 0.92;
}

.task-workflow-step-text {
  flex: 1;
  min-width: 0;
  color: #1e293b;
}

.task-workflow-step-state {
  flex: none;
  font-size: 11px;
  font-weight: 600;
  color: #64748b;
  white-space: nowrap;
}

.task-workflow-step--done .task-workflow-step-state {
  color: #15803d;
}

.task-workflow-step--active .task-workflow-step-state {
  color: #1d4ed8;
}

.task-list-detail {
  margin-top: 8px;
  border-top: 1px dashed #e5e7eb;
  padding-top: 8px;
}

.task-summary {
  font-size: 12px;
  color: #374151;
}

.task-error {
  margin-top: 4px;
  font-size: 12px;
  color: #dc2626;
}
</style>
