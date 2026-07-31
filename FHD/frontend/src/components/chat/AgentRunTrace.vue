<template>
  <div :class="['art-trace', `is-${trace.status}`]">
    <!-- 单行 header：状态点 + intent + 状态文字 + 耗时 -->
    <div class="art-head">
      <span class="art-dot" aria-hidden="true"></span>
      <span v-if="trace.intent" class="art-intent">{{ trace.intent }}</span>
      <span class="art-status">{{ statusLabel }}</span>
      <span v-if="durationLabel" class="art-dur">{{ durationLabel }}</span>
      <span v-if="!trace.terminal" class="art-pulse" aria-hidden="true"></span>
    </div>

    <!-- phase 流：每行一个，无 box -->
    <div class="art-stream">
      <div
        v-for="(phase, idx) in trace.phases"
        :key="phase.started_event_id || idx"
        :class="['art-row', `row-${phase.kind}`, `row-${phase.status}`]"
      >
        <span class="art-marker" aria-hidden="true">{{ markerFor(phase) }}</span>
        <div class="art-row-main">
          <div class="art-row-title">
            <span class="art-title">{{ phase.title || fallbackTitle(phase) }}</span>
            <span v-if="phase.subtitle" class="art-sub">{{ phase.subtitle }}</span>
            <span v-if="phase.duration_ms != null" class="art-ms">{{ phase.duration_ms }}ms</span>
            <span v-if="isTool(phase) && phase.retries > 0" class="art-retry" title="重试次数">↻{{ phase.retries }}</span>
            <span v-if="isTool(phase) && phase.waiting_approval" class="art-wait">等待确认</span>
            <span
              v-if="isTool(phase) && getPermissionBadge(phase.tool_id)"
              class="art-perm"
              :class="`perm-${getPermissionBadge(phase.tool_id)}`"
            >
              {{ getPermissionBadge(phase.tool_id) === 'session' ? '会话授权' : '永久授权' }}
            </span>
            <button
              v-if="isTool(phase) && phase.waiting_approval && getPermissionBadge(phase.tool_id)"
              type="button"
              class="art-auto-btn"
              @click.stop="onAutoApprove(phase.tool_id)"
            >自动确认</button>
          </div>

          <!-- 工具调用 inline 折叠（无 terminal box） -->
          <details
            v-if="isTool(phase) && (phase.params_json || phase.output_preview || phase.error || phase.observations.length || phase.repair_history.length)"
            class="art-tool-detail"
          >
            <summary>
              <code v-if="phase.tool_id">{{ phase.tool_id }}</code>
              <span v-if="phase.action" class="art-action">{{ phase.action }}</span>
              <span v-if="phase.node_id" class="art-node">#{{ phase.node_id }}</span>
            </summary>
            <div class="art-tool-body">
              <pre v-if="phase.params_json" class="art-params">{{ phase.params_json }}</pre>
              <pre v-if="phase.output_preview" class="art-out">{{ phase.output_preview }}</pre>
              <pre v-if="phase.error" class="art-err">{{ phase.error }}</pre>
              <ul v-if="phase.observations.length" class="art-obs">
                <li v-for="(o, oIdx) in phase.observations" :key="oIdx">{{ o }}</li>
              </ul>
              <ul v-if="phase.repair_history.length" class="art-repairs">
                <li v-for="(r, rIdx) in phase.repair_history" :key="rIdx">{{ r }}</li>
              </ul>
            </div>
          </details>

          <!-- Run phase 最终输出 -->
          <pre v-else-if="isRun(phase) && phase.final_output_preview" class="art-final">{{ phase.final_output_preview }}</pre>

          <!-- Planner 详情 -->
          <pre v-else-if="isPlanner(phase) && phase.detail" class="art-planner-detail">{{ phase.detail }}</pre>
        </div>
      </div>
    </div>

    <!-- mermaid 计划图（折叠入口极轻量） -->
    <details v-if="mermaidSource" class="art-mermaid" @toggle="onMermaidToggle">
      <summary>查看执行计划图</summary>
      <div ref="mermaidHostRef" class="mermaid-host" v-html="mermaidSvg"></div>
    </details>
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

async function onMermaidToggle(ev: Event) {
  const open = (ev.target as HTMLDetailsElement).open
  if (!open || mermaidSvg.value) return
  await renderMermaid()
}

onMounted(() => {
  // details 默认关闭，等用户打开才渲染
})

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
  setToolPermission(toolId, 'session')
  emit('grant-tool-permission', toolId, 'session')
  emit('auto-approve-tool', toolId)
}
</script>

<style scoped>
/* Trae/Cursor 风格：无 box、左侧色条、inline 折叠、融入消息流 */
.art-trace {
  --art-fg: var(--xc-color-text-primary, #1f2937);
  --art-muted: #6b7280;
  --art-muted-2: #9ca3af;
  --art-blue: #3b82f6;
  --art-green: #10b981;
  --art-red: #ef4444;
  --art-amber: #f59e0b;
  --art-gray: #9ca3af;
  --art-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace;

  position: relative;
  margin-top: 6px;
  padding: 2px 0 2px 10px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--art-fg);
  /* 左侧 2px 色条（无 box 边框） */
  border-left: 2px solid var(--art-gray);
}

/* 状态色条 */
.art-trace.is-running { border-left-color: var(--art-blue); }
.art-trace.is-success { border-left-color: var(--art-green); }
.art-trace.is-failed { border-left-color: var(--art-red); }
.art-trace.is-waiting { border-left-color: var(--art-amber); }
.art-trace.is-blocked { border-left-color: var(--art-gray); }

/* Header：单行 inline */
.art-head {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  color: var(--art-muted);
  font-size: 11px;
  margin-bottom: 2px;
}

.art-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--art-gray);
  flex-shrink: 0;
}
.is-running .art-dot { background: var(--art-blue); }
.is-success .art-dot { background: var(--art-green); }
.is-failed .art-dot { background: var(--art-red); }
.is-waiting .art-dot { background: var(--art-amber); }

.art-intent {
  color: var(--art-fg);
  font-weight: 500;
  font-family: var(--art-mono);
  font-size: 11px;
}

.art-status {
  color: var(--art-muted-2);
  font-size: 10px;
}

.art-dur {
  color: var(--art-muted-2);
  font-family: var(--art-mono);
  font-size: 10px;
}

.art-pulse {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--art-blue);
  animation: art-pulse 1.2s ease-in-out infinite;
}

@keyframes art-pulse {
  0%, 100% { opacity: 0.3; transform: scale(0.7); }
  50% { opacity: 1; transform: scale(1.1); }
}

/* Stream：无 ol 样式，紧凑行 */
.art-stream {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.art-row {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 1px 0;
}

.art-marker {
  flex-shrink: 0;
  width: 12px;
  text-align: center;
  font-size: 10px;
  line-height: 1.6;
  color: var(--art-muted-2);
  font-family: var(--art-mono);
}

.row-success .art-marker { color: var(--art-green); }
.row-failed .art-marker { color: var(--art-red); }
.row-waiting .art-marker { color: var(--art-amber); }
.row-running .art-marker { color: var(--art-blue); }

.art-row-main {
  flex: 1;
  min-width: 0;
}

.art-row-title {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  color: var(--art-fg);
  font-size: 12px;
}

.art-title {
  color: var(--art-fg);
}

.art-sub {
  color: var(--art-muted);
  font-family: var(--art-mono);
  font-size: 10px;
}

.art-ms {
  color: var(--art-muted-2);
  font-family: var(--art-mono);
  font-size: 10px;
}

.art-retry {
  color: var(--art-amber);
  font-size: 10px;
}

.art-wait {
  color: #b45309;
  font-size: 10px;
  background: rgba(245, 158, 11, 0.12);
  padding: 0 5px;
  border-radius: 2px;
}

.art-perm {
  font-size: 10px;
  padding: 0 5px;
  border-radius: 2px;
}
.art-perm.perm-session {
  color: #1e40af;
  background: rgba(59, 130, 246, 0.12);
}
.art-perm.perm-persistent {
  color: #065f46;
  background: rgba(16, 185, 129, 0.12);
}

.art-auto-btn {
  background: transparent;
  color: #065f46;
  border: 1px solid rgba(16, 185, 129, 0.4);
  padding: 0 6px;
  border-radius: 2px;
  font-size: 10px;
  cursor: pointer;
  line-height: 1.4;
}
.art-auto-btn:hover {
  background: rgba(16, 185, 129, 0.1);
}

/* 工具调用 inline 折叠（无 terminal box） */
.art-tool-detail {
  margin-top: 2px;
  margin-left: 0;
}

.art-tool-detail > summary {
  cursor: pointer;
  user-select: none;
  color: var(--art-muted);
  font-size: 11px;
  font-family: var(--art-mono);
  list-style: none;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.art-tool-detail > summary::before {
  content: '▸';
  font-size: 9px;
  color: var(--art-muted-2);
}
.art-tool-detail[open] > summary::before {
  content: '▾';
}
.art-tool-detail > summary::-webkit-details-marker {
  display: none;
}

.art-tool-detail > summary code {
  background: rgba(59, 130, 246, 0.1);
  color: var(--art-blue);
  padding: 0 4px;
  border-radius: 2px;
  font-size: 11px;
  font-family: var(--art-mono);
}

.art-action {
  color: var(--art-muted);
  font-size: 10px;
}

.art-node {
  color: var(--art-muted-2);
  font-size: 10px;
}

.art-tool-body {
  margin-top: 4px;
  padding-left: 8px;
  border-left: 1px solid rgba(127, 127, 127, 0.2);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.art-params,
.art-out,
.art-err,
.art-final,
.art-planner-detail {
  margin: 0;
  padding: 4px 6px;
  font-family: var(--art-mono);
  font-size: 11px;
  white-space: pre-wrap;
  word-break: break-word;
  background: rgba(127, 127, 127, 0.05);
  border-radius: 3px;
  color: #4b5563;
  max-height: 160px;
  overflow: auto;
}

.art-err {
  color: var(--art-red);
  background: rgba(239, 68, 68, 0.06);
}

.art-final {
  color: #374151;
  background: rgba(16, 185, 129, 0.05);
  border-left: 2px solid var(--art-green);
  border-radius: 0 3px 3px 0;
}

.art-planner-detail {
  color: var(--art-red);
  background: rgba(239, 68, 68, 0.06);
  border-left: 2px solid var(--art-red);
  border-radius: 0 3px 3px 0;
}

.art-obs,
.art-repairs {
  margin: 0;
  padding-left: 16px;
  font-size: 11px;
  color: var(--art-muted);
  font-family: var(--art-mono);
}
.art-obs li,
.art-repairs li {
  word-break: break-word;
}

/* mermaid 折叠入口极轻量 */
.art-mermaid {
  margin-top: 4px;
}
.art-mermaid > summary {
  cursor: pointer;
  user-select: none;
  color: var(--art-muted-2);
  font-size: 10px;
  list-style: none;
  display: inline-block;
}
.art-mermaid > summary::before {
  content: '▸ ';
}
.art-mermaid[open] > summary::before {
  content: '▾ ';
}
.art-mermaid > summary::-webkit-details-marker {
  display: none;
}
.mermaid-host {
  margin-top: 4px;
  padding: 4px 0;
  text-align: left;
  overflow-x: auto;
}
.mermaid-host :deep(svg) {
  max-width: 100%;
  height: auto;
}
.mermaid-fail {
  color: var(--art-red);
  font-size: 11px;
  padding: 4px 0;
}

/* Dark theme — 跟随 prefers-color-scheme */
@media (prefers-color-scheme: dark) {
  .art-trace {
    --art-fg: #e5e7eb;
    --art-muted: #9ca3af;
    --art-muted-2: #6b7280;
  }
  .art-title,
  .art-intent {
    color: #e5e7eb;
  }
  .art-params,
  .art-out {
    background: rgba(255, 255, 255, 0.04);
    color: #d1d5db;
  }
  .art-final {
    background: rgba(16, 185, 129, 0.08);
    color: #d1d5db;
  }
  .art-obs li,
  .art-repairs li {
    color: #9ca3af;
  }
  .art-tool-body {
    border-left-color: rgba(255, 255, 255, 0.15);
  }
  .art-perm.perm-session {
    color: #93c5fd;
    background: rgba(59, 130, 246, 0.2);
  }
  .art-perm.perm-persistent {
    color: #6ee7b7;
    background: rgba(16, 185, 129, 0.2);
  }
  .art-auto-btn {
    color: #6ee7b7;
    border-color: rgba(16, 185, 129, 0.5);
  }
}
</style>
