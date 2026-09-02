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
    const res = (await api.listStudioAssets()) as { items?: StudioItem[] }
    items.value = Array.isArray(res?.items) ? res.items : []
  } catch (e: unknown) {
    listError.value = e instanceof Error ? e.message : String(e)
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
  } catch (e: unknown) {
    listError.value = e instanceof Error ? e.message : String(e)
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
  } catch (e: unknown) {
    listError.value = e instanceof Error ? e.message : String(e)
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
  } catch (e: unknown) {
    listError.value = e instanceof Error ? e.message : String(e)
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
    } catch (e: unknown) {
      listError.value = e instanceof Error ? e.message : String(e)
    }
  })()
}

async function playTts() {
  const text = ttsText.value.trim() || '你好'
  ttsBusy.value = true
  try {
    await streamingTts.speak(text)
  } catch (e: unknown) {
    listError.value = e instanceof Error ? e.message : String(e)
  } finally {
    ttsBusy.value = false
  }
}

onMounted(loadList)
</script>

<!-- 拆分后本文件为组装入口（façade）：样式外移至 ./MyMaterialsView.css，模板与逻辑保持原样。 -->
<style scoped src="./MyMaterialsView.css"></style>
