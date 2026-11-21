<template>
  <div class="agent-task-runtime">
    <div class="agent-task-facts">
      <span>{{ $t('chat.runCount', { count: payload.runCount || 1 }) }}</span>
      <span>{{ $t('chat.toolCount', { count: toolCalls.length }) }}</span>
      <span>{{ $t('chat.attemptCount', { count: payload.attempt || 1 }) }}</span>
      <span v-if="payload.execution"
        >调度 {{ payload.execution.state }} · 执行 {{ payload.execution.execution_count }} 次 · 恢复
        {{ payload.execution.recovery_count }} 次</span
      >
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
        <small
          >{{ tool.status }}<template v-if="tool.duration_ms"> · {{ tool.duration_ms }}ms</template></small
        >
      </div>
    </details>
    <div v-if="Number(payload.artifactCount || 0)" class="agent-task-evidence">
      {{ $t('chat.evidenceCount', { count: payload.artifactCount }) }}
    </div>
    <div class="agent-task-evidence">
      结果证据：{{ payload.eventCount || 0 }} 条事件 · {{ payload.completedToolCount || 0 }} 次已完成工具调用 ·
      {{ payload.artifactCount || 0 }} 个产物
    </div>
    <section v-if="verification" class="agent-result-verification" :data-status="verificationStatus" aria-label="独立结果核验">
      <strong>独立结果核验</strong>
      <span>{{ verificationLabels[verificationStatus] }}</span>
      <small>独立通过 {{ verificationCount(verification.independently_verified_steps) }} 步 · 仅契约检查 {{ verificationCount(verification.contract_only_steps) }} 步</small>
      <p v-if="includesArtifactIntegrity">文件核验涵盖完整性与可读结构；业务语义仍需按任务要求验收。</p>
      <button v-if="canReverify" type="button" class="btn btn-secondary btn-sm agent-verification-action" :disabled="verificationPending || !!controlState?.pending" @click="reverify">
        {{ verificationPending ? '正在核验…' : '重新核验结果' }}
      </button>
      <p v-if="verificationMessage" role="status" aria-live="polite">{{ verificationMessage }}</p>
      <p v-if="verificationError" role="alert">{{ verificationError }}</p>
    </section>
    <div v-if="resultSummary" class="agent-result-summary" :class="{ 'agent-result-summary--unverified': verification && !verification.accepted }">
      <strong>业务结果</strong>
      <p>{{ resultSummary }}</p>
    </div>
    <div v-if="downloadableArtifacts.length" class="agent-artifact-downloads">
      <button
        v-for="artifact in downloadableArtifacts"
        :key="artifact.artifact_id"
        class="btn btn-primary btn-sm"
        :disabled="Boolean(downloadingId)"
        @click="downloadArtifact(artifact)"
      >
        {{ downloadingId === artifact.artifact_id ? '正在下载…' : `下载 ${artifact.name || '报表文件'}` }}
      </button>
      <p v-if="downloadError" role="alert">{{ downloadError }}</p>
    </div>
    <details v-if="hasResultEvidence" class="agent-result-evidence">
      <summary>技术明细（高级）</summary>
      <pre v-if="verificationDetailsText" class="agent-verification-details">{{ verificationDetailsText }}</pre>
      <pre v-if="finalOutputText">{{ finalOutputText }}</pre>
      <ul v-if="artifacts.length">
        <li v-for="artifact in artifacts" :key="artifact.artifact_id">
          {{ artifact.name || artifact.artifact_type || artifact.artifact_id }}
          <small v-if="artifact.uri">{{ artifact.uri }}</small>
        </li>
      </ul>
    </details>
    <AgentClarificationForm v-if="clarification && runId" :run-id="runId" :question="clarification" />
    <p v-if="controlState?.pending || controlState?.error || controlState?.message" role="status" aria-live="polite" class="task-control-status">
      {{ controlState?.pending ? `正在${controlLabels[controlState.pending]}…` : controlState?.error || controlState?.message }}
      <button v-if="controlState?.error" type="button" class="btn btn-secondary btn-sm" :disabled="!!controlState.pending" @click="$emit('refresh')">重新核对状态</button>
    </p>
    <div class="task-actions">
      <button class="btn btn-primary btn-sm" @click="$emit('open')">
        {{ $t('chat.openTask') }}
      </button>
      <button v-if="can('approve')" class="btn btn-success btn-sm" :disabled="!!controlState?.pending || !!controlState?.needsVerification" @click="$emit('approve')">审批并执行</button>
      <button v-if="isRetryable" class="btn btn-primary btn-sm" :disabled="!!controlState?.pending || !!controlState?.needsVerification" @click="$emit('retry')">
        {{ $t('chat.retryTask') }}
      </button>
      <button v-if="isPausable" class="btn btn-secondary btn-sm" :disabled="!!controlState?.pending || !!controlState?.needsVerification" @click="$emit('pause')">
        {{ $t('chat.pauseTask') }}
      </button>
      <button v-if="task.status === 'paused'" class="btn btn-primary btn-sm" :disabled="!!controlState?.pending || !!controlState?.needsVerification" @click="$emit('resume')">
        {{ $t('chat.resumeTask') }}
      </button>
      <button v-if="isCancellable" class="btn btn-secondary btn-sm" :disabled="!!controlState?.pending || !!controlState?.needsVerification" @click="$emit('cancel')">
        {{ $t('chat.cancel') }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import AgentClarificationForm, { type ClarificationQuestion } from './AgentClarificationForm.vue'
import { activeRunIdOfTask } from '@/utils/agentTaskWorkspaceModel'
import type { AgentArtifact, AgentRunStep, AgentToolCall, AgentVerificationReport, AgentVerificationStatus } from '@/api/agentRuns'
import agentRunsApi from '@/api/agentRuns'
import { downloadBlob } from '@/utils'
import { readActiveModIdFromStorage } from '@/utils/chatStorageKeys'
import { productReadScopeKey } from '@/utils/productReadAccountScope'
import type { TaskControlState } from '@/composables/useAgentTaskWorkspace'
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

const props = defineProps<{ task: TaskItem; controlState?: TaskControlState }>()
const emit = defineEmits<{ refresh: []; open: []; approve: []; retry: []; pause: []; resume: []; cancel: [] }>()

const controlLabels = { pause: '暂停', resume: '恢复', cancel: '取消', retry: '重试', approve: '审批' }
const runId = computed(() => activeRunIdOfTask(props.task))
const clarification = computed(() => {
  if (!steps.value.some((step) => step.tool_id === 'clarify' && step.status === 'waiting_user')) return null
  return payload.value.finalOutput?.clarification as ClarificationQuestion | undefined
})
const payload = computed(() => (props.task.payload ?? {}) as AgentTaskPayload)
const steps = computed(() => (Array.isArray(payload.value.steps) ? payload.value.steps : []))
const toolCalls = computed(() => (Array.isArray(payload.value.toolCalls) ? payload.value.toolCalls : []))
const artifacts = computed(() => (Array.isArray(payload.value.artifacts) ? payload.value.artifacts : []))
const verificationLabels: Record<AgentVerificationStatus, string> = {
  verified: '独立核验通过',
  failed: '核验未通过',
  inconclusive: '结果待核验，证据暂不可确认',
  pending: '等待核验',
  not_required: '已完成输出契约检查，无需独立读回',
  not_verified: '尚无独立核验证据',
}
const verification = computed(() => {
  const report = payload.value.finalOutput?.verification
  return report && typeof report === 'object' && !Array.isArray(report) ? report as AgentVerificationReport : null
})
const verificationStatus = computed<AgentVerificationStatus>(() => {
  const status = verification.value?.status
  if (!status || !(status in verificationLabels)) return 'not_verified'
  if (['verified', 'not_required'].includes(status) && verification.value?.accepted !== true) return 'inconclusive'
  return status
})
const includesArtifactIntegrity = computed(() => Array.isArray(verification.value?.steps) && verification.value.steps.some((step) =>
  Array.isArray(step?.checks) && step.checks.some((check) => check?.evidence?.verification_scope === 'artifact_integrity'),
))
const rawRunStatus = computed(() => String(payload.value.rawRunStatus || props.task.status))
const canReverify = computed(() => Boolean(
  runId.value && ['blocked', 'failed'].includes(rawRunStatus.value) &&
  verification.value?.protocol === 'xcagi.result-verification.v1' &&
  Array.isArray(verification.value.steps) && verification.value.steps.some((step) => typeof step?.call_id === 'string' && step.call_id),
))
const verificationPending = ref(false)
const verificationMessage = ref('')
const verificationError = ref('')
let verificationEpoch = 0
const verificationScope = () => JSON.stringify([props.task.id, runId.value, productReadScopeKey(readActiveModIdFromStorage())])
function retireVerification(): void {
  verificationEpoch++
  verificationPending.value = false
  verificationMessage.value = ''
  verificationError.value = ''
}
watch([verificationScope, rawRunStatus], retireVerification, { flush: 'sync' })
onBeforeUnmount(retireVerification)
function verificationCount(value: number | undefined): number {
  return typeof value === 'number' && Number.isFinite(value) ? Math.max(0, Math.floor(value)) : 0
}
async function reverify(): Promise<void> {
  if (!canReverify.value || verificationPending.value || props.controlState?.pending) return
  const requestedRun = runId.value
  const requestedScope = verificationScope()
  const requestedEpoch = ++verificationEpoch
  const isCurrent = () => requestedEpoch === verificationEpoch && requestedScope === verificationScope()
  verificationPending.value = true
  verificationMessage.value = ''
  verificationError.value = ''
  try {
    const response = await agentRunsApi.verifyRun(requestedRun)
    if (!isCurrent()) return
    if (response.success !== true) throw new Error('verification_request_failed')
    const report = response.verification
    verificationMessage.value = report?.accepted === true && ['verified', 'not_required'].includes(report.status)
      ? (report.status === 'verified' ? '结果核验已通过，正在更新任务状态。' : '输出契约检查已完成，正在更新任务状态。')
      : '结果仍待核验，请查看核验明细。'
    emit('refresh')
  } catch {
    if (!isCurrent()) return
    verificationError.value = '重新核验失败，请刷新核对任务状态后再试。'
    emit('refresh')
  } finally {
    if (requestedEpoch === verificationEpoch) verificationPending.value = false
  }
}
const downloadingId = ref('')
const downloadError = ref('')
const downloadableArtifacts = computed(() =>
  artifacts.value.filter(
    (artifact) =>
      runId.value &&
      artifact.artifact_type === 'file' &&
      artifact.uri === `/api/agent/runs/${encodeURIComponent(runId.value)}/artifacts/${encodeURIComponent(artifact.artifact_id)}`,
  ),
)
async function downloadArtifact(artifact: AgentArtifact): Promise<void> {
  if (downloadingId.value || !downloadableArtifacts.value.includes(artifact)) return
  downloadingId.value = artifact.artifact_id
  downloadError.value = ''
  try {
    const response = await agentRunsApi.downloadArtifact(runId.value, artifact.artifact_id)
    downloadBlob(await response.blob(), artifact.name || '报表.xlsx')
  } catch {
    downloadError.value = '下载失败，请重试；如果文件已失效，请重新导出。'
  } finally {
    downloadingId.value = ''
  }
}
const resultSummary = computed(() => {
  const output = payload.value.finalOutput
  if (!output || typeof output !== 'object') return ''
  if (verification.value && verification.value.accepted !== true) return '结果尚未完成核验。'
  const businessResult =
    output.business_result && typeof output.business_result === 'object' ? (output.business_result as Record<string, unknown>) : null
  const projectedSummary = businessResult?.summary
  if (typeof projectedSummary === 'string' && projectedSummary.trim()) {
    const facts = businessResult?.facts && typeof businessResult.facts === 'object' ? (businessResult.facts as Record<string, unknown>) : {}
    const factLabels: Record<string, string> = {
      customer_id: '客户 ID',
      product_id: '产品 ID',
      material_id: '原材料 ID',
      order_id: '订单 ID',
      record_id: '记录 ID',
      request_no: '请求单号',
      order_number: '业务单号',
      doc_name: '文档',
      created: '新增',
      updated: '更新',
      count: '数量',
      total: '合计',
    }
    const renderedFacts = Object.entries(facts)
      .filter(([, value]) => value !== '' && value !== null && value !== undefined)
      .map(([key, value]) => `${factLabels[key] || key}：${String(value)}`)
    return [projectedSummary.trim(), ...renderedFacts].join('；').slice(0, 800)
  }
  const chatPayload = output.chat_payload
  const chatRecord = chatPayload && typeof chatPayload === 'object' ? (chatPayload as Record<string, unknown>) : null
  const candidates = [chatRecord?.response, chatRecord?.message, output.response, output.message]
  const summary = candidates.find((value) => typeof value === 'string' && value.trim())
  if (typeof summary === 'string') return summary.trim().slice(0, 800)
  const nodeOutputs = output.node_outputs && typeof output.node_outputs === 'object' ? Object.values(output.node_outputs) : []
  const lastOutput = [...nodeOutputs].reverse().find((value) => value && typeof value === 'object') as Record<string, unknown> | undefined
  if (!lastOutput) return ''
  const nodeMessage = [lastOutput.message, lastOutput.summary].find((value) => typeof value === 'string' && value.trim())
  if (typeof nodeMessage === 'string') return nodeMessage.trim().slice(0, 800)
  const idEntry = Object.entries(lastOutput).find(
    ([key, value]) => /(?:^id$|_id$|_number$)/.test(key) && ['string', 'number'].includes(typeof value),
  )
  return lastOutput.success === true ? `业务操作执行成功${idEntry ? `；${idEntry[0]}：${String(idEntry[1])}` : ''}` : ''
})
const finalOutputText = computed(() => {
  const output = Object.fromEntries(Object.entries(payload.value.finalOutput || {}).filter(([key]) => key !== 'verification'))
  if (!output || !Object.keys(output).length) return ''
  const rendered = JSON.stringify(output, null, 2)
  return rendered.length > 4000 ? `${rendered.slice(0, 4000)}\n…` : rendered
})
const verificationDetailsText = computed(() => verification.value ? JSON.stringify(verification.value, null, 2) : '')
const hasResultEvidence = computed(() => Boolean(verificationDetailsText.value || finalOutputText.value || artifacts.value.length))
function can(action: string): boolean {
  if (action === 'approve' && clarification.value) return false
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
    pending: '待执行',
    running: '执行中',
    retrying: '重试中',
    waiting_user: '等待确认',
    completed: '已完成',
    failed: '失败',
    skipped: '已跳过',
  }
  return labels[String(status || '')] || '待执行'
}
</script>

<style scoped>
.agent-task-runtime {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 8px;
  padding: 9px;
  border: 1px solid #e2e8f0;
  border-radius: 7px;
  background: #f8fafc;
}
.agent-task-facts {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 11px;
  color: #475569;
}
.agent-task-facts span {
  padding: 2px 6px;
  border-radius: 999px;
  background: #e2e8f0;
}
.agent-task-workspace {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 2px 8px;
  font-size: 11px;
  color: #334155;
  word-break: break-all;
}
.agent-task-workspace small {
  grid-column: 2;
  color: #64748b;
}
.agent-task-steps {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.agent-task-steps li,
.agent-tool-session {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 11px;
  color: #334155;
}
.agent-task-steps em {
  flex: none;
  font-style: normal;
  color: #64748b;
}
.agent-step-status--completed {
  color: #15803d !important;
}
.agent-step-status--running,
.agent-step-status--retrying {
  color: #1d4ed8 !important;
}
.agent-step-status--waiting_user {
  color: #b45309 !important;
}
.agent-step-status--failed {
  color: #b91c1c !important;
}
.agent-tool-sessions summary {
  cursor: pointer;
  font-size: 11px;
  font-weight: 600;
  color: #334155;
}
.agent-tool-session {
  padding-top: 5px;
}
.agent-tool-session small,
.agent-task-evidence {
  color: #64748b;
  font-size: 11px;
}
.agent-result-summary {
  padding: 7px 8px;
  border-radius: 6px;
  background: #ecfdf5;
  color: #14532d;
  font-size: 11px;
}
.agent-result-summary p {
  margin: 3px 0 0;
  line-height: 1.45;
}
.agent-result-verification {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  padding: 7px 8px;
  border: 1px solid #fde68a;
  border-radius: 6px;
  background: #fffbeb;
  color: #92400e;
  font-size: 11px;
}
.agent-result-verification[data-status='verified'] {
  border-color: #a7f3d0;
  background: #ecfdf5;
  color: #14532d;
}
.agent-result-verification[data-status='failed'] {
  border-color: #fecaca;
  background: #fef2f2;
  color: #991b1b;
}
.agent-result-verification p {
  margin: 0;
}
.agent-result-summary--unverified {
  background: #fffbeb;
  color: #92400e;
}
.agent-result-evidence summary {
  cursor: pointer;
  font-size: 11px;
  font-weight: 600;
  color: #334155;
}
.agent-result-evidence pre {
  max-height: 220px;
  margin: 6px 0 0;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 10px;
  color: #334155;
}
.agent-result-evidence ul {
  margin: 6px 0 0;
  padding-left: 18px;
  font-size: 10px;
  color: #334155;
}
.agent-result-evidence small {
  display: block;
  word-break: break-all;
  color: #64748b;
}
.task-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
</style>
