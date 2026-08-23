<template>
  <details
    :class="['art-trace', `is-${trace.status}`]"
    :open="defaultOpen"
    data-testid="agent-run-trace"
  >
    <summary class="art-summary">
      <span class="art-disclosure" aria-hidden="true">
        <i class="fa fa-chevron-right"></i>
      </span>
      <span class="art-harness-icon" aria-hidden="true">
        <i class="fa fa-sitemap"></i>
      </span>
      <span class="art-heading">
        <span class="art-eyebrow">XCAGI Business Harness</span>
        <span class="art-task-title">{{ taskTitle }}</span>
      </span>
      <span v-if="toolCount" class="art-tool-count">{{ toolCount }} 个工具</span>
      <span :class="['art-status-pill', `is-${trace.status}`]">
        <i class="fa" :class="statusIconClass(trace.status)" aria-hidden="true"></i>
        {{ statusLabel }}
      </span>
      <span v-if="durationLabel" class="art-duration">{{ durationLabel }}</span>
    </summary>

    <div class="art-body">
      <div class="art-overview">
        <span><i class="fa fa-list-ul" aria-hidden="true"></i>{{ trace.phases.length }} 个步骤</span>
        <span v-if="waitingCount" class="is-warning"><i class="fa fa-shield" aria-hidden="true"></i>{{ waitingCount }} 项待确认</span>
        <span v-if="failedCount" class="is-danger"><i class="fa fa-exclamation-circle" aria-hidden="true"></i>{{ failedCount }} 项异常</span>
        <span v-if="trace.last_event_id" class="art-run-id">Run · {{ shortRunId }}</span>
      </div>

      <div class="art-stream">
        <details
          v-for="(phase, idx) in trace.phases"
          :key="phase.started_event_id || idx"
          :class="['art-step', `is-${phase.kind}`, `is-${phase.status}`, { 'has-detail': hasPhaseDetails(phase) }]"
          :open="shouldOpenPhase(phase)"
        >
          <summary
            class="art-step-summary"
            :aria-disabled="hasPhaseDetails(phase) ? undefined : 'true'"
            @click="!hasPhaseDetails(phase) && $event.preventDefault()"
          >
            <span class="art-step-icon" aria-hidden="true">
              <i class="fa" :class="phaseIconClass(phase)"></i>
            </span>
            <span class="art-step-heading">
              <span class="art-step-title">{{ phaseDisplayTitle(phase) }}</span>
              <span v-if="phaseDisplaySubtitle(phase)" class="art-step-subtitle">{{ phaseDisplaySubtitle(phase) }}</span>
            </span>
            <span v-if="isTool(phase) && phase.retries > 0" class="art-step-badge is-retry">重试 {{ phase.retries }}</span>
            <span v-if="isTool(phase) && phase.waiting_approval" class="art-step-badge is-waiting">需确认</span>
            <span v-if="phase.duration_ms != null" class="art-step-duration">{{ formatDuration(phase.duration_ms) }}</span>
            <i class="fa art-step-status" :class="statusIconClass(phase.status)" aria-hidden="true"></i>
            <i v-if="hasPhaseDetails(phase)" class="fa fa-chevron-right art-step-chevron" aria-hidden="true"></i>
          </summary>

          <div v-if="hasPhaseDetails(phase)" class="art-step-detail">
            <template v-if="isTool(phase)">
              <div class="art-tool-meta">
                <code>{{ phase.tool_id || 'tool' }}<template v-if="phase.action">.{{ phase.action }}</template></code>
                <span v-if="phase.node_id">节点 {{ phase.node_id }}</span>
                <span v-if="getPermissionBadge(phase.tool_id)" :class="['art-permission', `is-${getPermissionBadge(phase.tool_id)}`]">
                  {{ getPermissionBadge(phase.tool_id) === 'session' ? '本次会话已授权' : '已记住授权' }}
                </span>
              </div>
              <section v-if="phase.params_json" class="art-detail-section">
                <div class="art-detail-label"><i class="fa fa-sign-in" aria-hidden="true"></i>输入</div>
                <pre>{{ phase.params_json }}</pre>
              </section>
              <section v-if="phase.output_preview" class="art-detail-section is-output">
                <div class="art-detail-label"><i class="fa fa-check-circle" aria-hidden="true"></i>输出</div>
                <pre>{{ phase.output_preview }}</pre>
              </section>
              <section v-if="phase.error" class="art-detail-section is-error">
                <div class="art-detail-label"><i class="fa fa-exclamation-triangle" aria-hidden="true"></i>错误</div>
                <pre>{{ phase.error }}</pre>
              </section>
              <section v-if="phase.observations.length" class="art-detail-section">
                <div class="art-detail-label"><i class="fa fa-eye" aria-hidden="true"></i>观察</div>
                <ul>
                  <li v-for="(observation, observationIndex) in phase.observations" :key="observationIndex">{{ observation }}</li>
                </ul>
              </section>
              <section v-if="phase.repair_history.length" class="art-detail-section">
                <div class="art-detail-label"><i class="fa fa-wrench" aria-hidden="true"></i>修复记录</div>
                <ul>
                  <li v-for="(repair, repairIndex) in phase.repair_history" :key="repairIndex">{{ repair }}</li>
                </ul>
              </section>
              <button
                v-if="phase.waiting_approval && getPermissionBadge(phase.tool_id)"
                type="button"
                class="art-auto-approve"
                @click.stop="onAutoApprove(phase.tool_id)"
              >
                <i class="fa fa-check" aria-hidden="true"></i>按已授权规则确认
              </button>
            </template>
            <pre v-else-if="isRun(phase) && phase.final_output_preview" class="art-final-output">{{ phase.final_output_preview }}</pre>
            <pre v-else-if="isPlanner(phase) && phase.detail" class="art-final-output is-error">{{ phase.detail }}</pre>
          </div>
        </details>
      </div>

      <details v-if="showPlanGraph && mermaidSource" class="art-plan-graph" @toggle="onMermaidToggle">
        <summary><i class="fa fa-share-alt" aria-hidden="true"></i>查看执行关系图</summary>
        <div ref="mermaidHostRef" class="mermaid-host" v-html="mermaidSvg"></div>
      </details>
    </div>
  </details>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type {
  AgentRunTraceData,
  TracePhase,
  TracePlannerPhase,
  TraceRunPhase,
  TraceToolPhase,
} from '@/utils/agentRunTraceModel'
import { shouldShowAgentRunPlanGraph } from '@/utils/agentRunTraceModel'
import { traceToMermaid } from '@/utils/agentRunTraceToMermaid'
import { getToolPermission, setToolPermission, type ToolPermissionScope } from '@/utils/toolPermissionCache'

const props = defineProps<{
  trace: AgentRunTraceData
}>()

const emit = defineEmits<{
  'auto-approve-tool': [toolId: string]
  'grant-tool-permission': [toolId: string, scope: ToolPermissionScope]
}>()

const STATUS_LABELS: Record<string, string> = {
  running: '执行中',
  success: '已完成',
  failed: '执行失败',
  waiting: '等待确认',
  blocked: '已阻断',
}

const TOOL_LABELS: Array<[RegExp, string]> = [
  [/business[_-]?db|database|sql/i, '业务数据库'],
  [/browser|web/i, '浏览器'],
  [/search/i, '搜索'],
  [/shell|terminal|command|exec/i, '终端'],
  [/file|document|word|pdf/i, '文档'],
  [/excel|sheet/i, '表格'],
  [/mail|message|wechat|wecom/i, '消息'],
  [/approval|approve/i, '审批中心'],
  [/customer/i, '客户资料'],
  [/product|material|inventory/i, '业务资料'],
]

const ACTION_LABELS: Record<string, string> = {
  write: '写入',
  create: '创建',
  update: '更新',
  delete: '删除',
  query: '查询',
  list: '读取列表',
  search: '搜索',
  read: '读取',
  import: '导入',
  export: '导出',
  execute: '执行',
  send: '发送',
  approve: '审批',
}

const INTENT_LABELS: Record<string, string> = {
  business_db_write: '业务数据写入',
  business_db_read: '业务数据查询',
  excel_import: '表格数据导入',
  document_generation: '办公文档生成',
}

const statusLabel = computed(() => STATUS_LABELS[props.trace.status] || props.trace.status)
const defaultOpen = computed(() => props.trace.status !== 'success')
const showPlanGraph = computed(() => shouldShowAgentRunPlanGraph(props.trace))
const toolPhases = computed(() => props.trace.phases.filter((phase): phase is TraceToolPhase => phase.kind === 'tool'))
const toolCount = computed(() => toolPhases.value.length)
const waitingCount = computed(() => toolPhases.value.filter((phase) => phase.waiting_approval || phase.status === 'waiting').length)
const failedCount = computed(() => props.trace.phases.filter((phase) => phase.status === 'failed' || phase.status === 'blocked').length)
const shortRunId = computed(() => {
  const raw = String(props.trace.run_id || '').replace(/^run[_-]?/, '')
  return raw.length > 10 ? `${raw.slice(0, 8)}…` : raw || '—'
})

const taskTitle = computed(() => {
  const intent = String(props.trace.intent || '').trim()
  if (INTENT_LABELS[intent]) return INTENT_LABELS[intent]
  const primary = toolPhases.value[0]
  if (primary && toolPhases.value.length === 1) {
    return `${toolDisplayName(primary.tool_id)} · ${actionDisplayName(primary.action)}`
  }
  if (intent) {
    const readable = intent.replace(/[_-]+/g, ' ').trim()
    return readable.length > 36 ? `${readable.slice(0, 36)}…` : readable
  }
  return toolPhases.value.length > 1 ? '多工具协同任务' : '智能任务'
})

const durationLabel = computed(() => {
  const ms = props.trace.total_duration_ms
  return ms == null ? '' : formatDuration(ms)
})

function isTool(phase: TracePhase): phase is TraceToolPhase {
  return phase.kind === 'tool'
}

function isPlanner(phase: TracePhase): phase is TracePlannerPhase {
  return phase.kind === 'planner'
}

function isRun(phase: TracePhase): phase is TraceRunPhase {
  return phase.kind === 'run'
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)}s`
  return `${Math.floor(ms / 60_000)}m ${Math.round((ms % 60_000) / 1000)}s`
}

function toolDisplayName(toolId: string): string {
  const raw = String(toolId || '').trim()
  const match = TOOL_LABELS.find(([pattern]) => pattern.test(raw))
  return match?.[1] || raw.replace(/[_-]+/g, ' ') || '工具'
}

function actionDisplayName(action: string): string {
  const raw = String(action || '').trim().toLowerCase()
  return ACTION_LABELS[raw] || raw.replace(/[_-]+/g, ' ') || '执行'
}

function toolIconClass(toolId: string, action = ''): string {
  const raw = `${toolId} ${action}`
  if (/business[_-]?db|database|sql|customer|product|material|inventory/i.test(raw)) return 'fa-database'
  if (/browser|web/i.test(raw)) return 'fa-globe'
  if (/search|query|find/i.test(raw)) return 'fa-search'
  if (/shell|terminal|command|exec|code/i.test(raw)) return 'fa-terminal'
  if (/excel|sheet|table/i.test(raw)) return 'fa-table'
  if (/file|document|word|pdf/i.test(raw)) return 'fa-file-text-o'
  if (/mail|message|wechat|wecom|send/i.test(raw)) return 'fa-envelope-o'
  if (/approval|approve/i.test(raw)) return 'fa-check-square-o'
  if (/upload|import/i.test(raw)) return 'fa-upload'
  return 'fa-wrench'
}

function phaseIconClass(phase: TracePhase): string {
  if (isTool(phase)) return toolIconClass(phase.tool_id, phase.action)
  if (isPlanner(phase)) return 'fa-list-ul'
  return 'fa-flag-checkered'
}

function statusIconClass(status: string): string {
  if (status === 'success') return 'fa-check-circle'
  if (status === 'failed') return 'fa-times-circle'
  if (status === 'waiting') return 'fa-pause-circle'
  if (status === 'blocked') return 'fa-ban'
  return 'fa-circle-o-notch fa-spin'
}

function phaseDisplayTitle(phase: TracePhase): string {
  if (isTool(phase)) return toolDisplayName(phase.tool_id)
  if (isPlanner(phase)) return phase.status === 'success' ? '执行计划已生成' : phase.title || '正在生成执行计划'
  return phase.status === 'success' ? '任务执行完成' : phase.title || '任务结束'
}

function phaseDisplaySubtitle(phase: TracePhase): string {
  if (isTool(phase)) return actionDisplayName(phase.action)
  if (isPlanner(phase) && phase.step_count) return `${phase.step_count} 个计划步骤`
  return phase.subtitle || ''
}

function hasPhaseDetails(phase: TracePhase): boolean {
  if (isTool(phase)) {
    return Boolean(
      phase.params_json ||
        phase.output_preview ||
        phase.error ||
        phase.observations.length ||
        phase.repair_history.length ||
        (phase.waiting_approval && getPermissionBadge(phase.tool_id)),
    )
  }
  if (isPlanner(phase)) return Boolean(phase.detail)
  return Boolean(phase.final_output_preview)
}

function shouldOpenPhase(phase: TracePhase): boolean {
  return phase.status === 'failed' || phase.status === 'blocked' || phase.status === 'waiting'
}

const mermaidSource = computed(() => traceToMermaid(props.trace))
const mermaidHostRef = ref<HTMLDivElement | null>(null)
const mermaidSvg = ref('')

let mermaidApi: { render: (id: string, text: string) => Promise<{ svg: string }> } | null = null
let mermaidInit = false

async function getMermaid() {
  if (!mermaidApi) {
    const mod = await import('mermaid')
    mermaidApi = mod.default as never
  }
  if (!mermaidInit) {
    ;(mermaidApi as never as { initialize: (config: Record<string, unknown>) => void }).initialize({
      startOnLoad: false,
      securityLevel: 'strict',
      theme: 'neutral',
      fontFamily: 'ui-sans-serif, system-ui, sans-serif',
    })
    mermaidInit = true
  }
  return mermaidApi
}

async function renderMermaid() {
  const source = mermaidSource.value
  if (!source) {
    mermaidSvg.value = ''
    return
  }
  try {
    const mermaid = await getMermaid()
    const id = `trace_graph_${props.trace.run_id.replace(/[^a-zA-Z0-9]/g, '')}`.slice(0, 40)
    const { svg } = await mermaid.render(id, source)
    mermaidSvg.value = svg
  } catch (error) {
    mermaidSvg.value = `<div class="mermaid-fail">流程图解析失败：${(error as Error)?.message || error}</div>`
  }
}

async function onMermaidToggle(event: Event) {
  if (!(event.target as HTMLDetailsElement).open || mermaidSvg.value) return
  await renderMermaid()
}

watch(
  () => mermaidSource.value,
  async (source, previous) => {
    if (source && source !== previous && mermaidSvg.value) await renderMermaid()
  },
)

function getPermissionBadge(toolId: string): ToolPermissionScope | null {
  return toolId ? getToolPermission(toolId) : null
}

function onAutoApprove(toolId: string) {
  setToolPermission(toolId, 'session')
  emit('grant-tool-permission', toolId, 'session')
  emit('auto-approve-tool', toolId)
}
</script>

<style scoped src="./AgentRunTrace.css"></style>
