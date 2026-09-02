<template>
  <div class="kitten-shell">
    <header class="kitten-header">
      <button class="kitten-back" type="button" @click="emit('back')">返回</button>
      <div class="kitten-brand">
        <span class="kitten-brand-icon" aria-hidden="true">
          <KittenLauncherIcon size="sm" />
        </span>
        <div class="kitten-brand-text">
          <div class="kitten-title">智慧分析</div>
          <div class="kitten-subtitle">可视化 AI 员工 · 对话洞察 · 图表导出</div>
        </div>
      </div>
      <button class="kitten-header-action" type="button" @click="resetSession">清空</button>
    </header>

    <div v-if="datasetSummary" class="kitten-dataset-bar">
      <span class="kitten-dataset-name">{{ datasetSummary.name }}</span>
      <span class="kitten-dataset-meta">{{ datasetSummary.rows }} 行 · {{ datasetSummary.columns }} 列</span>
    </div>

    <div class="chat-container">
      <div ref="chatMessagesRef" class="chat-messages">
        <div v-for="(msg, idx) in messages" :key="idx" :class="['message', msg.role]">
          <div v-html="sanitizeChatBubbleHtml(msg.content)"></div>
          <button
            v-if="extractKittenDocumentPickupUrl(msg.content)"
            class="download-btn"
            @click="openDownloadLink(extractKittenDocumentPickupUrl(msg.content)!)"
          >
            下载
          </button>
          <div class="time">{{ msg.time }}</div>
        </div>
        <div v-if="isDatasetParsing || (isChatLoading && !isKittenStreaming)" class="message ai">
          <div><span class="status-dot online"></span> {{ loadingStatusText }}</div>
        </div>
      </div>

      <KittenVizEmployeeStrip
        v-if="datasetSummary"
        :employees="vizEmployees"
        :selected-pkg-id="selectedVizEmployee.pkgId"
        :installed-count="vizInstalledCount"
        :loading="vizLoading"
        @select="onVizEmployeeSelect"
      />

      <KittenChartPanel
        v-if="datasetSummary && datasetRows.length"
        :rows="datasetRows"
        :field-profiles="fieldProfiles"
        :config="chartConfig"
        :recommendations="recommendedCharts"
        :palette="selectedVizEmployee.palette"
        :dashboard-mode="!!selectedVizEmployee.dashboard"
        :employee-name="selectedVizEmployee.name"
        @update-config="setChartConfig"
        @apply-recommendation="applyChartRecommendation"
      />

      <aside class="side-panel" :class="{ 'is-collapsed': panelCollapsed }">
        <button class="panel-collapse-toggle" type="button" @click="panelCollapsed = !panelCollapsed">
          {{ panelCollapsed ? '设置' : '收起' }}
        </button>
        <div v-show="!panelCollapsed" class="panel-inner">
          <div class="panel-block">
            <div class="panel-label">数据</div>
            <template v-if="datasetSummary">
              <p class="panel-meta">{{ datasetSummary.rows }} 行 / {{ datasetSummary.columns }} 列</p>
              <div v-if="datasetFieldPreview.length" class="asset-chips">
                <span v-for="f in datasetFieldPreview" :key="f" class="asset-chip">{{ f }}</span>
                <span v-if="datasetSummary.fieldNames.length > 8" class="asset-chip muted">…</span>
              </div>
            </template>
            <p v-else class="panel-hint">上传表格后可预览字段</p>
            <label class="panel-check" title="可选：附带原材料 / 产品 / 出货的只读聚合摘要（非全库、非实时报表）">
              <input type="checkbox" v-model="kittenIncludeBusinessDb" @change="onKittenBusinessDbToggle" />
              <span>业务库摘要</span>
            </label>
            <p v-if="kittenDbStatsHint" class="panel-hint small">{{ kittenDbStatsHint }}</p>
            <label class="panel-check" title="开启后由服务端检索网页摘要（需配置 WEB_SEARCH_PROVIDER）">
              <input type="checkbox" v-model="kittenIncludeWebSearch" />
              <span>联网</span>
            </label>
          </div>

          <div v-if="lastWebSearchHits.length" class="panel-block">
            <div class="panel-label">引用</div>
            <ul class="citation-list">
              <li v-for="(h, i) in lastWebSearchHits.slice(0, 5)" :key="i">
                <a :href="h.url" target="_blank" rel="noopener noreferrer">{{ h.title || h.url }}</a>
              </li>
            </ul>
          </div>

          <div class="panel-block">
            <div class="panel-label">导出</div>
            <div class="export-row">
              <button class="btn btn-sm btn-primary" type="button" :disabled="!currentResult" @click="exportResult">Excel</button>
              <button class="btn btn-sm btn-secondary" type="button" :disabled="!currentResult" @click="exportDocx">Word</button>
              <button class="btn btn-sm btn-ghost" type="button" :disabled="!currentResult" @click="clearResult">清除</button>
            </div>
            <div v-if="lastDocumentPickupUrl" class="pickup-download-row">
              <button class="btn btn-sm btn-primary" type="button" @click="openDownloadLink(lastDocumentPickupUrl)">
                下载本次生成的文档
              </button>
            </div>
            <div v-if="currentResult" class="result-preview">
              <strong>{{ currentResult.title }}</strong>
              <p>{{ currentResult.summary }}</p>
            </div>
          </div>
        </div>
      </aside>
    </div>

    <div class="kitten-input-tools">
      <select
        v-model="quickPick"
        class="quick-select"
        aria-label="快捷分析"
        :disabled="isChatLoading || isDatasetParsing"
        @change="onQuickPick"
      >
        <option value="">快捷…</option>
        <option v-for="btn in kittenQuickActions" :key="btn.text" :value="btn.text">
          {{ btn.label }}
        </option>
      </select>

      <details ref="moreMenuRef" class="more-menu">
        <summary class="more-summary">更多</summary>
        <div class="more-body">
          <button class="more-action" type="button" :disabled="isChatLoading || isDatasetParsing" @click="runFinancialBriefAndClose">
            财务简报
          </button>
          <button class="more-action" type="button" @click="docGenExpanded = !docGenExpanded">
            {{ docGenExpanded ? '收起生成文档' : '生成 Word / Excel…' }}
          </button>
        </div>
      </details>
    </div>

    <div v-if="docGenExpanded" class="doc-gen-panel">
      <div class="doc-gen-title">按描述生成示范稿（正式用印前请审核）</div>
      <div class="doc-gen-row">
        <input
          v-model="docGenPrompt"
          class="doc-gen-input"
          type="text"
          placeholder="例：技术服务合同草案，Word"
          @keydown.enter.prevent="runDocGen"
        />
        <select v-model="docGenFormat" class="doc-gen-select">
          <option value="docx">Word (.docx)</option>
          <option value="xlsx">Excel (.xlsx)</option>
        </select>
        <button class="toolbar-chip toolbar-chip-primary" type="button" :disabled="isDocGenLoading || isChatLoading" @click="runDocGen">
          {{ isDocGenLoading ? '生成中…' : '生成并下载' }}
        </button>
      </div>
    </div>

    <div class="input-area">
      <input ref="fileInput" type="file" accept=".xlsx,.xls,.csv,.txt,.json" class="kitten-file-input" @change="handleFileSelect" />
      <div class="input-wrapper">
        <button type="button" class="attach-btn" title="上传 Excel / CSV / JSON" :disabled="isDatasetParsing" @click="triggerFileUpload">
          <span class="attach-icon" aria-hidden="true">&#128206;</span>
          <span class="sr-only">上传文件</span>
        </button>
        <button
          type="button"
          :class="voiceButtonClass"
          :disabled="voiceButtonDisabled"
          :title="voiceState === 'recording' ? '松开停止' : '按住说话，松开后自动识别'"
          @mousedown.prevent="startVoiceInput"
          @mouseup.prevent="stopVoiceInput"
          @mouseleave="stopVoiceInput"
          @touchstart.prevent="startVoiceInput"
          @touchend.prevent="stopVoiceInput"
          @touchcancel.prevent="stopVoiceInput"
        >
          <span class="attach-icon" aria-hidden="true">
            <i v-if="voiceState === 'recording'" class="fa fa-stop-circle" style="color: #ef4444"></i>
            <i v-else-if="voiceState === 'transcribing'" class="fa fa-spinner fa-pulse" style="color: #3b82f6"></i>
            <i v-else-if="voiceState === 'error'" class="fa fa-exclamation-circle" style="color: #ef4444"></i>
            <i v-else class="fa fa-microphone"></i>
          </span>
          <span class="sr-only">语音输入</span>
        </button>
        <textarea v-model="inputText" rows="3" placeholder="输入问题，Enter 发送；Shift+Enter 换行" @keydown="handleInputKeydown" />
        <button class="btn btn-primary send-btn" type="button" :disabled="isChatLoading || isDatasetParsing" @click="sendMessage">
          发送
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { buildFullApiUrl } from '@/api/core'
import { sanitizeChatBubbleHtml } from '@/utils/sanitizeHtml'
import { downloadBlob, getFilenameFromDisposition } from '@/utils'
import { appAlert } from '@/utils/appDialog'
import KittenChartPanel from '@/components/kitten/KittenChartPanel.vue'
import KittenLauncherIcon from '@/components/kitten/KittenLauncherIcon.vue'
import KittenVizEmployeeStrip from '@/components/kitten/KittenVizEmployeeStrip.vue'
import { useKittenVizEmployees } from '@/composables/useKittenVizEmployees'
import type { KittenChartType } from '@/composables/useKittenAnalyzer'
import { asRecord, asArray, asString } from '@/utils/typeGuards'
import { useKittenAnalyzer, kittenQuickActions, extractKittenDocumentPickupUrl } from '@/composables/useKittenAnalyzer'

const emit = defineEmits<{ back: [] }>()

const panelCollapsed = ref(true)
const docGenPrompt = ref('')
const docGenFormat = ref<'docx' | 'xlsx'>('docx')
const docGenExpanded = ref(false)
const quickPick = ref('')
const moreMenuRef = ref<HTMLDetailsElement | null>(null)

const {
  messages,
  inputText,
  isChatLoading,
  isKittenStreaming,
  isDatasetParsing,
  currentResult,
  fileInput,
  chatMessagesRef,
  datasetSummary,
  datasetRows,
  fieldProfiles,
  chartConfig,
  recommendedCharts,
  kittenIncludeBusinessDb,
  kittenIncludeWebSearch,
  kittenDbStatsHint,
  lastWebSearchHits,
  datasetFieldPreview,
  lastDocumentPickupUrl,
  loadingStatusText,
  resetSession,
  onKittenBusinessDbToggle,
  triggerFileUpload,
  handleFileSelect,
  setChartConfig,
  applyChartRecommendation,
  sendMessage,
  sendQuickAction,
  exportResult,
  exportDocx,
  isDocGenLoading,
  generateAiOfficeDocument,
  runFinancialBrief,
  clearResult,
  handleInputKeydown,
} = useKittenAnalyzer()

const {
  employees: vizEmployees,
  selected: selectedVizEmployee,
  installedCount: vizInstalledCount,
  loading: vizLoading,
  selectEmployee: selectVizEmployee,
} = useKittenVizEmployees()

function onVizEmployeeSelect(pkgId: string) {
  selectVizEmployee(pkgId)
  applyVizEmployeeChartType()
}

function applyVizEmployeeChartType() {
  const emp = selectedVizEmployee.value
  if (!emp?.installed || !datasetSummary.value) return
  const nextType: KittenChartType = emp.dashboard ? 'bar' : emp.chartType
  setChartConfig({ type: nextType })
}

watch(
  () => datasetSummary.value?.name,
  () => applyVizEmployeeChartType(),
)

const runDocGen = () => {
  void generateAiOfficeDocument(docGenPrompt.value, docGenFormat.value)
}

const onQuickPick = () => {
  const v = quickPick.value
  quickPick.value = ''
  if (!v) return
  const btn = kittenQuickActions.find((b) => b.text === v)
  if (btn) sendQuickAction(btn)
}

const runFinancialBriefAndClose = () => {
  moreMenuRef.value?.removeAttribute('open')
  void runFinancialBrief()
}

type VoiceState = 'idle' | 'recording' | 'transcribing' | 'error'
type SpeechRecognitionLike = {
  lang: string
  continuous: boolean
  interimResults: boolean
  maxAlternatives: number
  onstart: (() => void) | null
  onresult: ((event: unknown) => void) | null
  onerror: ((event: unknown) => void) | null
  onend: (() => void) | null
  start: () => void
  stop: () => void
  abort: () => void
}

type SpeechWindow = Window & {
  SpeechRecognition?: new () => SpeechRecognitionLike
  webkitSpeechRecognition?: new () => SpeechRecognitionLike
}

const voiceState = ref<VoiceState>('idle')
const voiceErrorText = ref('')
let voiceRecognition: SpeechRecognitionLike | null = null

const voiceButtonDisabled = computed(() => voiceState.value === 'transcribing' || isChatLoading.value)
const voiceButtonClass = computed(() => ({
  'attach-btn': true,
  'voice-recording': voiceState.value === 'recording',
  'voice-transcribing': voiceState.value === 'transcribing',
  'voice-error': voiceState.value === 'error',
}))

const startVoiceInput = () => {
  if (voiceState.value === 'recording' || voiceState.value === 'transcribing') return
  const win = window as SpeechWindow
  const SpeechRecognitionCtor = win.SpeechRecognition || win.webkitSpeechRecognition
  if (!SpeechRecognitionCtor) {
    voiceState.value = 'error'
    voiceErrorText.value = '当前浏览器不支持语音识别'
    return
  }
  if (voiceRecognition) {
    voiceRecognition.abort()
  }
  voiceRecognition = new SpeechRecognitionCtor()
  voiceRecognition.lang = 'zh-CN'
  voiceRecognition.continuous = false
  voiceRecognition.interimResults = false
  voiceRecognition.maxAlternatives = 1

  voiceRecognition.onstart = () => {
    voiceState.value = 'recording'
    voiceErrorText.value = ''
  }
  voiceRecognition.onresult = (event: unknown) => {
    const row = asRecord(event)
    const results = asArray(asArray(row.results)[0])
    const text = asString(asRecord(results[0]).transcript)
    inputText.value = (inputText.value || '') + text
  }
  voiceRecognition.onerror = (event: unknown) => {
    const err = asString(asRecord(event).error)
    if (err === 'no-speech') {
      voiceState.value = 'idle'
      return
    }
    voiceState.value = 'error'
    voiceErrorText.value = err || '语音识别失败'
  }
  voiceRecognition.onend = () => {
    if (voiceState.value === 'recording') voiceState.value = 'idle'
  }
  voiceRecognition.start()
}

const stopVoiceInput = () => {
  if (voiceRecognition) {
    voiceRecognition.stop()
    voiceRecognition = null
  }
  if (voiceState.value === 'recording') voiceState.value = 'idle'
}

const openDownloadLink = async (link: string) => {
  const fullUrl = /^https?:\/\//i.test(link.trim()) ? link.trim() : buildFullApiUrl(link.trim())
  try {
    const resp = await fetch(fullUrl, { credentials: 'include' })
    const ct = (resp.headers.get('content-type') || '').toLowerCase()
    if (!resp.ok) {
      if (ct.includes('application/json')) {
        const j = (await resp.json().catch(() => null)) as { message?: string } | null
        throw new Error(j?.message || `下载失败（${resp.status}）`)
      }
      throw new Error(`下载失败（${resp.status}）`)
    }
    if (ct.includes('application/json')) {
      const j = (await resp.json().catch(() => null)) as { message?: string } | null
      throw new Error(j?.message || '下载失败：服务器返回了 JSON 而非文件')
    }
    const blob = await resp.blob()
    const ext = blob.type.includes('spreadsheet') ? 'xlsx' : blob.type.includes('word') || blob.type.includes('msword') ? 'docx' : 'bin'
    const filename = getFilenameFromDisposition(resp.headers.get('content-disposition'), `文档.${ext}`)
    downloadBlob(blob, filename)
  } catch (err) {
    console.error('Download failed:', err)
    const msg = err instanceof Error ? err.message : String(err)
    await appAlert(`无法下载：${msg}`)
    try {
      window.open(fullUrl, '_blank', 'noopener,noreferrer')
    } catch {
      /* ignore */
    }
  }
}
</script>

<style scoped src="./KittenAnalyzerView.css"></style>
