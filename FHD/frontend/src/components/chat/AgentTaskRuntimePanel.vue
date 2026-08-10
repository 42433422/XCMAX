<template>
  <div class="agent-task-runtime">
    <div class="agent-task-facts">
      <span>{{ $t('chat.runCount', { count: payload.runCount || 1 }) }}</span>
      <span>{{ $t('chat.toolCount', { count: toolCalls.length }) }}</span>
      <span>{{ $t('chat.attemptCount', { count: payload.attempt || 1 }) }}</span>
    </div>
    <div v-if="payload.workspaceId || payload.workspacePath" class="agent-task-workspace">
      <strong>{{ $t('chat.taskWorkspace') }}</strong>
      <span>{{ payload.workspaceId || payload.workspacePath }}</span>
      <small>{{ payload.workspaceIsolation || 'business_workspace' }}</small>
    </div>
    <ol v-if="steps.length" class="agent-task-steps">
      <li v-for="step in steps" :key="step.step_id">
        <span>{{ step.description || `${step.tool_id}.${step.action}` }}</span>
        <em :class="`agent-step-status--${step.status || 'pending'}`">{{ stepStatus(step.status) }}</em>
      </li>
    </ol>
    <details v-if="toolCalls.length" class="agent-tool-sessions">
      <summary>{{ $t('chat.toolSessions') }}</summary>
      <div v-for="tool in toolCalls" :key="tool.call_id" class="agent-tool-session">
        <span>{{ tool.tool_id }}.{{ tool.action }}</span>
        <small>{{ tool.status }}<template v-if="tool.duration_ms"> · {{ tool.duration_ms }}ms</template></small>
      </div>
    </details>
    <div v-if="Number(payload.artifactCount || 0)" class="agent-task-evidence">
      {{ $t('chat.evidenceCount', { count: payload.artifactCount }) }}
    </div>
    <div class="task-actions">
      <button class="btn btn-primary btn-sm" @click="$emit('open')">{{ $t('chat.openTask') }}</button>
      <button v-if="isRetryable" class="btn btn-primary btn-sm" @click="$emit('retry')">{{ $t('chat.retryTask') }}</button>
      <button v-if="isPausable" class="btn btn-secondary btn-sm" @click="$emit('pause')">{{ $t('chat.pauseTask') }}</button>
      <button v-if="task.status === 'paused'" class="btn btn-primary btn-sm" @click="$emit('resume')">{{ $t('chat.resumeTask') }}</button>
      <button v-if="isCancellable" class="btn btn-secondary btn-sm" @click="$emit('cancel')">{{ $t('chat.cancel') }}</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { AgentRunStep, AgentToolCall } from '@/api/agentRuns'
import type { TaskItem } from '@/composables/useChatPersistence'

type AgentTaskPayload = {
  runCount?: number
  attempt?: number
  workspaceId?: string
  workspacePath?: string
  workspaceIsolation?: string
  steps?: AgentRunStep[]
  toolCalls?: AgentToolCall[]
  artifactCount?: number
}

const props = defineProps<{ task: TaskItem }>()
defineEmits<{ open: []; retry: []; pause: []; resume: []; cancel: [] }>()

const payload = computed(() => (props.task.payload ?? {}) as AgentTaskPayload)
const steps = computed(() => Array.isArray(payload.value.steps) ? payload.value.steps : [])
const toolCalls = computed(() => Array.isArray(payload.value.toolCalls) ? payload.value.toolCalls : [])
const isRetryable = computed(() => ['failed', 'cancelled', 'blocked'].includes(props.task.status))
const isPausable = computed(() => ['running', 'queued'].includes(props.task.status))
const isCancellable = computed(() => ['running', 'queued', 'blocked', 'paused'].includes(props.task.status))

function stepStatus(status: string | undefined): string {
  const labels: Record<string, string> = {
    pending: '待执行', running: '执行中', retrying: '重试中', waiting_user: '等待确认',
    completed: '已完成', failed: '失败', skipped: '已跳过',
  }
  return labels[String(status || '')] || '待执行'
}
</script>

<style scoped>
.agent-task-runtime { display: flex; flex-direction: column; gap: 8px; margin-top: 8px; padding: 9px; border: 1px solid #e2e8f0; border-radius: 7px; background: #f8fafc; }
.agent-task-facts { display: flex; flex-wrap: wrap; gap: 6px; font-size: 11px; color: #475569; }
.agent-task-facts span { padding: 2px 6px; border-radius: 999px; background: #e2e8f0; }
.agent-task-workspace { display: grid; grid-template-columns: auto 1fr; gap: 2px 8px; font-size: 11px; color: #334155; word-break: break-all; }
.agent-task-workspace small { grid-column: 2; color: #64748b; }
.agent-task-steps { display: flex; flex-direction: column; gap: 5px; margin: 0; padding: 0; list-style: none; }
.agent-task-steps li, .agent-tool-session { display: flex; align-items: center; justify-content: space-between; gap: 8px; font-size: 11px; color: #334155; }
.agent-task-steps em { flex: none; font-style: normal; color: #64748b; }
.agent-step-status--completed { color: #15803d !important; }
.agent-step-status--running, .agent-step-status--retrying { color: #1d4ed8 !important; }
.agent-step-status--waiting_user { color: #b45309 !important; }
.agent-step-status--failed { color: #b91c1c !important; }
.agent-tool-sessions summary { cursor: pointer; font-size: 11px; font-weight: 600; color: #334155; }
.agent-tool-session { padding-top: 5px; }
.agent-tool-session small, .agent-task-evidence { color: #64748b; font-size: 11px; }
.task-actions { display: flex; flex-wrap: wrap; gap: 6px; }
</style>
