<template>
  <div class="mat">
    <header class="mat-head">
      <div>
        <h1 class="mat-title">我的素材</h1>
        <p class="mat-sub">
          上传音频、图片、文档等制作资源，保存在服务器供后续员工包与 TTS 配置引用。下载需登录态（Bearer / Cookie）。
        </p>
      </div>
      <label class="mat-upload">
        <input type="file" class="mat-upload-input" :disabled="uploading" @change="onPickUpload" />
        <span>{{ uploading ? '上传中…' : '+ 上传素材' }}</span>
      </label>
    </header>

    <p v-if="listError" class="mat-flash mat-flash--err">{{ listError }}</p>
    <p v-if="uploadMsg" class="mat-flash mat-flash--ok">{{ uploadMsg }}</p>

    <section class="mat-tts" aria-labelledby="mat-tts-title">
      <h2 id="mat-tts-title" class="mat-section-title">云端 TTS 试听</h2>
      <p class="mat-hint">
        试听使用服务端 edge-tts。员工包内朗读请在「统一工作台 → 专注员工制作」中配置 <code>actions.voice_output</code> 等字段。
      </p>
      <div class="mat-tts-row">
        <select v-model="ttsVoice" class="mat-select">
          <option v-for="v in edgeVoices" :key="v.id" :value="v.id">{{ v.label }}</option>
        </select>
        <input v-model="ttsText" class="mat-input" type="text" placeholder="输入试听文字…" />
        <label class="mat-rate">
          语速 {{ ttsRate.toFixed(1) }}×
          <input v-model.number="ttsRate" type="range" min="0.6" max="1.6" step="0.1" />
        </label>
        <button type="button" class="mat-btn" :disabled="ttsBusy" @click="playTts">{{ ttsBusy ? '…' : '▶ 试听' }}</button>
      </div>
    </section>

    <section class="mat-list-wrap" aria-labelledby="mat-list-title">
      <h2 id="mat-list-title" class="mat-section-title">已保存的素材</h2>
      <p v-if="loading" class="mat-empty">加载中…</p>
      <p v-else-if="!items.length" class="mat-empty">暂无素材，点击右上角上传。</p>
      <ul v-else class="mat-grid">
        <li v-for="it in items" :key="it.id" class="mat-card">
          <header class="mat-card-head">
            <span class="mat-badge">{{ kindLabel(it.kind) }}</span>
            <h3 class="mat-name">{{ it.filename }}</h3>
          </header>
          <p class="mat-meta">{{ formatSize(it.size_bytes) }} · {{ it.mime_type }}</p>
          <p class="mat-meta">{{ formatTime(it.created_at) }}</p>
          <p v-if="employeeSummary(it)" class="mat-meta mat-meta--emp">关联员工：{{ employeeSummary(it) }}</p>
          <div class="mat-card-actions">
            <button type="button" class="mat-btn mat-btn--ghost" @click="copyDownloadPath(it.id)">复制下载路径</button>
            <button type="button" class="mat-btn mat-btn--ghost" @click="downloadBlob(it)">下载</button>
            <button type="button" class="mat-btn mat-btn--ghost" @click="openEdit(it)">备注 / 关联</button>
            <button type="button" class="mat-btn mat-btn--danger" @click="confirmDelete(it)">删除</button>
          </div>
        </li>
      </ul>
    </section>

    <div v-if="editOpen" class="mat-overlay" role="presentation" @click.self="editOpen = false">
      <div class="mat-dialog" role="dialog" aria-modal="true" aria-label="编辑素材元数据" @click.stop>
        <h3>备注与关联员工</h3>
        <p class="mat-hint">关联员工 ID 用英文逗号分隔，供 manifest / 制作向导引用（不做外键校验）。</p>
        <label class="mat-field">
          <span>备注</span>
          <input v-model="editNote" class="mat-input" type="text" />
        </label>
        <label class="mat-field">
          <span>员工 ID 列表</span>
          <input v-model="editEmployees" class="mat-input" type="text" placeholder="emp_a, emp_b" />
        </label>
        <div class="mat-dialog-actions">
          <button type="button" class="mat-btn mat-btn--ghost" @click="editOpen = false">取消</button>
          <button type="button" class="mat-btn" :disabled="editSaving" @click="saveEdit">{{ editSaving ? '保存中…' : '保存' }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
import { useStreamingTts } from '../composables/useStreamingTts'

interface StudioItem {
  id: number
  kind: string
  filename: string
  mime_type: string
  size_bytes: number
  metadata?: Record<string, unknown>
  created_at?: string
}

const loading = ref(true)
const listError = ref('')
const items = ref<StudioItem[]>([])
const uploading = ref(false)
const uploadMsg = ref('')

const ttsText = ref('你好，这是素材页的 TTS 试听。')
const ttsVoice = ref('zh-CN-XiaoxiaoNeural')
const ttsRate = ref(1)
const ttsBusy = ref(false)

const streamingTts = useStreamingTts(() => ({
  engine: 'edge-online',
  edgeVoice: ttsVoice.value,
  browserVoiceName: '',
  rate: ttsRate.value,
}))

const edgeVoices = [
  { id: 'zh-CN-XiaoxiaoNeural', label: '晓晓（女声，通用）' },
  { id: 'zh-CN-YunxiNeural', label: '云希（男声）' },
  { id: 'zh-CN-XiaoyiNeural', label: '晓伊（女声）' },
  { id: 'zh-CN-YunjianNeural', label: '云健（男声，资讯风）' },
  { id: 'zh-CN-XiaochenNeural', label: '晓辰（女声）' },
  { id: 'zh-CN-XiaomengNeural', label: '晓梦（女声）' },
]

const editOpen = ref(false)
const editSaving = ref(false)
const editId = ref<number | null>(null)
const editNote = ref('')
const editEmployees = ref('')

function kindLabel(k: string) {
  return (
    {
      audio: '音频',
      image: '图片',
      document: '文档',
      other: '其他',
    }[k] || k
  )
}

function formatSize(n: number) {
  if (!n) return '0 B'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

function formatTime(t: string | undefined) {
  if (!t) return ''
  try {
    return new Date(t).toLocaleString('zh-CN')
  } catch {
    return t
  }
}

function employeeSummary(it: StudioItem) {
  const raw = it.metadata?.linked_employee_ids
  if (Array.isArray(raw) && raw.length) return raw.map(String).join(', ')
  return ''
}

async function loadList() {
  loading.value = true
  listError.value = ''
  try {
    const res: any = await api.listStudioAssets()
    items.value = Array.isArray(res?.items) ? res.items : []
  } catch (e: any) {
    listError.value = e?.message || String(e)
    items.value = []
  } finally {
    loading.value = false
  }
}

async function onPickUpload(ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  uploading.value = true
  uploadMsg.value = ''
  try {
    await api.uploadStudioAsset(file)
    uploadMsg.value = `已上传：${file.name}`
    await loadList()
  } catch (e: any) {
    listError.value = e?.message || String(e)
  } finally {
    uploading.value = false
  }
}

function copyDownloadPath(id: number) {
  const path = `/api/workbench/studio-assets/${id}/file`
  void navigator.clipboard.writeText(path).then(
    () => {
      uploadMsg.value = '已复制路径（需登录后 GET）：' + path
    },
    () => {
      listError.value = '复制失败，请手动复制：' + path
    },
  )
}

async function downloadBlob(it: StudioItem) {
  try {
    const blob = await api.downloadStudioAssetBlob(it.id)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = it.filename || 'download'
    a.click()
    URL.revokeObjectURL(url)
  } catch (e: any) {
    listError.value = e?.message || String(e)
  }
}

function openEdit(it: StudioItem) {
  editId.value = it.id
  const m = it.metadata || {}
  editNote.value = typeof m.note === 'string' ? m.note : ''
  const ids = m.linked_employee_ids
  editEmployees.value = Array.isArray(ids) ? ids.map(String).join(', ') : ''
  editOpen.value = true
}

async function saveEdit() {
  if (editId.value == null) return
  const ids = editEmployees.value
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
  editSaving.value = true
  try {
    const meta: Record<string, unknown> = {
      note: editNote.value.trim(),
      linked_employee_ids: ids,
    }
    await api.patchStudioAssetMetadata(editId.value, meta)
    editOpen.value = false
    await loadList()
  } catch (e: any) {
    listError.value = e?.message || String(e)
  } finally {
    editSaving.value = false
  }
}

function confirmDelete(it: StudioItem) {
  if (!confirm(`确定删除「${it.filename}」？`)) return
  void (async () => {
    try {
      await api.deleteStudioAsset(it.id)
      await loadList()
    } catch (e: any) {
      listError.value = e?.message || String(e)
    }
  })()
}

async function playTts() {
  const text = ttsText.value.trim() || '你好'
  ttsBusy.value = true
  try {
    await streamingTts.speak(text)
  } catch (e: any) {
    listError.value = e?.message || String(e)
  } finally {
    ttsBusy.value = false
  }
}

onMounted(loadList)
</script>

<style scoped>
.mat {
  max-width: 1100px;
  margin: 0 auto;
  padding: 24px 24px 80px;
  color: #d8dde6;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
}
.mat-head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 20px;
}
.mat-title {
  margin: 0;
  font-size: 22px;
}
.mat-sub {
  margin: 8px 0 0;
  color: #9aa3b2;
  font-size: 14px;
  line-height: 1.6;
  max-width: 720px;
}
.mat-upload {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: #f5d870;
  color: #0b0e14;
  font-weight: 600;
  border: none;
  padding: 10px 18px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
}
.mat-upload-input {
  display: none;
}
.mat-flash {
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 13px;
}
.mat-flash--err {
  background: #3a1515;
  color: #f5a8a8;
  border: 1px solid #6b2a2a;
}
.mat-flash--ok {
  background: #143b1f;
  color: #9be7b7;
  border: 1px solid #2a6b3f;
}
.mat-section-title {
  margin: 28px 0 10px;
  font-size: 16px;
  color: #e8ecf3;
}
.mat-hint {
  margin: 0 0 12px;
  color: #7e8796;
  font-size: 13px;
  line-height: 1.55;
}
.mat-hint code {
  font-size: 12px;
  color: #c7e5ff;
}
.mat-tts {
  background: #0f131a;
  border: 1px solid #2c333f;
  border-radius: 10px;
  padding: 16px 18px;
}
.mat-tts-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}
.mat-select,
.mat-input {
  background: #0b0e14;
  border: 1px solid #2c333f;
  color: #e8ecf3;
  border-radius: 6px;
  padding: 8px 10px;
  font-size: 14px;
}
.mat-input {
  flex: 1 1 200px;
  min-width: 0;
}
.mat-rate {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: #9aa3b2;
  min-width: 140px;
}
.mat-btn {
  background: #2ba8ff;
  color: #061018;
  border: none;
  padding: 8px 16px;
  border-radius: 6px;
  font-weight: 600;
  cursor: pointer;
  font-size: 13px;
}
.mat-btn:disabled {
  opacity: 0.55;
  cursor: default;
}
.mat-btn--ghost {
  background: transparent;
  color: #c7e5ff;
  border: 1px solid #2c5a82;
}
.mat-btn--danger {
  background: transparent;
  color: #f57878;
  border-color: #6b2a2a;
}
.mat-empty {
  color: #6b7280;
  padding: 32px;
  text-align: center;
  background: #0f131a;
  border: 1px dashed #2c333f;
  border-radius: 8px;
}
.mat-grid {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 14px;
}
.mat-card {
  background: #0f131a;
  border: 1px solid #2c333f;
  border-radius: 8px;
  padding: 14px 16px;
}
.mat-card-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.mat-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  background: #2c333f;
  color: #c2c8d4;
  flex-shrink: 0;
}
.mat-name {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: #e8ecf3;
  word-break: break-all;
}
.mat-meta {
  margin: 4px 0 0;
  font-size: 12px;
  color: #6b7280;
}
.mat-meta--emp {
  color: #9aa3b2;
}
.mat-card-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}
.mat-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 80;
  padding: 16px;
}
.mat-dialog {
  background: #111620;
  border: 1px solid #2c333f;
  border-radius: 10px;
  padding: 20px 22px;
  max-width: 440px;
  width: 100%;
  color: #e8ecf3;
}
.mat-dialog h3 {
  margin: 0 0 8px;
  font-size: 17px;
}
.mat-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 12px;
  font-size: 13px;
  color: #9aa3b2;
}
.mat-dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 18px;
}
html[data-workbench-theme='light'] .mat {
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .mat-sub {
  color: #86868b;
}
html[data-workbench-theme='light'] .mat-upload {
  background: rgba(217,119,6,.1);
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .mat-flash--err {
  background: rgba(215,0,21,.08);
  color: #d70015;
  border: 1px solid rgba(215,0,21,.2);
}
html[data-workbench-theme='light'] .mat-flash--ok {
  background: rgba(52,168,83,.08);
  color: #34a853;
  border: 1px solid rgba(52,168,83,.2);
}
html[data-workbench-theme='light'] .mat-section-title {
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .mat-hint {
  color: #86868b;
}
html[data-workbench-theme='light'] .mat-hint code {
  color: #0071e3;
}
html[data-workbench-theme='light'] .mat-tts {
  background: #ffffff;
  border: 1px solid rgba(0,0,0,.08);
}
html[data-workbench-theme='light'] .mat-select,
html[data-workbench-theme='light'] .mat-input {
  background: #ffffff;
  border: 1px solid rgba(0,0,0,.08);
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .mat-rate {
  color: #86868b;
}
html[data-workbench-theme='light'] .mat-btn {
  background: #0071e3;
  color: #ffffff;
}
html[data-workbench-theme='light'] .mat-btn--ghost {
  color: #0071e3;
  border: 1px solid rgba(0,113,227,.2);
}
html[data-workbench-theme='light'] .mat-btn--danger {
  color: #d70015;
  border-color: rgba(215,0,21,.2);
}
html[data-workbench-theme='light'] .mat-empty {
  color: #86868b;
  background: #ffffff;
  border: 1px dashed rgba(0,0,0,.08);
}
html[data-workbench-theme='light'] .mat-card {
  background: #ffffff;
  border: 1px solid rgba(0,0,0,.08);
}
html[data-workbench-theme='light'] .mat-badge {
  background: rgba(0,0,0,.06);
  color: #86868b;
}
html[data-workbench-theme='light'] .mat-name {
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .mat-meta {
  color: #86868b;
}
html[data-workbench-theme='light'] .mat-meta--emp {
  color: #86868b;
}
html[data-workbench-theme='light'] .mat-dialog {
  background: #ffffff;
  border: 1px solid rgba(0,0,0,.08);
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .mat-field {
  color: #86868b;
}
</style>
