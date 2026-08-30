<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { executeDiagnosticCommand, type DiagnosticResult } from '../application/diagnosticTerminalApi'
import { xcagiAibizDashboardUrl } from '../constants/xcagiDashboardEmbed'
import { useAuthStore } from '../stores/auth'

interface TerminalEntry {
  id: number
  command: string
  startedAt: string
  result?: DiagnosticResult
  error?: string
}

const authStore = useAuthStore()
const { isAdmin } = storeToRefs(authStore)
const iframeSrc = computed(() => xcagiAibizDashboardUrl())
const commandInput = ref('')
const commandField = ref<HTMLInputElement | null>(null)
const outputPanel = ref<HTMLElement | null>(null)
const running = ref(false)
const entries = ref<TerminalEntry[]>([])
const history = ref<string[]>([])
const historyIndex = ref(-1)
const bootstrapped = ref(false)
let nextId = 1

const quickCommands = [
  ['一键体检', 'doctor'],
  ['当前问题', 'problems'],
  ['异常任务', 'scheduler failing'],
  ['错误日志', 'logs error --limit 20'],
  ['系统事件', 'incidents --limit 20'],
  ['健康路由', 'routes health'],
]
const statusLabels: Record<string, string> = {
  healthy: '正常',
  attention: '需关注',
  degraded: '异常',
  info: '信息',
}

const statusLabel = (status: string) => statusLabels[status] || status || '未知'
const stringify = (value: unknown) => JSON.stringify(value, null, 2)
function formatMetric(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

function remember(command: string): void {
  if (history.value.at(-1) !== command) history.value.push(command)
  if (history.value.length > 60) history.value.splice(0, history.value.length - 60)
  historyIndex.value = history.value.length
}

async function scrollToLatest(): Promise<void> {
  await nextTick()
  if (outputPanel.value) outputPanel.value.scrollTop = outputPanel.value.scrollHeight
}

async function runCommand(raw?: string): Promise<void> {
  const command = String(raw ?? commandInput.value).trim() || 'doctor'
  if (command === 'clear' || command === '清屏') {
    entries.value = []
    commandInput.value = ''
    return
  }
  if (running.value) return
  running.value = true
  remember(command)
  commandInput.value = ''
  const entry: TerminalEntry = { id: nextId++, command, startedAt: new Date().toISOString() }
  entries.value.push(entry)
  await scrollToLatest()
  try {
    entry.result = await executeDiagnosticCommand(command)
  } catch (error: unknown) {
    entry.error = error instanceof Error ? error.message : String(error || '诊断请求失败')
  } finally {
    running.value = false
    await scrollToLatest()
    commandField.value?.focus()
  }
}

function moveHistory(direction: -1 | 1): void {
  if (!history.value.length) return
  historyIndex.value = Math.max(0, Math.min(history.value.length, historyIndex.value + direction))
  commandInput.value = historyIndex.value === history.value.length ? '' : history.value[historyIndex.value] || ''
  nextTick(() => commandField.value?.setSelectionRange(commandInput.value.length, commandInput.value.length))
}

async function copyResult(result: DiagnosticResult): Promise<void> {
  await navigator.clipboard.writeText(stringify(result))
}

function exportResult(entry: TerminalEntry): void {
  if (!entry.result) return
  const url = URL.createObjectURL(new Blob([stringify(entry.result)], { type: 'application/json;charset=utf-8' }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `xcmax-diagnostic-${entry.result.command}-${Date.now()}.json`
  anchor.click()
  URL.revokeObjectURL(url)
}

function globalShortcut(event: KeyboardEvent): void {
  const target = event.target as HTMLElement | null
  const typing = target?.tagName === 'INPUT' || target?.tagName === 'TEXTAREA'
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    commandField.value?.focus()
  } else if (event.key === '/' && !typing) {
    event.preventDefault()
    commandField.value?.focus()
  }
}

watch(
  isAdmin,
  (allowed) => {
    if (allowed && !bootstrapped.value) {
      bootstrapped.value = true
      void runCommand('doctor')
    }
  },
  { immediate: true },
)
onMounted(() => window.addEventListener('keydown', globalShortcut))
onBeforeUnmount(() => window.removeEventListener('keydown', globalShortcut))
</script>

<template>
  <div v-if="!isAdmin" class="ops-terminal-denied"><p>需要管理员权限。</p></div>
  <main v-else id="view-admin-ops-terminal" class="ops-terminal-view">
    <header class="terminal-header">
      <div>
        <div class="terminal-title-row">
          <span class="terminal-live-dot" aria-hidden="true"></span>
          <h2>XC 诊断终端</h2>
          <span class="read-only-badge">只读</span>
        </div>
        <p>一条命令跨账号、交付、调度器、事件、日志与 API 路由定位问题，不执行任意 Shell。</p>
      </div>
      <div class="terminal-header-actions">
        <a :href="iframeSrc" target="_blank" rel="noopener noreferrer">打开全景监控</a>
        <button type="button" @click="runCommand('help')">命令帮助</button>
      </div>
    </header>

    <section class="quick-command-bar" aria-label="常用诊断命令">
      <button v-for="quick in quickCommands" :key="quick[1]" type="button" :disabled="running" @click="runCommand(quick[1])">
        <span>{{ quick[0] }}</span
        ><code>{{ quick[1] }}</code>
      </button>
    </section>

    <section ref="outputPanel" class="terminal-output" aria-live="polite">
      <div v-if="!entries.length" class="terminal-empty">输入 <code>doctor</code> 一键体检，或输入 <code>find 关键词</code> 跨域搜索。</div>
      <article v-for="entry in entries" :key="entry.id" class="terminal-entry">
        <div class="command-line">
          <span class="prompt">xcmax&gt;</span><code>{{ entry.command }}</code>
          <time>{{ new Date(entry.startedAt).toLocaleTimeString() }}</time>
        </div>
        <div v-if="entry.error" class="terminal-error" role="alert">
          <strong>命令失败</strong><span>{{ entry.error }}</span>
          <button type="button" @click="runCommand(entry.command)">重试</button>
        </div>
        <div v-else-if="!entry.result" class="terminal-running"><span class="spinner" aria-hidden="true"></span>正在读取真实运行状态…</div>
        <div v-else class="terminal-result" :class="`terminal-status-${entry.result.status}`">
          <div class="result-summary">
            <span class="status-chip" :class="`status-${entry.result.status}`">{{ statusLabel(entry.result.status) }}</span>
            <strong>{{ entry.result.summary }}</strong
            ><span>{{ entry.result.elapsed_ms }} ms</span>
            <div class="result-actions">
              <button type="button" @click="copyResult(entry.result)">复制 JSON</button>
              <button type="button" @click="exportResult(entry)">导出</button>
            </div>
          </div>
          <dl v-if="Object.keys(entry.result.metrics || {}).length" class="metric-grid">
            <div v-for="(value, key) in entry.result.metrics" :key="key">
              <dt>{{ key }}</dt>
              <dd :title="formatMetric(value)">{{ formatMetric(value) }}</dd>
            </div>
          </dl>
          <div v-if="entry.result.items.length" class="evidence-list">
            <article
              v-for="(evidence, index) in entry.result.items"
              :key="`${evidence.kind}-${evidence.reference || index}`"
              class="evidence-item"
              :class="`severity-${evidence.severity}`"
            >
              <span class="severity-marker" aria-hidden="true"></span>
              <div class="evidence-content">
                <div class="evidence-title">
                  <span>{{ evidence.kind }}</span
                  ><strong>{{ evidence.title }}</strong>
                </div>
                <p v-if="evidence.detail">{{ evidence.detail }}</p>
                <small>{{ [evidence.source, evidence.reference, evidence.timestamp].filter(Boolean).join(' · ') }}</small>
                <details v-if="evidence.data">
                  <summary>结构化证据</summary>
                  <pre>{{ stringify(evidence.data) }}</pre>
                </details>
              </div>
            </article>
          </div>
          <p v-else class="no-result">没有匹配证据。</p>
          <ul v-if="entry.result.hints.length" class="result-hints">
            <li v-for="hint in entry.result.hints" :key="hint">{{ hint }}</li>
          </ul>
        </div>
      </article>
    </section>

    <form class="terminal-command-form" @submit.prevent="runCommand()">
      <label for="xcmax-terminal-command">xcmax&gt;</label>
      <input
        id="xcmax-terminal-command"
        ref="commandField"
        v-model="commandInput"
        type="text"
        autocomplete="off"
        spellcheck="false"
        placeholder="doctor / find 关键词 / account 用户名 / logs error"
        :disabled="running"
        @keydown.up.prevent="moveHistory(-1)"
        @keydown.down.prevent="moveHistory(1)"
      />
      <span class="shortcut-hint">⌘K</span>
      <button type="submit" :disabled="running">{{ running ? '查询中' : '执行' }}</button>
      <button type="button" class="clear-button" :disabled="running" @click="runCommand('clear')">清屏</button>
    </form>
  </main>
</template>

<style scoped src="../styles/adminOpsTerminal.css"></style>
