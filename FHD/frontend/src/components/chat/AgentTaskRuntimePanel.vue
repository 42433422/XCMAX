<template>
  <div class="agent-task-runtime">
    <div class="agent-task-facts">
      <span>{{ $t('chat.runCount', { count: payload.runCount || 1 }) }}</span>
      <span>{{ $t('chat.toolCount', { count: toolCalls.length }) }}</span>
      <span>{{ $t('chat.attemptCount', { count: payload.attempt || 1 }) }}</span>
      <span v-if="payload.execution">调度 {{ payload.execution.state }} · 执行 {{ payload.execution.execution_count }} 次 · 恢复 {{ payload.execution.recovery_count }} 次</span>
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
    <div class="agent-task-evidence">
      结果证据：{{ payload.eventCount || 0 }} 条事件 · {{ payload.completedToolCount || 0 }} 次已完成工具调用 · {{ payload.artifactCount || 0 }} 个产物
    </div>
    <details v-if="hasResultEvidence" class="agent-result-evidence">
      <summary>查看结果证据</summary>
      <pre v-if="finalOutputText">{{ finalOutputText }}</pre>
      <ul v-if="artifacts.length">
        <li v-for="artifact in artifacts" :key="artifact.artifact_id">
          {{ artifact.name || artifact.artifact_type || artifact.artifact_id }}
          <small v-if="artifact.uri">{{ artifact.uri }}</small>
        </li>
      </ul>
    </details>
    <div class="task-actions">
      <button class="btn btn-primary btn-sm" @click="$emit('open')">{{ $t('chat.openTask') }}</button>
      <button v-if="can('approve')" class="btn btn-success btn-sm" @click="$emit('approve')">审批并执行</button>
      <button v-if="isRetryable" class="btn btn-primary btn-sm" @click="$emit('retry')">{{ $t('chat.retryTask') }}</button>
      <button v-if="isPausable" class="btn btn-secondary btn-sm" @click="$emit('pause')">{{ $t('chat.pauseTask') }}</button>
      <button v-if="task.status === 'paused'" class="btn btn-primary btn-sm" @click="$emit('resume')">{{ $t('chat.resumeTask') }}</button>
      <button v-if="isCancellable" class="btn btn-secondary btn-sm" @click="$emit('cancel')">{{ $t('chat.cancel') }}</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { AgentArtifact, AgentRunStep, AgentToolCall } from '@/api/agentRuns'
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
  eventCount?: number
  completedToolCount?: number
  capabilities?: Record<string, boolean>
  rawRunStatus?: string
  finalOutput?: Record<string, unknown>
  artifacts?: AgentArtifact[]
  execution?: {
    state: string
    execution_count: number
    recovery_count: number
  }
}

const props = defineProps<{ task: TaskItem }>()
defineEmits<{ open: []; approve: []; retry: []; pause: []; resume: []; cancel: [] }>()

const payload = computed(() => (props.task.payload ?? {}) as AgentTaskPayload)
const steps = computed(() => Array.isArray(payload.value.steps) ? payload.value.steps : [])
const toolCalls = computed(() => Array.isArray(payload.value.toolCalls) ? payload.value.toolCalls : [])
const artifacts = computed(() => Array.isArray(payload.value.artifacts) ? payload.value.artifacts : [])
const finalOutputText = computed(() => {
  const output = payload.value.finalOutput
  if (!output || !Object.keys(output).length) return ''
  const rendered = JSON.stringify(output, null, 2)
  return rendered.length > 4000 ? `${rendered.slice(0, 4000)}\n…` : rendered
})
const hasResultEvidence = computed(() => Boolean(finalOutputText.value || artifacts.value.length))
function can(action: string): boolean {
  if (payload.value.capabilities && action in payload.value.capabilities) {
    return Boolean(payload.value.capabilities[action])
  }
  const rawStatus = String(payload.value.rawRunStatus || props.task.status)
  if (action === 'approve') return rawStatus === 'waiting_user'
  if (action === 'pause') return ['queued', 'running', 'waiting_user'].includes(rawStatus)
  if (action === 'resume') return rawStatus === 'paused'
  if (action === 'cancel') return ['queued', 'running', 'blocked', 'paused', 'waiting_user'].includes(rawStatus)
  if (action === 'retry') return ['failed', 'cancelled', 'blocked'].includes(rawStatus)
  return action === 'evidence'
}
const isRetryable = computed(() => can('retry'))
const isPausable = computed(() => can('pause'))
const isCancellable = computed(() => can('cancel'))

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
.agent-result-evidence summary { cursor: pointer; font-size: 11px; font-weight: 600; color: #334155; }
.agent-result-evidence pre { max-height: 220px; margin: 6px 0 0; overflow: auto; white-space: pre-wrap; word-break: break-word; font-size: 10px; color: #334155; }
.agent-result-evidence ul { margin: 6px 0 0; padding-left: 18px; font-size: 10px; color: #334155; }
.agent-result-evidence small { display: block; word-break: break-all; color: #64748b; }
.task-actions { display: flex; flex-wrap: wrap; gap: 6px; }
</style>
