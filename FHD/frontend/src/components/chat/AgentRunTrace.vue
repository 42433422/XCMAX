<template>
  <div :class="['agent-run-trace', `is-${trace.status}`]">
    <!-- 顶部：意图徽章 + 状态 dot + 耗时 -->
    <div class="trace-header">
      <span class="trace-dot" :class="`dot-${trace.status}`" aria-hidden="true"></span>
      <span class="trace-badge">agent_run</span>
      <span v-if="trace.intent" class="trace-intent">{{ trace.intent }}</span>
      <span class="trace-status-label">{{ statusLabel }}</span>
      <span v-if="durationLabel" class="trace-duration">{{ durationLabel }}</span>
      <span v-if="!trace.terminal" class="trace-running-pulse" aria-hidden="true"></span>
    </div>

    <!-- mermaid 计划图（折叠，按需渲染） -->
    <details v-if="mermaidSource" class="trace-mermaid" @toggle="onMermaidToggle">
      <summary>查看执行计划图</summary>
      <div ref="mermaidHostRef" class="mermaid-host" v-html="mermaidSvg"></div>
    </details>

    <!-- 垂直时间线 -->
    <ol class="trace-stream">
      <li
        v-for="(phase, idx) in trace.phases"
        :key="phase.started_event_id || idx"
        :class="['trace-phase', `phase-${phase.kind}`, `phase-${phase.status}`]"
      >
        <!-- 状态指示符 -->
        <span class="phase-marker" aria-hidden="true">{{ markerFor(phase) }}</span>

        <!-- 主行：标题 + 副标题 + 耗时 -->
        <div class="phase-main">
          <div class="phase-title-row">
            <span class="phase-title">{{ phase.title || fallbackTitle(phase) }}</span>
            <span v-if="phase.subtitle" class="phase-subtitle">{{ phase.subtitle }}</span>
            <span v-if="phase.duration_ms != null" class="phase-duration">{{ phase.duration_ms }}ms</span>
            <span v-if="isTool(phase) && phase.retries > 0" class="phase-retries">↻ {{ phase.retries }}</span>
            <span v-if="isTool(phase) && phase.waiting_approval" class="phase-waiting-chip">等待确认</span>
            <span v-if="isTool(phase) && getPermissionBadge(phase.tool_id)" class="phase-permission-chip" :class="`perm-${getPermissionBadge(phase.tool_id)}`">
              {{ getPermissionBadge(phase.tool_id) === 'session' ? '已授权·会话' : '已授权·永久' }}
            </span>
            <button
              v-if="isTool(phase) && phase.waiting_approval && getPermissionBadge(phase.tool_id)"
              type="button"
              class="phase-auto-approve-btn"
              @click.stop="onAutoApprove(phase.tool_id)"
            >
              自动确认
            </button>
          </div>

          <!-- 工具调用 terminal 块 -->
          <div v-if="isTool(phase)" class="phase-terminal">
            <div v-if="phase.tool_id || phase.action" class="terminal-header">
              <span v-if="phase.tool_id" class="terminal-tool">{{ phase.tool_id }}</span>
              <span v-if="phase.action" class="terminal-action">{{ phase.action }}</span>
              <span v-if="phase.node_id" class="terminal-node">#{{ phase.node_id }}</span>
            </div>
            <pre v-if="phase.params_json" class="terminal-params">{{ phase.params_json }}</pre>
            <details v-if="phase.output_preview || phase.error || phase.observations.length || phase.repair_history.length" class="terminal-details">
              <summary>展开输出</summary>
              <div v-if="phase.output_preview" class="terminal-output">
                <div class="output-label">output</div>
                <pre>{{ phase.output_preview }}</pre>
              </div>
              <div v-if="phase.observations.length" class="terminal-observations">
                <div class="output-label">observations</div>
                <ul>
                  <li v-for="(o, oIdx) in phase.observations" :key="oIdx">{{ o }}</li>
                </ul>
              </div>
              <div v-if="phase.error" class="terminal-error">
                <div class="output-label">error</div>
                <pre>{{ phase.error }}</pre>
              </div>
              <div v-if="phase.repair_history.length" class="terminal-repairs">
                <div class="output-label">repair history</div>
                <ul>
                  <li v-for="(r, rIdx) in phase.repair_history" :key="rIdx">{{ r }}</li>
                </ul>
              </div>
            </details>
          </div>

          <!-- Run phase 的最终输出预览 -->
          <div v-else-if="isRun(phase) && phase.final_output_preview" class="phase-final-output">
            <pre>{{ phase.final_output_preview }}</pre>
          </div>

          <!-- Planner phase 的详情（如计划被阻断时的错误） -->
          <div v-else-if="isPlanner(phase) && phase.detail" class="phase-planner-detail">
            <pre>{{ phase.detail }}</pre>
          </div>
        </div>
      </li>
    </ol>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import type {
  AgentRunTraceData,
  TracePhase,
  TracePlannerPhase,
  TraceToolPhase,
  TraceRunPhase,
} from '@/utils/agentRunTraceModel'
import { traceToMermaid } from '@/utils/agentRunTraceToMermaid'
import {
  getToolPermission,
  setToolPermission,
  type ToolPermissionScope,
} from '@/utils/toolPermissionCache'

const props = defineProps<{
  trace: AgentRunTraceData
}>()

const emit = defineEmits<{
  /** 用户点击"自动确认"：父组件可据此调用现有的审批确认流程 */
  'auto-approve-tool': [toolId: string]
  /** 用户主动授权某工具（按 scope 记忆） */
  'grant-tool-permission': [toolId: string, scope: ToolPermissionScope]
}>()

const STATUS_LABELS: Record<string, string> = {
  running: '执行中',
  success: '完成',
  failed: '失败',
  waiting: '等待确认',
  blocked: '已阻断',
}

const statusLabel = computed(() => STATUS_LABELS[props.trace.status] || props.trace.status)

const durationLabel = computed(() => {
  const ms = props.trace.total_duration_ms
  if (ms == null) return ''
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(2)}s`
})

function isTool(p: TracePhase): p is TraceToolPhase {
  return p.kind === 'tool'
}
function isPlanner(p: TracePhase): p is TracePlannerPhase {
  return p.kind === 'planner'
}
function isRun(p: TracePhase): p is TraceRunPhase {
  return p.kind === 'run'
}

function markerFor(p: TracePhase): string {
  if (p.kind === 'planner') {
    return p.status === 'success' ? '●' : p.status === 'failed' ? '✗' : '◌'
  }
  if (p.kind === 'tool') {
    if (p.status === 'success') return '✓'
    if (p.status === 'failed') return '✗'
    if (p.status === 'waiting') return '⏸'
    if (p.status === 'blocked') return '⚠'
    return '▸'
  }
  return p.status === 'success' ? '●' : '✗'
}

function fallbackTitle(p: TracePhase): string {
  if (p.kind === 'planner') return '执行计划'
  if (p.kind === 'tool') return '工具调用'
  return '运行结束'
}

/* ---------------- mermaid 计划图渲染 ---------------- */

const mermaidSource = computed(() => traceToMermaid(props.trace))
const mermaidHostRef = ref<HTMLDivElement | null>(null)
const mermaidSvg = ref<string>('')

let mermaidApi: {
  render: (id: string, text: string) => Promise<{ svg: string }>
} | null = null
let mermaidInit = false

async function getMermaid() {
  if (!mermaidApi) {
    const mod = await import('mermaid')
    mermaidApi = mod.default as never
  }
  if (!mermaidInit) {
    ;(mermaidApi as never as { initialize: (c: Record<string, unknown>) => void }).initialize({
      startOnLoad: false,
      securityLevel: 'strict',
      theme: 'dark',
      fontFamily: 'ui-sans-serif, system-ui, sans-serif',
    })
    mermaidInit = true
  }
  return mermaidApi
}

async function renderMermaid() {
  const src = mermaidSource.value
  if (!src) {
    mermaidSvg.value = ''
    return
  }
  try {
    const mer = await getMermaid()
    const id = `trace_graph_${props.trace.run_id.replace(/[^a-zA-Z0-9]/g, '')}`.slice(0, 40)
    const { svg } = await mer.render(id, src)
    mermaidSvg.value = svg
  } catch (e) {
    mermaidSvg.value = `<div class="mermaid-fail">流程图解析失败：${(e as Error)?.message || e}</div>`
  }
}

/** details 展开（toggle）时按需渲染——避免每个折叠卡都加载 mermaid */
async function onMermaidToggle(ev: Event) {
  const open = (ev.target as HTMLDetailsElement).open
  if (!open || mermaidSvg.value) return
  await renderMermaid()
}

onMounted(() => {
  // 如果 details 默认是关闭的，等用户打开才渲染。这里不做预渲染。
})

// 当 trace 增量更新（流式轮询）时，如果 details 已展开则重新渲染
watch(
  () => mermaidSource.value,
  async (src, prev) => {
    if (src && src !== prev && mermaidSvg.value) {
      await renderMermaid()
    }
  },
)

/* ---------------- 工具权限缓存 ---------------- */

function getPermissionBadge(toolId: string): ToolPermissionScope | null {
  if (!toolId) return null
  return getToolPermission(toolId)
}

function onAutoApprove(toolId: string) {
  // 默认按 session scope 授权（用户可在父组件弹层改为 persistent）
  setToolPermission(toolId, 'session')
  emit('grant-tool-permission', toolId, 'session')
  emit('auto-approve-tool', toolId)
}
</script>

<style scoped>
.agent-run-trace {
  --trace-fg: var(--xc-color-text-primary, #1f2937);
  --trace-muted: #6b7280;
  --trace-border: #e5e7eb;
  --trace-bg: #f9fafb;
  --trace-blue: #3b82f6;
  --trace-green: #10b981;
  --trace-red: #ef4444;
  --trace-amber: #f59e0b;
  --trace-gray: #9ca3af;
  --trace-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace;

  margin-top: 8px;
  border: 1px solid var(--trace-border);
  border-radius: 8px;
  background: var(--trace-bg);
  font-size: 12px;
  color: var(--trace-fg);
  overflow: hidden;
}

/* Header */
.trace-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  background: rgba(0, 0, 0, 0.02);
  border-bottom: 1px solid var(--trace-border);
  font-family: var(--trace-mono);
}

.trace-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.dot-running {
  background: var(--trace-blue);
}
.dot-success {
  background: var(--trace-green);
}
.dot-failed {
  background: var(--trace-red);
}
.dot-waiting {
  background: var(--trace-amber);
}
.dot-blocked {
  background: var(--trace-gray);
}

.trace-badge {
  background: rgba(59, 130, 246, 0.1);
  color: var(--trace-blue);
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.5px;
}

.trace-intent {
  color: var(--trace-fg);
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 220px;
}

.trace-status-label {
  margin-left: auto;
  color: var(--trace-muted);
  font-size: 11px;
}

.trace-duration {
  color: var(--trace-muted);
  font-size: 11px;
}

.trace-running-pulse {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--trace-blue);
  animation: trace-pulse 1.2s ease-in-out infinite;
}

@keyframes trace-pulse {
  0%, 100% { opacity: 0.3; transform: scale(0.8); }
  50% { opacity: 1; transform: scale(1.1); }
}

/* Mermaid 计划图（折叠） */
.trace-mermaid {
  border-bottom: 1px solid var(--trace-border);
  background: #fff;
}
.trace-mermaid > summary {
  padding: 4px 10px;
  font-size: 10px;
  color: var(--trace-muted);
  cursor: pointer;
  user-select: none;
}
.trace-mermaid[open] > summary {
  border-bottom: 1px solid var(--trace-border);
}
.mermaid-host {
  padding: 8px 10px;
  text-align: center;
  overflow-x: auto;
}
.mermaid-host :deep(svg) {
  max-width: 100%;
  height: auto;
}
.mermaid-fail {
  color: var(--trace-red);
  font-size: 11px;
  padding: 6px;
}

/* 工具权限徽章 */
.phase-permission-chip {
  background: rgba(16, 185, 129, 0.15);
  color: #065f46;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 10px;
  font-weight: 500;
}
.phase-permission-chip.perm-session {
  background: rgba(59, 130, 246, 0.15);
  color: #1e40af;
}
.phase-permission-chip.perm-persistent {
  background: rgba(16, 185, 129, 0.15);
  color: #065f46;
}
.phase-auto-approve-btn {
  background: rgba(16, 185, 129, 0.15);
  color: #065f46;
  border: 1px solid rgba(16, 185, 129, 0.4);
  padding: 1px 8px;
  border-radius: 3px;
  font-size: 10px;
  cursor: pointer;
}
.phase-auto-approve-btn:hover {
  background: rgba(16, 185, 129, 0.25);
}

/* Stream */
.trace-stream {
  list-style: none;
  padding: 6px 10px 8px;
  margin: 0;
  position: relative;
}

.trace-stream::before {
  content: '';
  position: absolute;
  left: 14px;
  top: 12px;
  bottom: 12px;
  width: 1px;
  background: var(--trace-border);
}

.trace-phase {
  position: relative;
  padding-left: 18px;
  padding-bottom: 6px;
}
.trace-phase:last-child {
  padding-bottom: 0;
}

.phase-marker {
  position: absolute;
  left: 8px;
  top: 0;
  width: 13px;
  text-align: center;
  font-size: 10px;
  line-height: 14px;
  background: var(--trace-bg);
  color: var(--trace-muted);
}

/* Phase status colors */
.phase-success .phase-marker {
  color: var(--trace-green);
}
.phase-failed .phase-marker {
  color: var(--trace-red);
}
.phase-waiting .phase-marker {
  color: var(--trace-amber);
}
.phase-running .phase-marker {
  color: var(--trace-blue);
}

.phase-main {
  min-width: 0;
}

.phase-title-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.phase-title {
  color: var(--trace-fg);
  font-weight: 500;
}

.phase-subtitle {
  color: var(--trace-muted);
  font-family: var(--trace-mono);
  font-size: 11px;
}

.phase-duration {
  color: var(--trace-muted);
  font-family: var(--trace-mono);
  font-size: 10px;
}

.phase-retries {
  color: var(--trace-amber);
  font-size: 10px;
}

.phase-waiting-chip {
  background: rgba(245, 158, 11, 0.15);
  color: #b45309;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 10px;
  font-weight: 500;
}

/* Terminal block (tool phase) */
.phase-terminal {
  margin-top: 4px;
  border: 1px solid var(--trace-border);
  border-left: 2px solid var(--trace-blue);
  border-radius: 4px;
  background: #fff;
  font-family: var(--trace-mono);
  overflow: hidden;
}

.phase-failed .phase-terminal {
  border-left-color: var(--trace-red);
}

.terminal-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 3px 8px;
  background: rgba(0, 0, 0, 0.03);
  border-bottom: 1px solid var(--trace-border);
  font-size: 11px;
}

.terminal-tool {
  color: var(--trace-blue);
  font-weight: 600;
}

.terminal-action {
  color: var(--trace-fg);
}

.terminal-node {
  color: var(--trace-muted);
  margin-left: auto;
  font-size: 10px;
}

.terminal-params {
  margin: 0;
  padding: 6px 8px;
  font-size: 11px;
  color: #4b5563;
  background: #fafafa;
  border-bottom: 1px solid var(--trace-border);
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 120px;
  overflow: auto;
}

.terminal-details {
  border-top: 1px solid transparent;
}

.terminal-details > summary {
  padding: 3px 8px;
  font-size: 10px;
  color: var(--trace-muted);
  cursor: pointer;
  user-select: none;
}

.terminal-details[open] > summary {
  border-bottom: 1px solid var(--trace-border);
}

.terminal-output,
.terminal-observations,
.terminal-error,
.terminal-repairs {
  padding: 4px 8px;
  font-size: 11px;
}

.output-label {
  color: var(--trace-muted);
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 2px;
}

.terminal-output pre,
.terminal-error pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  color: #374151;
  font-family: var(--trace-mono);
}

.terminal-error pre {
  color: var(--trace-red);
}

.terminal-observations ul,
.terminal-repairs ul {
  margin: 0;
  padding-left: 16px;
}

.terminal-observations li,
.terminal-repairs li {
  color: #4b5563;
  font-family: var(--trace-mono);
  word-break: break-word;
}

/* Run phase final output */
.phase-final-output {
  margin-top: 4px;
  padding: 4px 8px;
  border-radius: 4px;
  background: rgba(16, 185, 129, 0.06);
  border-left: 2px solid var(--trace-green);
}

.phase-failed .phase-final-output {
  background: rgba(239, 68, 68, 0.06);
  border-left-color: var(--trace-red);
}

.phase-final-output pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--trace-mono);
  font-size: 11px;
}

/* Planner phase detail */
.phase-planner-detail {
  margin-top: 4px;
  padding: 4px 8px;
  background: rgba(239, 68, 68, 0.06);
  border-left: 2px solid var(--trace-red);
  border-radius: 4px;
}

.phase-planner-detail pre {
  margin: 0;
  white-space: pre-wrap;
  font-family: var(--trace-mono);
  font-size: 11px;
  color: var(--trace-red);
}

/* Dark theme — 跟随 prefers-color-scheme（MessageBody.vue 同款策略） */
@media (prefers-color-scheme: dark) {
  .agent-run-trace {
    --trace-fg: #e5e7eb;
    --trace-muted: #9ca3af;
    --trace-border: #374151;
    --trace-bg: #1f2937;
  }

  .trace-header {
    background: rgba(255, 255, 255, 0.03);
  }

  .phase-terminal {
    background: #111827;
  }

  .terminal-header {
    background: rgba(255, 255, 255, 0.04);
  }

  .terminal-params {
    background: #0b1220;
    color: #d1d5db;
  }

  .terminal-output pre,
  .terminal-observations li,
  .terminal-repairs li {
    color: #d1d5db;
  }

  .trace-mermaid {
    background: #0b1220;
  }
  .phase-permission-chip.perm-session {
    background: rgba(59, 130, 246, 0.25);
    color: #93c5fd;
  }
  .phase-permission-chip.perm-persistent {
    background: rgba(16, 185, 129, 0.25);
    color: #6ee7b7;
  }
  .phase-auto-approve-btn {
    background: rgba(16, 185, 129, 0.2);
    color: #6ee7b7;
    border-color: rgba(16, 185, 129, 0.5);
  }
}
</style>
