<template>
  <main class="desktop-runtime">
    <section class="panel panel--head">
      <div>
        <h1>桌面运行时</h1>
        <p class="muted">查看本机数据位置、备份与更新状态。数据保存在您自己的电脑上。</p>
      </div>
      <div class="head-actions">
        <button type="button" class="btn" @click="refresh">刷新状态</button>
        <button v-if="isDesktopShell" type="button" class="btn btn--primary" @click="checkUpdates">
          检查桌面更新
        </button>
      </div>
    </section>

    <section class="panel">
      <h2>运行状态</h2>
      <dl v-if="status" class="kv">
        <dt>桌面模式</dt>
        <dd>{{ status.desktopMode ? '是' : '否' }}</dd>
        <dt>数据目录</dt>
        <dd class="kv-with-action">
          <span class="mono">{{ status.dataDir || '—' }}</span>
          <button
            v-if="canOpenDataDir"
            type="button"
            class="btn btn--sm"
            @click="openDataDir"
          >
            打开数据目录
          </button>
        </dd>
        <dt>数据库</dt>
        <dd class="mono">{{ status.database || '—' }}</dd>
        <dt>存储模式</dt>
        <dd>{{ storageModeLabel }}</dd>
        <dt>连接（脱敏）</dt>
        <dd class="mono">{{ status.databaseUrlRedacted || '—' }}</dd>
        <dt>Mod 目录</dt>
        <dd class="mono">{{ status.modsDir || '—' }}</dd>
        <dt>模型目录</dt>
        <dd class="mono">{{ status.modelsDir || '—' }}</dd>
      </dl>
      <p v-else>正在加载...</p>
    </section>

    <section class="panel">
      <h2>数据备份</h2>
      <template v-if="status">
        <dl class="kv">
          <dt>上次备份</dt>
          <dd>
            <template v-if="lastBackupLabel">{{ lastBackupLabel }}</template>
            <template v-else>还没有备份（桌面版每天会自动备份一次）</template>
          </dd>
          <dt v-if="status.lastBackup?.filename">备份文件</dt>
          <dd v-if="status.lastBackup?.filename" class="mono">
            {{ status.lastBackup.filename }}（{{ formatBytes(status.lastBackup.size) }}）
          </dd>
        </dl>
        <div class="backup-actions">
          <button
            type="button"
            class="btn btn--primary"
            :disabled="backingUp || !status.desktopMode"
            @click="backupNow"
          >
            {{ backingUp ? '正在备份…' : '立即备份' }}
          </button>
          <span v-if="backupResult" class="backup-result" :class="{ 'is-error': backupFailed }">
            {{ backupResult }}
          </span>
        </div>
        <p class="muted backup-hint">
          自动备份每日一次，保留 7 天（周备份保留 28 天），存放在数据目录 backups/ 下。
        </p>
      </template>
      <p v-else>正在加载...</p>
    </section>

    <section class="panel">
      <h2>本地模型</h2>
      <ul v-if="models.length" class="model-list">
        <li v-for="model in models" :key="`${model.name}:${model.version}`">
          <strong>{{ model.name }}</strong> {{ model.version }}
          <span class="mono">{{ model.path }}</span>
        </li>
      </ul>
      <p v-else class="muted">暂无已安装模型。桌面版会在首次使用对应能力时按需下载。</p>
    </section>

    <section v-if="isDesktopShell || updateEvents.length" class="panel">
      <h2>桌面更新</h2>
      <p v-if="lastUpdateCheckLabel" class="muted">上次检查：{{ lastUpdateCheckLabel }}</p>
      <ul v-if="updateEvents.length" class="update-list">
        <li v-for="(event, idx) in updateEvents" :key="idx">
          <time>{{ event.time }}</time>
          <span>{{ event.text }}</span>
        </li>
      </ul>
      <p v-else class="muted">暂无更新动态。桌面版启动后会自动定期检查更新。</p>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api, ApiError } from '@/api/core'
import { rememberUpdateCheckTime, readUpdateCheckTime } from '@/utils/desktopUpdateCheckTime'
import { describeUpdateEvent, type RawUpdateEvent } from '@/utils/desktopUpdateEvents'

interface DesktopStatus {
  desktopMode: boolean
  dataDir: string
  database: string
  modsDir: string
  modelsDir: string
  storageMode?: string
  databaseUrlRedacted?: string
  profilePath?: string
  lastBackup?: {
    path?: string | null
    filename?: string | null
    timestamp?: string | null
    size?: number | null
  }
}

interface ModelInfo {
  name: string
  version: string
  path: string
}

interface ReadableUpdateEvent {
  time: string
  text: string
}

const status = ref<DesktopStatus | null>(null)
const models = ref<ModelInfo[]>([])
const updateEvents = ref<ReadableUpdateEvent[]>([])
const backingUp = ref(false)
const backupResult = ref('')
const backupFailed = ref(false)
const lastUpdateCheckAt = ref<string>(readUpdateCheckTime())
const isDesktopShell = computed(() => Boolean(window.xcagiDesktop))
const canOpenDataDir = computed(() => Boolean(window.xcagiDesktop?.openDataDir))

const storageModeLabel = computed(() => {
  const mode = status.value?.storageMode
  if (mode === 'local_sqlite') return '本地 SQLite'
  if (mode === 'remote_postgresql') return '远程 PostgreSQL'
  return mode || '—'
})

const lastBackupLabel = computed(() => {
  const ts = status.value?.lastBackup?.timestamp
  if (!ts) return ''
  return formatDateTime(ts)
})

const lastUpdateCheckLabel = computed(() =>
  lastUpdateCheckAt.value ? formatDateTime(lastUpdateCheckAt.value) : '',
)

let unsubscribe: (() => void) | undefined

function formatDateTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function formatBytes(size?: number | null): string {
  const n = Number(size)
  if (!Number.isFinite(n) || n <= 0) return '—'
  if (n >= 1024 * 1024 * 1024) return `${(n / (1024 * 1024 * 1024)).toFixed(1)} GB`
  if (n >= 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`
  if (n >= 1024) return `${(n / 1024).toFixed(0)} KB`
  return `${n} B`
}

function pushUpdateEvent(event: unknown) {
  const now = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  updateEvents.value.unshift({
    time: `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`,
    text: describeUpdateEvent(event),
  })
  if (updateEvents.value.length > 20) {
    updateEvents.value.length = 20
  }
  const type = (event as RawUpdateEvent | null)?.type
  if (type === 'checking-for-update' || type === 'update-not-available' || type === 'update-available') {
    lastUpdateCheckAt.value = rememberUpdateCheckTime()
  }
}

async function refresh() {
  const [statusResponse, modelsResponse] = await Promise.all([
    fetch('/api/desktop/status'),
    fetch('/api/desktop/models'),
  ])
  status.value = await statusResponse.json()
  const payload = await modelsResponse.json()
  models.value = payload.models || []
}

async function checkUpdates() {
  lastUpdateCheckAt.value = rememberUpdateCheckTime()
  try {
    await window.xcagiDesktop?.checkForUpdates()
  } catch (error) {
    pushUpdateEvent({ type: 'error', data: { message: error instanceof Error ? error.message : String(error) } })
  }
}

async function openDataDir() {
  try {
    await window.xcagiDesktop?.openDataDir?.()
  } catch {
    /* ignore */
  }
}

async function backupNow() {
  backingUp.value = true
  backupResult.value = ''
  backupFailed.value = false
  try {
    // 走统一 api 客户端：自动携带 X-CSRF-Token（后端 CSRFMiddleware 校验变更请求）
    const body = (await api.post('/api/desktop/backup-now', {})) as {
      success?: boolean
      backup?: { filename?: string; size?: number }
      detail?: string
    }
    if (body?.success) {
      backupResult.value = `备份完成：${body.backup?.filename || ''}（${formatBytes(body.backup?.size)}）`
      await refresh()
    } else {
      backupFailed.value = true
      backupResult.value = body?.detail || '备份失败，请稍后重试'
    }
  } catch (error) {
    backupFailed.value = true
    if (error instanceof ApiError) {
      const detail = (error.data as { detail?: string } | null)?.detail
      backupResult.value = detail || error.message || '备份失败，请稍后重试'
    } else {
      backupResult.value = '备份失败，请检查后端是否运行'
    }
  } finally {
    backingUp.value = false
  }
}

onMounted(() => {
  void refresh()
  unsubscribe = window.xcagiDesktop?.onUpdateEvent((event) => {
    pushUpdateEvent(event)
  })
})

onUnmounted(() => {
  unsubscribe?.()
})
</script>

<style scoped>
.desktop-runtime {
  display: grid;
  gap: 16px;
  padding: 24px;
  overflow-y: auto;
}

.panel {
  border: 1px solid #d9dee8;
  border-radius: 12px;
  padding: 16px 20px;
  background: #fff;
}

.panel--head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.panel h1 {
  margin: 0 0 4px;
  font-size: 20px;
}

.panel h2 {
  margin: 0 0 12px;
  font-size: 15px;
}

.panel p {
  margin: 0;
}

.muted {
  color: #6b7280;
  font-size: 13px;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  word-break: break-all;
}

.head-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.btn {
  border: 1px solid #cbd5e1;
  background: #fff;
  color: #334155;
  border-radius: 8px;
  padding: 7px 14px;
  font-size: 13px;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease;
}

.btn:hover {
  border-color: #94a3b8;
  background: #f8fafc;
}

.btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.btn--primary {
  background: #2563eb;
  border-color: #2563eb;
  color: #fff;
}

.btn--primary:hover {
  background: #1d4ed8;
  border-color: #1d4ed8;
}

.btn--sm {
  padding: 3px 10px;
  font-size: 12px;
}

.kv {
  display: grid;
  grid-template-columns: 110px 1fr;
  gap: 8px 16px;
  margin: 0;
}

.kv dt {
  color: #6b7280;
  font-size: 13px;
}

.kv dd {
  margin: 0;
  font-size: 13px;
  color: #111827;
}

.kv-with-action {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.backup-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 12px;
  flex-wrap: wrap;
}

.backup-result {
  font-size: 13px;
  color: #15803d;
}

.backup-result.is-error {
  color: #b91c1c;
}

.backup-hint {
  margin-top: 10px;
}

.model-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 8px;
}

.model-list li {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 13px;
}

.update-list {
  margin: 8px 0 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 6px;
}

.update-list li {
  display: flex;
  gap: 10px;
  font-size: 13px;
  color: #111827;
}

.update-list time {
  color: #6b7280;
  font-variant-numeric: tabular-nums;
  flex: none;
}
</style>
