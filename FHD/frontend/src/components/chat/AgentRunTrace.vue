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

<style scoped>
.art-trace {
  --art-fg: #172033;
  --art-muted: #667085;
  --art-border: #dce3ec;
  --art-surface: #ffffff;
  --art-subtle: #f6f8fb;
  --art-blue: #2563eb;
  --art-green: #16a36a;
  --art-red: #dc3b3b;
  --art-amber: #c87912;
  --art-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;

  margin: 2px 0 8px;
  border: 1px solid var(--art-border);
  border-radius: 12px;
  background: var(--art-surface);
  color: var(--art-fg);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  overflow: hidden;
}

.art-summary {
  min-height: 54px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  cursor: pointer;
  list-style: none;
  user-select: none;
  transition: background 0.15s ease;
}

.art-summary:hover { background: #f8fafd; }
.art-summary::-webkit-details-marker { display: none; }

.art-disclosure {
  width: 14px;
  color: #8b95a7;
  font-size: 10px;
  transition: transform 0.16s ease;
}

.art-trace[open] > .art-summary .art-disclosure { transform: rotate(90deg); }

.art-harness-icon {
  width: 32px;
  height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 32px;
  border-radius: 9px;
  color: var(--art-blue);
  background: #eef4ff;
  border: 1px solid #d9e6ff;
  font-size: 14px;
}

.art-heading {
  min-width: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  line-height: 1.25;
}

.art-eyebrow {
  color: #8490a3;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.art-task-title {
  overflow: hidden;
  color: var(--art-fg);
  font-size: 13px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.art-tool-count,
.art-duration,
.art-step-duration {
  color: #8a94a5;
  font-family: var(--art-mono);
  font-size: 10px;
  white-space: nowrap;
}

.art-status-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 7px;
  border-radius: 999px;
  color: #596579;
  background: #f0f3f7;
  font-size: 10px;
  font-weight: 600;
  white-space: nowrap;
}

.art-status-pill.is-success { color: #087a4d; background: #eaf8f1; }
.art-status-pill.is-running { color: #1d58bd; background: #eaf2ff; }
.art-status-pill.is-waiting { color: #9a5905; background: #fff4dc; }
.art-status-pill.is-failed { color: #b42323; background: #fff0f0; }
.art-status-pill.is-blocked { color: #5e6675; background: #eef0f3; }

.art-body {
  border-top: 1px solid #e7ebf1;
  padding: 10px 12px 12px 46px;
  background: #fbfcfe;
}

.art-overview {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px 14px;
  margin-bottom: 7px;
  color: var(--art-muted);
  font-size: 10px;
}

.art-overview span { display: inline-flex; align-items: center; gap: 5px; }
.art-overview .is-warning { color: var(--art-amber); }
.art-overview .is-danger { color: var(--art-red); }
.art-overview .art-run-id { margin-left: auto; font-family: var(--art-mono); color: #98a1b0; }

.art-stream {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.art-stream::before {
  content: '';
  position: absolute;
  top: 20px;
  bottom: 20px;
  left: 15px;
  width: 1px;
  background: #dde4ed;
}

.art-step {
  position: relative;
  border: 1px solid transparent;
  border-radius: 9px;
  background: transparent;
}

.art-step[open] {
  border-color: #e1e7ef;
  background: var(--art-surface);
}

.art-step-summary {
  min-height: 38px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px 4px 2px;
  list-style: none;
  border-radius: 8px;
  cursor: pointer;
}

.art-step-summary:hover { background: rgba(238, 243, 249, 0.72); }
.art-step-summary[aria-disabled='true'] { cursor: default; }
.art-step-summary::-webkit-details-marker { display: none; }

.art-step-icon {
  position: relative;
  z-index: 1;
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 28px;
  border: 1px solid #dce4ee;
  border-radius: 8px;
  color: #546174;
  background: #fff;
  font-size: 12px;
}

.art-step.is-tool .art-step-icon { color: var(--art-blue); background: #f3f7ff; border-color: #dbe7ff; }
.art-step.is-success .art-step-icon { color: #0d8a57; }
.art-step.is-failed .art-step-icon,
.art-step.is-blocked .art-step-icon { color: var(--art-red); background: #fff6f6; border-color: #f6dada; }
.art-step.is-waiting .art-step-icon { color: var(--art-amber); background: #fff9ec; border-color: #f4e3bc; }

.art-step-heading {
  min-width: 0;
  flex: 1;
  display: flex;
  align-items: baseline;
  gap: 7px;
}

.art-step-title {
  overflow: hidden;
  color: #283448;
  font-size: 12px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.art-step-subtitle {
  color: #7f8999;
  font-size: 10px;
  white-space: nowrap;
}

.art-step-badge {
  padding: 2px 6px;
  border-radius: 999px;
  font-size: 9px;
  white-space: nowrap;
}

.art-step-badge.is-waiting { color: #925504; background: #fff0ce; }
.art-step-badge.is-retry { color: #945f13; background: #fff7e8; }

.art-step-status { width: 13px; text-align: center; font-size: 11px; color: #8f99aa; }
.art-step.is-success .art-step-status { color: var(--art-green); }
.art-step.is-failed .art-step-status,
.art-step.is-blocked .art-step-status { color: var(--art-red); }
.art-step.is-waiting .art-step-status { color: var(--art-amber); }
.art-step.is-running .art-step-status { color: var(--art-blue); }

.art-step-chevron {
  width: 10px;
  color: #a0a8b6;
  font-size: 8px;
  transition: transform 0.16s ease;
}
.art-step[open] > .art-step-summary .art-step-chevron { transform: rotate(90deg); }

.art-step-detail {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 0 8px 9px 38px;
  padding: 9px 10px;
  border-radius: 8px;
  background: var(--art-subtle);
}

.art-tool-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px 10px;
  color: #7a8595;
  font-size: 9px;
}

.art-tool-meta code {
  padding: 2px 5px;
  border: 1px solid #dce4ee;
  border-radius: 5px;
  color: #315f9c;
  background: #fff;
  font-family: var(--art-mono);
  font-size: 9px;
}

.art-permission { padding: 2px 5px; border-radius: 999px; }
.art-permission.is-session { color: #245faf; background: #e8f1ff; }
.art-permission.is-persistent { color: #08784b; background: #e6f7ef; }

.art-detail-section { display: flex; flex-direction: column; gap: 4px; }
.art-detail-label { display: flex; align-items: center; gap: 5px; color: #778294; font-size: 9px; font-weight: 600; }
.art-detail-section.is-output .art-detail-label { color: #0c8051; }
.art-detail-section.is-error .art-detail-label { color: var(--art-red); }

.art-detail-section pre,
.art-final-output {
  max-height: 180px;
  margin: 0;
  padding: 7px 8px;
  overflow: auto;
  border: 1px solid #e1e6ed;
  border-radius: 6px;
  color: #465164;
  background: #fff;
  font-family: var(--art-mono);
  font-size: 10px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

.art-detail-section.is-output pre { border-color: #d6eee3; background: #f7fcf9; }
.art-detail-section.is-error pre,
.art-final-output.is-error { border-color: #f1d5d5; color: #ad2d2d; background: #fff8f8; }

.art-detail-section ul { margin: 0; padding-left: 16px; color: #5f6b7d; font-size: 10px; line-height: 1.55; }

.art-auto-approve {
  align-self: flex-start;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 8px;
  border: 1px solid #b9dfcc;
  border-radius: 6px;
  color: #08784b;
  background: #f5fcf8;
  font-size: 10px;
  cursor: pointer;
}

.art-plan-graph { margin: 8px 0 0 38px; }
.art-plan-graph > summary {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #657186;
  font-size: 10px;
  cursor: pointer;
  list-style: none;
}
.art-plan-graph > summary::-webkit-details-marker { display: none; }
.mermaid-host { margin-top: 8px; padding: 8px; overflow-x: auto; border: 1px solid #e1e7ef; border-radius: 8px; background: #fff; }
.mermaid-host :deep(svg) { max-width: 100%; height: auto; }
.mermaid-fail { color: var(--art-red); font-size: 10px; }

@media (max-width: 720px) {
  .art-tool-count,
  .art-duration { display: none; }
  .art-summary { gap: 7px; padding-inline: 9px; }
  .art-body { padding-left: 14px; }
  .art-overview .art-run-id { display: none; }
}

@media (prefers-color-scheme: dark) {
  .art-trace {
    --art-fg: #e8edf5;
    --art-muted: #9da8b8;
    --art-border: #3a4351;
    --art-surface: #202630;
    --art-subtle: #252c37;
  }
  .art-summary:hover,
  .art-step-summary:hover { background: #29313d; }
  .art-body { border-top-color: #394250; background: #1d232c; }
  .art-task-title,
  .art-step-title { color: #e8edf5; }
  .art-harness-icon,
  .art-step-icon { background: #253044; border-color: #3d4b62; }
  .art-step[open] { border-color: #3c4655; }
  .art-stream::before { background: #3a4452; }
  .art-tool-meta code,
  .art-detail-section pre,
  .art-final-output,
  .mermaid-host { color: #d3dae5; background: #1c222b; border-color: #3a4452; }
  .art-detail-section.is-output pre { color: #bce6cf; background: #1d2b25; border-color: #315341; }
}
</style>
