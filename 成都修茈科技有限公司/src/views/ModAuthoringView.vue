<template>
  <div class="authoring-page">
    <div v-if="loading" class="loading">加载中...</div>
    <div v-else-if="loadError" class="panel panel-err">
      <p>{{ loadError }}</p>
      <button type="button" class="btn" @click="goRepo">返回 Mod 仓库</button>
    </div>
    <template v-else-if="modData">
      <header class="page-header">
        <div class="header-top">
          <button type="button" class="btn btn-ghost" @click="goRepo">← Mod 仓库</button>
          <span
            class="badge"
            :class="modData.validation_ok ? 'badge-ok' : 'badge-warn'"
          >
            {{ modData.validation_ok ? 'manifest 校验通过' : 'manifest 待修正' }}
          </span>
        </div>
        <h1 class="page-title">{{ modData.manifest?.name || modData.id }}</h1>
        <p class="page-sub">
          <code class="mono">{{ modData.id }}</code>
          <span v-if="modData.manifest?.version" class="muted"> · v{{ modData.manifest.version }}</span>
        </p>
      </header>

      <div v-if="message" :class="['flash', messageOk ? 'flash-ok' : 'flash-err']">{{ message }}</div>

      <nav class="tabs">
        <button
          v-for="t in tabs"
          :key="t.id"
          type="button"
          class="tab"
          :class="{ active: tab === t.id }"
          @click="tab = t.id"
        >
          {{ t.label }}
        </button>
      </nav>

      <!-- 指南与清单 -->
      <section v-show="tab === 'guide'" class="panel">
        <h2 class="panel-title">XCAGI 6.0 Mod 要点</h2>
        <p class="muted small">
          完整字段与契约请以宿主仓库中的
          <strong>MOD_AUTHORING_GUIDE.md</strong>（XCAGI MOD 作者指南）为准；此处为制作时常用摘要。
        </p>
        <ul class="guide-list">
          <li>物理路径 <code class="mono">mods/&lt;mod_id&gt;/</code>，目录名须与 <code class="mono">manifest.id</code> 一致。</li>
          <li>根目录必须有 <code class="mono">manifest.json</code>；<code class="mono">backend/__init__.py</code> 必须存在（可为空）。</li>
          <li>
            <code class="mono">backend.entry</code> 指向 <code class="mono">backend/&lt;entry&gt;.py</code>，推荐导出
            <code class="mono">register_fastapi_routes(app, mod_id)</code>；禁止新 Mod 使用 Flask
            <code class="mono">register_blueprints</code>。
          </li>
          <li>前端约定：<code class="mono">frontend/routes.js</code> 导出路由与菜单；见指南 §8。</li>
          <li><code class="mono">hooks</code> / <code class="mono">comms.exports</code> / <code class="mono">workflow_employees</code> / <code class="mono">bundle</code> 见指南 §9–§11、§14。</li>
        </ul>

        <h3 class="sub-title">本 Mod 结构检查</h3>
        <ul class="checklist">
          <li v-for="row in checklist" :key="row.key" :class="{ ok: row.ok, warn: !row.ok }">
            <span class="mark">{{ row.ok ? '✓' : '○' }}</span>
            {{ row.label }}
            <span v-if="row.hint" class="hint">{{ row.hint }}</span>
          </li>
        </ul>

        <div v-if="artifactNote" class="artifact-note">{{ artifactNote }}</div>
      </section>

      <!-- manifest -->
      <section v-show="tab === 'manifest'" class="panel">
        <div class="panel-actions">
          <button type="button" class="btn btn-primary" :disabled="savingManifest" @click="saveManifest">
            {{ savingManifest ? '保存中…' : '保存 manifest' }}
          </button>
          <button type="button" class="btn" :disabled="loading" @click="reload">重新加载</button>
        </div>
        <p v-if="manifestSaveWarnings.length" class="warn-block">
          保存后提示：<span v-for="(w, i) in manifestSaveWarnings" :key="i">{{ w }}<br v-if="i < manifestSaveWarnings.length - 1" /></span>
        </p>
        <textarea v-model="manifestText" class="code-area" spellcheck="false" />
      </section>

      <!-- 文件 -->
      <section v-show="tab === 'files'" class="panel">
        <div class="file-toolbar">
          <label class="label-inline">文件</label>
          <select v-model="selectedPath" class="select" @change="onPathSelect">
            <option value="">选择路径…</option>
            <option v-for="p in sortedFiles" :key="p" :value="p">{{ p }}</option>
          </select>
          <button type="button" class="btn" :disabled="!selectedPath || loadingFile" @click="loadSelectedFile">
            读取
          </button>
          <button type="button" class="btn btn-primary" :disabled="!selectedPath || savingFile" @click="saveFile">
            {{ savingFile ? '保存中…' : '保存文件' }}
          </button>
        </div>
        <p v-if="fileWarnings.length" class="warn-block">
          manifest 相关提示：<span v-for="(w, i) in fileWarnings" :key="i">{{ w }}<br v-if="i < fileWarnings.length - 1" /></span>
        </p>
        <textarea
          v-model="fileContent"
          class="code-area"
          spellcheck="false"
          :placeholder="selectedPath ? '' : '请选择文件并点击「读取」'"
        />
      </section>

      <!-- 扫描与诊断 -->
      <section v-show="tab === 'scan'" class="panel">
        <div class="panel-actions">
          <button type="button" class="btn" :disabled="loadingSummary" @click="refreshSummary">
            {{ loadingSummary ? '刷新中…' : '刷新扫描' }}
          </button>
        </div>
        <template v-if="summary">
          <p class="small">
            蓝图文件：
            <code v-if="summary.blueprint_file" class="mono">{{ summary.blueprint_file }}</code>
            <span v-else class="muted">未找到 backend/blueprints.py 或根目录 blueprints.py</span>
          </p>
          <p v-if="summary.validation_ok === false && summary.warnings?.length" class="warn-block">
            <span v-for="(w, i) in summary.warnings" :key="i">{{ w }}<br /></span>
          </p>
          <p v-else-if="summary.validation_ok" class="ok-line">当前 manifest 校验无警告。</p>

          <div v-if="summary.blueprint_routes?.length" class="table-wrap">
            <table class="routes-table">
              <thead>
                <tr>
                  <th>方法</th>
                  <th>路径</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(r, idx) in summary.blueprint_routes" :key="idx">
                  <td class="mono">{{ (r.methods || []).join(', ') }}</td>
                  <td class="mono">{{ r.path }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else class="muted small">未扫描到 FastAPI APIRouter 路由装饰器，或蓝图文件不存在。</p>
        </template>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'

const route = useRoute()
const router = useRouter()

const tabs = [
  { id: 'guide', label: '指南与清单' },
  { id: 'manifest', label: 'manifest.json' },
  { id: 'files', label: '文件' },
  { id: 'scan', label: '扫描与诊断' },
]

const tab = ref('guide')
const loading = ref(true)
const loadError = ref('')
const modData = ref(null)
const summary = ref(null)
const manifestText = ref('')
const manifestSaveWarnings = ref([])
const message = ref('')
const messageOk = ref(true)
const savingManifest = ref(false)
const selectedPath = ref('')
const fileContent = ref('')
const loadingFile = ref(false)
const savingFile = ref(false)
const fileWarnings = ref([])
const loadingSummary = ref(false)

const modId = computed(() => String(route.params.modId || ''))

function normPath(p) {
  return String(p || '').replace(/\\/g, '/').replace(/^\//, '')
}

const fileSet = computed(() => {
  const files = modData.value?.files
  if (!Array.isArray(files)) return new Set()
  return new Set(files.map((f) => normPath(f)))
})

const sortedFiles = computed(() => {
  const files = modData.value?.files
  if (!Array.isArray(files)) return []
  return [...files].map(normPath).sort((a, b) => a.localeCompare(b))
})

const backendEntryRel = computed(() => {
  const m = modData.value?.manifest
  const entry = typeof m?.backend?.entry === 'string' ? m.backend.entry : 'blueprints'
  const stem = entry.replace(/\.py$/i, '')
  return `backend/${stem}.py`
})

const checklist = computed(() => {
  const fs = fileSet.value
  const rows = [
    {
      key: 'manifest',
      label: '根目录 manifest.json',
      ok: fs.has('manifest.json'),
    },
    {
      key: 'init',
      label: 'backend/__init__.py',
      ok: fs.has('backend/__init__.py'),
      hint: '包初始化文件缺失会导致同 Mod 内相对 import 失败',
    },
    {
      key: 'entry',
      label: `后端入口 ${backendEntryRel.value}`,
      ok: fs.has(backendEntryRel.value),
      hint: '由 manifest.backend.entry 决定',
    },
    {
      key: 'routes',
      label: 'frontend/routes.js',
      ok: fs.has('frontend/routes.js'),
    },
  ]
  return rows
})

const artifactNote = computed(() => {
  const art = modData.value?.manifest?.artifact || modData.value?.manifest?.kind
  if (art === 'employee_pack') {
    return '当前 artifact 为 employee_pack：通常仅声明 workflow_employee，不带路由与前端菜单。'
  }
  if (art === 'bundle') {
    return '当前 artifact 为 bundle：元包组合安装，本体多为 manifest + bundle 字段，一般不含业务代码。'
  }
  return ''
})

function flash(msg, ok = true) {
  message.value = msg
  messageOk.value = ok
  setTimeout(() => {
    message.value = ''
  }, 5000)
}

function goRepo() {
  router.push({ name: 'workbench-repository' })
}

async function refreshSummary() {
  if (!modId.value) return
  loadingSummary.value = true
  try {
    summary.value = await api.getModAuthoringSummary(modId.value)
  } catch (e) {
    flash(e.message || String(e), false)
  } finally {
    loadingSummary.value = false
  }
}

async function reload() {
  loadError.value = ''
  loading.value = true
  manifestSaveWarnings.value = []
  fileWarnings.value = []
  try {
    const [detail, sum] = await Promise.all([
      api.getMod(modId.value),
      api.getModAuthoringSummary(modId.value).catch(() => null),
    ])
    modData.value = detail
    summary.value = sum
    manifestText.value = JSON.stringify(detail.manifest || {}, null, 2)
    if (!selectedPath.value || !fileSet.value.has(normPath(selectedPath.value))) {
      selectedPath.value = ''
      fileContent.value = ''
    }
  } catch (e) {
    modData.value = null
    summary.value = null
    loadError.value = e.message || String(e)
  } finally {
    loading.value = false
  }
}

async function saveManifest() {
  let parsed
  try {
    parsed = JSON.parse(manifestText.value)
  } catch (e) {
    flash('JSON 解析失败: ' + (e.message || String(e)), false)
    return
  }
  savingManifest.value = true
  manifestSaveWarnings.value = []
  try {
    const res = await api.putModManifest(modId.value, parsed)
    manifestSaveWarnings.value = Array.isArray(res.warnings) ? res.warnings : []
    flash('manifest 已保存')
    await reload()
  } catch (e) {
    flash(e.message || String(e), false)
  } finally {
    savingManifest.value = false
  }
}

async function loadSelectedFile() {
  const p = normPath(selectedPath.value)
  if (!p) return
  loadingFile.value = true
  fileWarnings.value = []
  try {
    const res = await api.getModFile(modId.value, p)
    fileContent.value = res.content ?? ''
  } catch (e) {
    flash(e.message || String(e), false)
  } finally {
    loadingFile.value = false
  }
}

function onPathSelect() {
  fileContent.value = ''
  fileWarnings.value = []
}

async function saveFile() {
  const p = normPath(selectedPath.value)
  if (!p) return
  savingFile.value = true
  fileWarnings.value = []
  try {
    const res = await api.putModFile(modId.value, p, fileContent.value)
    fileWarnings.value = Array.isArray(res.manifest_warnings) ? res.manifest_warnings : []
    flash('文件已保存')
    await reload()
  } catch (e) {
    flash(e.message || String(e), false)
  } finally {
    savingFile.value = false
  }
}

watch(
  modId,
  (id) => {
    if (!id) {
      loadError.value = '缺少 modId'
      loading.value = false
      modData.value = null
      return
    }
    reload()
  },
  { immediate: true },
)
</script>

<style scoped>
.authoring-page {
  max-width: 1100px;
  margin: 0 auto;
  padding: 2rem 1rem;
}

.loading {
  text-align: center;
  padding: 3rem;
  color: rgba(255, 255, 255, 0.35);
}

.page-header {
  margin-bottom: 1.25rem;
}

.header-top {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
}

.page-title {
  font-size: 1.5rem;
  margin: 0 0 0.25rem;
  color: #fff;
}

.page-sub {
  margin: 0;
  font-size: 0.875rem;
  color: rgba(255, 255, 255, 0.45);
}

.mono {
  font-family: ui-monospace, monospace;
  font-size: 0.85em;
}

.muted {
  color: rgba(255, 255, 255, 0.4);
}

.small {
  font-size: 0.8125rem;
}

.flash {
  padding: 10px 16px;
  border-radius: 8px;
  margin-bottom: 16px;
  font-size: 14px;
}

.flash-ok {
  background: rgba(74, 222, 128, 0.1);
  color: #4ade80;
}

.flash-err {
  background: rgba(255, 80, 80, 0.1);
  color: #ff6b6b;
}

.tabs {
  display: flex;
  gap: 0.25rem;
  flex-wrap: wrap;
  margin-bottom: 1rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  padding-bottom: 0.5rem;
}

.tab {
  padding: 0.45rem 0.85rem;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: rgba(255, 255, 255, 0.45);
  font-size: 0.875rem;
  cursor: pointer;
}

.tab:hover {
  color: rgba(255, 255, 255, 0.75);
  background: rgba(255, 255, 255, 0.05);
}

.tab.active {
  color: #fff;
  background: rgba(255, 255, 255, 0.08);
}

.panel {
  background: #111;
  border: 0.5px solid rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  padding: 1.25rem;
}

.panel-err {
  color: #ff6b6b;
}

.panel-title {
  font-size: 1.05rem;
  margin: 0 0 0.5rem;
  color: #fff;
}

.sub-title {
  font-size: 0.95rem;
  margin: 1.25rem 0 0.5rem;
  color: rgba(255, 255, 255, 0.85);
}

.panel-actions {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
  margin-bottom: 0.75rem;
}

.guide-list {
  margin: 0.75rem 0 0;
  padding-left: 1.2rem;
  color: rgba(255, 255, 255, 0.65);
  line-height: 1.6;
  font-size: 0.875rem;
}

.guide-list li {
  margin-bottom: 0.35rem;
}

.checklist {
  list-style: none;
  padding: 0;
  margin: 0.5rem 0 0;
}

.checklist li {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.35rem;
  padding: 0.35rem 0;
  font-size: 0.875rem;
  color: rgba(255, 255, 255, 0.55);
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.checklist li.ok {
  color: rgba(74, 222, 128, 0.85);
}

.checklist li.warn {
  color: rgba(251, 191, 36, 0.9);
}

.mark {
  width: 1.25rem;
  flex-shrink: 0;
}

.hint {
  width: 100%;
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.35);
}

.artifact-note {
  margin-top: 1rem;
  padding: 0.75rem;
  border-radius: 8px;
  background: rgba(96, 165, 250, 0.08);
  color: rgba(147, 197, 253, 0.95);
  font-size: 0.8125rem;
  line-height: 1.5;
}

.warn-block {
  font-size: 0.8125rem;
  color: #fbbf24;
  margin: 0 0 0.75rem;
}

.ok-line {
  font-size: 0.875rem;
  color: #4ade80;
  margin: 0 0 0.75rem;
}

.code-area {
  width: 100%;
  min-height: 420px;
  box-sizing: border-box;
  padding: 0.75rem;
  border: 0.5px solid rgba(255, 255, 255, 0.12);
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.35);
  color: rgba(255, 255, 255, 0.88);
  font-family: ui-monospace, monospace;
  font-size: 0.8rem;
  line-height: 1.45;
  resize: vertical;
  outline: none;
}

.code-area:focus {
  border-color: rgba(255, 255, 255, 0.25);
}

.file-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}

.label-inline {
  font-size: 0.8rem;
  color: rgba(255, 255, 255, 0.45);
}

.select {
  flex: 1;
  min-width: 200px;
  max-width: 100%;
  padding: 0.45rem 0.6rem;
  border-radius: 6px;
  border: 0.5px solid rgba(255, 255, 255, 0.15);
  background: rgba(255, 255, 255, 0.04);
  color: #fff;
  font-size: 0.85rem;
}

.table-wrap {
  overflow-x: auto;
  margin-top: 0.75rem;
}

.routes-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8125rem;
}

.routes-table th,
.routes-table td {
  text-align: left;
  padding: 0.4rem 0.5rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.routes-table th {
  color: rgba(255, 255, 255, 0.45);
  font-weight: 500;
}

.badge {
  display: inline-flex;
  align-items: center;
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  font-size: 0.6875rem;
  font-weight: 500;
}

.badge-ok {
  background: rgba(74, 222, 128, 0.12);
  color: #4ade80;
}

.badge-warn {
  background: rgba(251, 191, 36, 0.12);
  color: #fbbf24;
}

.btn {
  padding: 0.45rem 0.9rem;
  border: 0.5px solid rgba(255, 255, 255, 0.15);
  border-radius: 6px;
  background: transparent;
  color: rgba(255, 255, 255, 0.75);
  font-size: 0.8125rem;
  cursor: pointer;
}

.btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.06);
  color: #fff;
}

.btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.btn-primary {
  background: #fff;
  color: #0a0a0a;
  border-color: transparent;
}

.btn-ghost {
  border-color: transparent;
  padding-left: 0;
}
</style>
