<template>
  <div class="employee-exam-page">
    <div class="exam-grid">
      <section class="exam-panel exam-panel--control">
        <header class="exam-panel-head">
          <h1 class="exam-page-title">考试试跑</h1>
          <p class="exam-page-sub">Word 全量读取 → 自动生成 HTML 量化报告</p>
        </header>

        <div class="exam-config">
          <label class="exam-label" for="exam-employee-select">员工包</label>
          <select
            id="exam-employee-select"
            v-model="selectedEmployeeId"
            class="exam-select"
            :disabled="loadingEmployees || pipelineBusy"
          >
            <option v-if="!employeeOptions.length" value="">暂无可用员工包</option>
            <option v-for="opt in employeeOptions" :key="opt.id" :value="opt.id">
              {{ opt.name }}
            </option>
          </select>
          <button
            type="button"
            class="btn btn-ghost btn-sm"
            :disabled="loadingEmployees"
            @click="loadEmployees"
          >
            刷新
          </button>
        </div>

        <div
          class="exam-dropzone"
          :class="{ 'exam-dropzone--active': dragOver, 'exam-dropzone--has-file': !!selectedFile }"
          @dragover.prevent="dragOver = true"
          @dragleave.prevent="dragOver = false"
          @drop.prevent="onDrop"
        >
          <input
            ref="fileInputRef"
            type="file"
            class="exam-file-input"
            :accept="acceptAttr"
            @change="onFileInput"
          />
          <template v-if="selectedFile">
            <div class="exam-file-chip">
              <span class="exam-file-chip-name" :title="selectedFile.name">{{ selectedFile.name }}</span>
              <span class="exam-file-chip-meta">{{ formatBytes(selectedFile.size) }}</span>
            </div>
            <button type="button" class="btn btn-ghost btn-sm" :disabled="pipelineBusy" @click="clearFile">
              更换
            </button>
          </template>
          <template v-else>
            <p class="exam-drop-title">拖入或选择文件</p>
            <p class="exam-drop-sub">{{ dropZoneSubtext }}</p>
            <button type="button" class="btn btn-connect btn-sm" :disabled="pipelineBusy" @click="fileInputRef?.click()">
              选择文件
            </button>
          </template>
        </div>

        <p v-if="employeesError" class="exam-alert exam-alert--err">{{ employeesError }}</p>
        <p v-if="jsonReportUploadHint" class="exam-alert">{{ jsonReportUploadHint }}</p>
        <p v-if="employeeAutoSwitchNote" class="exam-alert exam-alert--ok">{{ employeeAutoSwitchNote }}</p>
        <p v-if="legacyDocHint" class="exam-alert exam-alert--warn">{{ legacyDocHint }}</p>
        <p v-if="fileHint" class="exam-alert exam-alert--warn">{{ fileHint }}</p>

        <div v-if="pipelineComplete && !pipelineBusy" class="exam-done-chip">流程已完成</div>
        <p v-if="lastRunStatusLine" class="exam-run-status">{{ lastRunStatusLine }}</p>

        <section
          v-else-if="showPipelinePanel"
          class="exam-pipeline"
          aria-live="polite"
          :aria-busy="pipelineBusy"
        >
          <div class="exam-pipeline-bar-wrap">
            <div
              class="exam-pipeline-bar"
              role="progressbar"
              :aria-valuenow="pipelinePercent"
              aria-valuemin="0"
              aria-valuemax="100"
            >
              <div class="exam-pipeline-bar-fill" :style="{ width: `${pipelinePercent}%` }" />
            </div>
            <span class="exam-pipeline-pct">{{ pipelinePercent }}%</span>
          </div>
          <p v-if="pipelineMessage" class="exam-pipeline-message">{{ pipelineMessage }}</p>
          <ol class="exam-pipeline-steps">
            <li
              v-for="step in pipelineStepViews"
              :key="step.id"
              class="exam-pipeline-step"
              :class="`exam-pipeline-step--${step.status}`"
            >
              <span class="exam-pipeline-step-icon" aria-hidden="true">{{ step.icon }}</span>
              <span class="exam-pipeline-step-label">{{ step.label }}</span>
            </li>
          </ol>
        </section>

        <button type="button" class="btn btn-action btn-block" :disabled="!canRun" @click="runExam">
          {{ examPrimaryLabel }}
        </button>

        <p v-if="runError" class="exam-alert exam-alert--err">{{ runError }}</p>
        <p v-if="reportError && !pipelineBusy" class="exam-alert exam-alert--err">{{ reportError }}</p>
      </section>

      <section class="exam-panel exam-panel--output">
        <div v-if="!htmlReportPreviewUrl && !pipelineBusy" class="exam-output-empty">
          <p class="exam-output-empty-title">报告预览区</p>
          <p class="exam-output-empty-sub">完成左侧试跑后，HTML 量化报告将显示在此处</p>
        </div>

        <div v-else-if="pipelineBusy" class="exam-output-empty exam-output-empty--busy">
          <p class="exam-output-empty-title">正在生成报告…</p>
          <p class="exam-output-empty-sub">{{ pipelineMessage || '请稍候' }}</p>
        </div>

        <article v-else ref="reportHeroRef" class="exam-report-card">
          <header class="exam-report-card-head">
            <div>
              <h2 class="exam-report-card-title">量化报告</h2>
              <p v-if="lastReadSourceFile" class="exam-report-card-sub">{{ lastReadSourceFile }}</p>
            </div>
            <div class="exam-report-card-actions">
              <button type="button" class="btn btn-ghost btn-sm" @click="openHtmlReportInNewTab">新窗口</button>
              <button
                v-if="htmlReportDownload"
                type="button"
                class="btn btn-connect btn-sm"
                :disabled="downloadingKey === htmlReportDownloadKey"
                @click="downloadHtmlReport"
              >
                {{ downloadingKey === htmlReportDownloadKey ? '…' : '下载' }}
              </button>
            </div>
          </header>
          <iframe
            class="exam-report-card-frame"
            :src="htmlReportPreviewUrl"
            title="量化报告预览"
            sandbox="allow-same-origin"
          />
        </article>

        <details v-if="showMoreDrawer" class="exam-more">
          <summary>更多：摘要与下载</summary>
          <div v-if="resultSummary" class="exam-more-summary" v-html="resultSummaryHtml" />
          <div v-if="showManualReportButton" class="exam-more-actions">
            <button
              type="button"
              class="btn btn-action btn-sm"
              :disabled="pipelineBusy"
              @click="generateReportFromRead"
            >
              {{ manualReportButtonLabel }}
            </button>
          </div>
          <ul v-if="downloads.length" class="exam-more-files">
            <li v-for="d in downloads" :key="`${d.jobId}:${d.filename}`">
              <button
                type="button"
                class="exam-more-file-btn"
                :disabled="downloadingKey === `${d.jobId}:${d.filename}`"
                @click="downloadOutput(d)"
              >
                {{ downloadingKey === `${d.jobId}:${d.filename}` ? '下载中…' : (d.label || d.filename) }}
              </button>
            </li>
          </ul>
          <details v-if="rawJsonPreview" class="exam-raw">
            <summary>原始 JSON</summary>
            <pre class="exam-raw-pre">{{ rawJsonPreview }}</pre>
          </details>
        </details>

        <section
          v-if="showFailurePanel"
          class="exam-failure"
        >
          <h2 class="exam-failure-title">试跑失败</h2>
          <div v-if="resultSummary" class="exam-failure-body" v-html="resultSummaryHtml" />
        </section>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import { ApiError } from '../infrastructure/http/client'
import {
  employeeAcceptsFileExtension,
  employeeFileMismatchHint,
  extractDocumentFullJsonText,
  extractEmployeeExecuteDiagnostics,
  formatEmployeeReadResultSummary,
  JSON_REPORT_EMPLOYEE_ID,
  parseEmployeeOutputDownloads,
  pickDocumentFullJsonDownload,
  pickQuantitativeReportDownload,
  readEmployeeDisplayName,
  resolveReadEmployeeForExtension,
  suggestEmployeeForUploadedFile,
  type EmployeeOutputDownload,
} from '../utils/tabularReadEmployees'

const DEFAULT_EMPLOYEE_ID = 'word-full-read-employee'

type EmployeeOption = { id: string; name: string }

const employeeOptions = ref<EmployeeOption[]>([])
const selectedEmployeeId = ref('')
const loadingEmployees = ref(false)
const employeesError = ref('')

const selectedFile = ref<File | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)
const dragOver = ref(false)

const running = ref(false)
const runError = ref('')
const resultSummary = ref('')
const rawJsonPreview = ref('')
const downloads = ref<EmployeeOutputDownload[]>([])
const downloadingKey = ref('')
const htmlReportPreviewUrl = ref('')
const htmlPreviewLoading = ref(false)
const reportFromReadLoading = ref(false)
/** execute-file + LLM 报告生成允许的最长等待（毫秒） */
const REPORT_EXECUTE_TIMEOUT_MS = 300_000

type PipelineStepId = 'word' | 'prepare_json' | 'report' | 'preview'
type PipelineStepStatus = 'pending' | 'active' | 'done' | 'error' | 'skipped'

const PIPELINE_WORD_FLOW: { id: PipelineStepId; label: string }[] = [
  { id: 'word', label: '读取 Word 文档' },
  { id: 'prepare_json', label: '准备 document_full.json' },
  { id: 'report', label: '生成 HTML 量化报告' },
  { id: 'preview', label: '加载报告预览' },
]

const PIPELINE_JSON_FLOW: { id: PipelineStepId; label: string }[] = [
  { id: 'prepare_json', label: '校验 JSON 文档' },
  { id: 'report', label: '生成 HTML 量化报告' },
  { id: 'preview', label: '加载报告预览' },
]

const pipelineFlow = ref<typeof PIPELINE_WORD_FLOW | typeof PIPELINE_JSON_FLOW>(PIPELINE_WORD_FLOW)
const pipelineStatuses = ref<Record<PipelineStepId, PipelineStepStatus>>({
  word: 'pending',
  prepare_json: 'pending',
  report: 'pending',
  preview: 'pending',
})
const pipelineMessage = ref('')
const pipelineVisible = ref(false)

type ExamRunKind = 'word_chain' | 'json_only'
const lastRunKind = ref<ExamRunKind | null>(null)
/** 用户本次试跑选用的源文件名（如 1.docx），不随报告阶段改为 document_full.json */
const lastRunSourceFile = ref('')

function resetPipeline(flow: typeof PIPELINE_WORD_FLOW | typeof PIPELINE_JSON_FLOW) {
  pipelineFlow.value = flow
  const statuses: Record<PipelineStepId, PipelineStepStatus> = {
    word: 'skipped',
    prepare_json: 'pending',
    report: 'pending',
    preview: 'pending',
  }
  for (const step of flow) {
    statuses[step.id] = 'pending'
  }
  for (const id of ['word', 'prepare_json', 'report', 'preview'] as PipelineStepId[]) {
    if (!flow.some((s) => s.id === id)) statuses[id] = 'skipped'
  }
  pipelineStatuses.value = statuses
  pipelineMessage.value = ''
  pipelineVisible.value = true
}

function setPipelineStep(id: PipelineStepId, status: PipelineStepStatus, message?: string) {
  pipelineStatuses.value = { ...pipelineStatuses.value, [id]: status }
  if (message !== undefined) pipelineMessage.value = message
}

const pipelineBusy = computed(
  () => running.value || reportFromReadLoading.value || htmlPreviewLoading.value,
)

const showPipelinePanel = computed(() => pipelineVisible.value)

const pipelineStepViews = computed(() => {
  const iconMap: Record<PipelineStepStatus, string> = {
    pending: '○',
    active: '◉',
    done: '✓',
    error: '✕',
    skipped: '—',
  }
  return pipelineFlow.value.map((step) => ({
    id: step.id,
    label: step.label,
    status: pipelineStatuses.value[step.id] || 'pending',
    icon: iconMap[pipelineStatuses.value[step.id] || 'pending'],
  }))
})

const pipelinePercent = computed(() => {
  const steps = pipelineFlow.value
  if (!steps.length) return 0
  let score = 0
  for (const step of steps) {
    const st = pipelineStatuses.value[step.id]
    if (st === 'done') score += 1
    else if (st === 'active') score += 0.45
    else if (st === 'error') score += 0.2
  }
  return Math.min(100, Math.round((score / steps.length) * 100))
})
const lastReadSourceFile = ref('')
const lastExecuteResult = ref<unknown>(null)
const executeFailed = ref(false)
const reportError = ref('')
const employeeAutoSwitchNote = ref('')
/** Word 试跑已成功、尚无可预览 HTML 报告（用于显示「生成/重新生成」） */
const wordReadSucceeded = ref(false)
const wordPhaseSummary = ref('')
const wordPhaseDownloads = ref<EmployeeOutputDownload[]>([])
const reportHeroRef = ref<HTMLElement | null>(null)

/** 考试报告：跳过 LLM，用服务端模板秒级出 HTML（避免长时间卡在「生成报告」） */
const EXAM_REPORT_INPUT = { action: 'convert' as const, skip_llm: true }

const pipelineComplete = computed(() => {
  if (!pipelineVisible.value || pipelineBusy.value) return false
  return pipelineFlow.value.every((step) => {
    const st = pipelineStatuses.value[step.id]
    return st === 'done' || st === 'skipped'
  })
})

const showFailurePanel = computed(() => {
  if (pipelineBusy.value || htmlReportPreviewUrl.value) return false
  return executeFailed.value && Boolean(resultSummary.value || runError.value)
})

const showMoreDrawer = computed(() => {
  if (!htmlReportPreviewUrl.value || pipelineBusy.value) return false
  return Boolean(resultSummary.value) || downloads.value.length > 0 || showManualReportButton.value
})

const htmlReportDownloadKey = computed(() => {
  const d = htmlReportDownload.value
  return d ? `${d.jobId}:${d.filename}` : ''
})

const acceptAttr = computed(() =>
  selectedEmployeeId.value === JSON_REPORT_EMPLOYEE_ID
    ? '.json,application/json'
    : '.docx,.doc,.docm,.dotx,.dotm,.rtf,.xlsx,.xlsm,.xls,.csv,.pdf,.pptx,.ppt',
)

const dropZoneSubtext = computed(() =>
  selectedEmployeeId.value === JSON_REPORT_EMPLOYEE_ID
    ? '仅支持 .json（推荐 Word 全量读取产出的 document_full.json）'
    : '支持 Word / Excel / CSV / PDF / PPT 等（与读取员工类型一致）',
)

const jsonReportUploadHint = computed(() =>
  selectedEmployeeId.value === JSON_REPORT_EMPLOYEE_ID
    ? '上传 Word 全量读取员产出的 document_full.json，或含 execute_result / document_full 的 JSON。推荐：先 Word 全量读取试跑（会自动生成报告）。'
    : '',
)

const documentFullDownload = computed(() => pickDocumentFullJsonDownload(downloads.value))

const htmlReportDownload = computed(() => pickQuantitativeReportDownload(downloads.value))

const canGenerateReportFromRead = computed(() => {
  if (pipelineBusy.value) return false
  if (documentFullDownload.value) return true
  return Boolean(extractDocumentFullJsonText(lastExecuteResult.value))
})

/** 有 document_full 或 Word 已试跑成功时显示「生成/重新生成报告」。 */
const showManualReportButton = computed(() => {
  if (reportFromReadLoading.value) return false
  if (htmlReportDownload.value) return true
  if (canGenerateReportFromRead.value) return true
  return wordReadSucceeded.value && !executeFailed.value
})

const manualReportButtonLabel = computed(() =>
  htmlReportDownload.value || reportError.value ? '重新生成报告' : '生成量化报告',
)

const examPrimaryLabel = computed(() => {
  if (pipelineBusy.value) return '处理中，请稍候…'
  if (selectedEmployeeId.value === JSON_REPORT_EMPLOYEE_ID) return '生成 HTML 报告'
  if (selectedEmployeeId.value === DEFAULT_EMPLOYEE_ID) return '试跑并自动生成报告'
  return '开始考试'
})

const canRun = computed(
  () =>
    Boolean(
      selectedEmployeeId.value &&
        selectedFile.value &&
        !pipelineBusy.value &&
        !loadingEmployees.value,
    ),
)

const legacyDocHint = computed(() => {
  const file = selectedFile.value
  const eid = selectedEmployeeId.value
  if (!file || eid !== 'word-full-read-employee') return ''
  const ext = file.name.split('.').pop()?.toLowerCase() || ''
  if (ext === 'doc') {
    return '旧版 .doc 需服务器 LibreOffice 转换；若试跑失败，请另存为 .docx 后重试。'
  }
  return ''
})

const lastRunStatusLine = computed(() => {
  if (pipelineBusy.value) return ''
  if (!pipelineComplete.value && !htmlReportPreviewUrl.value) return ''
  const src = lastRunSourceFile.value.trim()
  if (!src) return ''
  if (lastRunKind.value === 'word_chain') {
    return `已完成：${src} → HTML 量化报告（Word 读取 + 报告生成）`
  }
  if (lastRunKind.value === 'json_only') {
    return `已完成：${src} → HTML 量化报告`
  }
  return ''
})

const fileHint = computed(() => {
  if (pipelineBusy.value || pipelineComplete.value || htmlReportPreviewUrl.value) return ''
  const file = selectedFile.value
  const eid = selectedEmployeeId.value
  if (!file || !eid) return ''
  const ext = file.name.split('.').pop()?.toLowerCase() || ''
  if (employeeAcceptsFileExtension(eid, ext)) return ''
  return employeeFileMismatchHint(eid, ext)
})

const resultSummaryHtml = computed(() => {
  const text = resultSummary.value
  if (!text) return ''
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/```([\s\S]*?)```/g, '<pre class="exam-inline-pre">$1</pre>')
    .replace(/\n/g, '<br>')
})

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

function revokeHtmlPreview() {
  if (htmlReportPreviewUrl.value) {
    URL.revokeObjectURL(htmlReportPreviewUrl.value)
    htmlReportPreviewUrl.value = ''
  }
}

function buildWordChainSummary(sourceDoc: string): string {
  const doc = sourceDoc.trim() || 'Word 文档'
  return [
    '**考试流程已完成**',
    `1. **Word 全量读取**：\`${doc}\` → \`document_full.json\``,
    '2. **JSON 量化报告员**：已生成 HTML 量化报告',
    '',
    '右侧为报告预览；完整摘要与下载见「更多」。',
  ].join('\n')
}

function resetStaleRunUi() {
  pipelineVisible.value = false
  pipelineMessage.value = ''
  lastRunKind.value = null
  lastRunSourceFile.value = ''
  wordPhaseSummary.value = ''
  wordPhaseDownloads.value = []
  wordReadSucceeded.value = false
  resultSummary.value = ''
  downloads.value = []
  rawJsonPreview.value = ''
  executeFailed.value = false
  lastExecuteResult.value = null
  reportError.value = ''
  revokeHtmlPreview()
}

function pickFile(file: File | undefined) {
  if (!file) return
  if (!pipelineBusy.value) resetStaleRunUi()
  const ext = file.name.split('.').pop()?.toLowerCase() || ''
  const suggested = suggestEmployeeForUploadedFile(ext)
  const cur = selectedEmployeeId.value.trim()
  employeeAutoSwitchNote.value = ''
  if (suggested && cur && !employeeAcceptsFileExtension(cur, ext)) {
    const hasOpt = employeeOptions.value.some((o) => o.id === suggested)
    if (hasOpt) {
      selectedEmployeeId.value = suggested
      employeeAutoSwitchNote.value = `已自动切换为「${readEmployeeDisplayName(suggested)}」，以匹配 ${file.name}。`
    }
  }
  selectedFile.value = file
  runError.value = ''
  resultSummary.value = ''
  rawJsonPreview.value = ''
  downloads.value = []
  revokeHtmlPreview()
}

function onFileInput(ev: Event) {
  const input = ev.target as HTMLInputElement
  pickFile(input.files?.[0])
  if (input) input.value = ''
}

function onDrop(ev: DragEvent) {
  dragOver.value = false
  pickFile(ev.dataTransfer?.files?.[0])
}

function clearFile() {
  if (!pipelineBusy.value) resetStaleRunUi()
  selectedFile.value = null
  runError.value = ''
}

async function loadEmployees() {
  loadingEmployees.value = true
  employeesError.value = ''
  const merged = new Map<string, EmployeeOption>()
  try {
    const rows = await api.listEmployees()
    for (const e of Array.isArray(rows) ? rows : []) {
      const row = e as { id?: string; name?: string }
      const id = String(row.id || '').trim()
      if (!id) continue
      merged.set(id, { id, name: String(row.name || id).trim() || id })
    }
  } catch (e: unknown) {
    employeesError.value = `加载员工列表失败：${(e as Error)?.message || String(e)}`
  }
  try {
    const r = await api.listV1Packages('employee_pack', '', 120, 0)
    for (const p of r?.packages || []) {
      const row = p as { id?: string; name?: string }
      const id = String(row.id || '').trim()
      if (!id) continue
      const name = String(row.name || id).trim() || id
      const existing = merged.get(id)
      merged.set(id, existing ? { id, name: existing.name } : { id, name })
    }
  } catch {
    /* optional */
  }
  if (!merged.has(JSON_REPORT_EMPLOYEE_ID)) {
    merged.set(JSON_REPORT_EMPLOYEE_ID, {
      id: JSON_REPORT_EMPLOYEE_ID,
      name: readEmployeeDisplayName(JSON_REPORT_EMPLOYEE_ID),
    })
  }
  employeeOptions.value = [...merged.values()].sort((a, b) => {
    const order = [DEFAULT_EMPLOYEE_ID, JSON_REPORT_EMPLOYEE_ID]
    const ai = order.indexOf(a.id)
    const bi = order.indexOf(b.id)
    if (ai >= 0 || bi >= 0) return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi)
    return a.name.localeCompare(b.name, 'zh-CN')
  })
  loadingEmployees.value = false
  if (!employeeOptions.value.length) {
    selectedEmployeeId.value = ''
    return
  }
  const cur = selectedEmployeeId.value.trim()
  if (!cur || !merged.has(cur)) {
    const preferred = merged.get(DEFAULT_EMPLOYEE_ID)
    selectedEmployeeId.value = preferred ? preferred.id : employeeOptions.value[0].id
  }
}

function wordReadReadyForReport(): boolean {
  if (pickDocumentFullJsonDownload(downloads.value)) return true
  if (pickDocumentFullJsonDownload(parseEmployeeOutputDownloads(lastExecuteResult.value))) return true
  return Boolean(extractDocumentFullJsonText(lastExecuteResult.value))
}

async function autoGenerateReportAfterWordRead(): Promise<void> {
  await nextTick()
  if (!wordReadReadyForReport()) {
    setPipelineStep('prepare_json', 'error', '未找到 document_full.json')
    reportError.value =
      'Word 读取已完成，但未解析到 document_full.json。请点「重新生成报告」重试，或查看下方可下载产出是否含 document_full.json。'
    return
  }
  await generateReportFromRead()
}

function formatRunError(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 403) {
      return '无权执行该员工包：需购买/订阅、成为作者，或使用管理员账号。'
    }
    if (e.status === 413) return e.message || '文件过大'
    const msg = e.message || `HTTP ${e.status}`
    if (e.status === 400 && /文件类型|不匹配|\.json/i.test(msg)) {
      return `${msg}（生成报告需后端支持 .json 上传；若 Word 读取已成功，请联系管理员重启 modstore API 或稍后重试。）`
    }
    return msg
  }
  return (e as Error)?.message || String(e)
}

function applyWordPhaseResult(fileName: string, res: unknown) {
  const diag = extractEmployeeExecuteDiagnostics(res)
  executeFailed.value = !diag.success
  lastExecuteResult.value = res
  const { text, downloads: dls } = formatEmployeeReadResultSummary(DEFAULT_EMPLOYEE_ID, fileName, res, {
    includeLlmExcerpt: false,
  })
  wordPhaseSummary.value = text
  wordPhaseDownloads.value = dls
  downloads.value = dls
  resultSummary.value = executeFailed.value ? text : ''
  if (!executeFailed.value) {
    runError.value = ''
    reportError.value = ''
  } else if (diag.error) {
    runError.value = diag.error
  }
  try {
    rawJsonPreview.value = JSON.stringify(res, null, 2).slice(0, 24_000)
  } catch {
    rawJsonPreview.value = String(res)
  }
}

function applyExecuteResult(eid: string, fileName: string, res: unknown) {
  const diag = extractEmployeeExecuteDiagnostics(res)
  executeFailed.value = !diag.success
  lastExecuteResult.value = res
  const { text, downloads: dls } = formatEmployeeReadResultSummary(eid, fileName, res, {
    includeLlmExcerpt: eid !== JSON_REPORT_EMPLOYEE_ID,
  })
  const reportDls = parseEmployeeOutputDownloads(res)
  if (eid === JSON_REPORT_EMPLOYEE_ID && wordPhaseSummary.value) {
    const src = lastRunSourceFile.value.trim() || lastReadSourceFile.value.trim()
    resultSummary.value = buildWordChainSummary(src)
    const seen = new Set<string>()
    downloads.value = [...wordPhaseDownloads.value, ...reportDls].filter((d) => {
      const k = `${d.jobId}:${d.filename}`
      if (seen.has(k)) return false
      seen.add(k)
      return true
    })
  } else {
    resultSummary.value = text
    downloads.value = dls.length ? dls : reportDls
  }
  if (!executeFailed.value) {
    runError.value = ''
    if (eid === 'word-full-read-employee') reportError.value = ''
  }
  try {
    rawJsonPreview.value = JSON.stringify(res, null, 2).slice(0, 24_000)
  } catch {
    rawJsonPreview.value = String(res)
  }
}

async function runExam() {
  let eid = selectedEmployeeId.value.trim()
  const file = selectedFile.value
  if (!eid || !file) return
  const ext = file.name.split('.').pop()?.toLowerCase() || ''
  if (!employeeAcceptsFileExtension(eid, ext)) {
    const suggested = suggestEmployeeForUploadedFile(ext)
    if (suggested && employeeOptions.value.some((o) => o.id === suggested)) {
      selectedEmployeeId.value = suggested
      eid = suggested
      employeeAutoSwitchNote.value = `已自动切换为「${readEmployeeDisplayName(suggested)}」后再试跑。`
    } else {
      runError.value = employeeFileMismatchHint(eid, ext)
      return
    }
  }
  const isWordFlow = eid === DEFAULT_EMPLOYEE_ID
  const isJsonFlow = eid === JSON_REPORT_EMPLOYEE_ID
  if (isWordFlow) {
    lastRunKind.value = 'word_chain'
    lastRunSourceFile.value = file.name
    resetPipeline(PIPELINE_WORD_FLOW)
  } else if (isJsonFlow) {
    lastRunKind.value = 'json_only'
    lastRunSourceFile.value = file.name
    resetPipeline(PIPELINE_JSON_FLOW)
  } else {
    lastRunKind.value = null
    lastRunSourceFile.value = file.name
    pipelineVisible.value = false
  }

  running.value = true
  runError.value = ''
  reportError.value = ''
  wordReadSucceeded.value = false
  wordPhaseSummary.value = ''
  wordPhaseDownloads.value = []
  resultSummary.value = ''
  rawJsonPreview.value = ''
  downloads.value = []
  revokeHtmlPreview()
  try {
    if (isWordFlow) {
      setPipelineStep('word', 'active', '解析段落、表格、图片与样式…')
    } else if (isJsonFlow) {
      setPipelineStep('prepare_json', 'active', '校验 JSON 文档结构…')
    }
    const res = await api.employeeExecuteFile(eid, file, {
      task: isJsonFlow ? '考试生成量化报告' : '考试试跑',
      inputData: isJsonFlow ? { ...EXAM_REPORT_INPUT } : { action: 'convert' },
      timeoutMs: isWordFlow || isJsonFlow ? REPORT_EXECUTE_TIMEOUT_MS : undefined,
    })
    if (isWordFlow) {
      lastReadSourceFile.value = file.name
    }
    if (isWordFlow) {
      applyWordPhaseResult(file.name, res)
    } else {
      applyExecuteResult(eid, file.name, res)
    }
    if (isWordFlow && !executeFailed.value) {
      wordReadSucceeded.value = true
      setPipelineStep('word', 'done', 'Word 读取完成')
    } else if (isWordFlow && executeFailed.value) {
      setPipelineStep('word', 'error', runError.value || 'Word 读取失败')
    } else if (isJsonFlow) {
      if (executeFailed.value) {
        setPipelineStep('prepare_json', 'error', runError.value || 'JSON 校验失败')
      } else {
        setPipelineStep('prepare_json', 'done', 'JSON 已就绪')
        setPipelineStep('report', 'done', '报告生成完成')
      }
    }
    if (isJsonFlow && pickQuantitativeReportDownload(parseEmployeeOutputDownloads(res))) {
      await previewHtmlReport()
    } else if (isWordFlow && !executeFailed.value) {
      await autoGenerateReportAfterWordRead()
      return
    }
  } catch (e: unknown) {
    runError.value = formatRunError(e)
    if (isWordFlow) setPipelineStep('word', 'error', runError.value)
    else if (isJsonFlow) setPipelineStep('report', 'error', runError.value)
  } finally {
    running.value = false
  }
}

function isJsonOnlyReportContext(): boolean {
  const file = selectedFile.value
  const eid = selectedEmployeeId.value
  if (eid !== JSON_REPORT_EMPLOYEE_ID || !file) return false
  return file.name.toLowerCase().endsWith('.json')
}

function ensureReportPipelineVisible() {
  if (pipelineVisible.value) return
  const jsonOnly = isJsonOnlyReportContext()
  if (jsonOnly) {
    resetPipeline(PIPELINE_JSON_FLOW)
    return
  }
  resetPipeline(PIPELINE_WORD_FLOW)
  const src = lastRunSourceFile.value.trim() || lastReadSourceFile.value.trim()
  if (wordReadSucceeded.value || documentFullDownload.value || src) {
    setPipelineStep('word', 'done', src ? `已读取 ${src}` : 'Word 读取完成')
  }
}

async function generateReportFromRead() {
  if (reportFromReadLoading.value) return
  ensureReportPipelineVisible()
  const docDl = documentFullDownload.value
  reportFromReadLoading.value = true
  reportError.value = ''
  revokeHtmlPreview()
  let shouldPreviewReport = false
  try {
    setPipelineStep('prepare_json', 'active', '获取 document_full.json…')
    let jsonFile: File
    if (docDl) {
      const blob = await api.employeeOutputDownload(docDl.jobId, docDl.filename)
      jsonFile = new File([blob], 'document_full.json', { type: 'application/json' })
    } else {
      const text = extractDocumentFullJsonText(lastExecuteResult.value)
      if (!text) {
        setPipelineStep('prepare_json', 'error', '未找到 document_full.json')
        reportError.value = '未找到 document_full.json：请重新试跑 Word 读取，或检查下载列表。'
        return
      }
      jsonFile = new File([text], 'document_full.json', { type: 'application/json' })
    }
    setPipelineStep('prepare_json', 'done', 'JSON 已就绪')
    setPipelineStep('report', 'active', '正在生成 HTML 量化报告（考试模式：模板报告，约 5–15 秒）…')
    const res = await api.employeeExecuteFile(JSON_REPORT_EMPLOYEE_ID, jsonFile, {
      task: '考试生成量化报告',
      inputData: { ...EXAM_REPORT_INPUT },
      timeoutMs: REPORT_EXECUTE_TIMEOUT_MS,
    })
    const src = lastRunSourceFile.value.trim() || lastReadSourceFile.value.trim()
    if (!lastRunKind.value && src) {
      lastRunKind.value = 'word_chain'
      lastRunSourceFile.value = src
    }
    applyExecuteResult(JSON_REPORT_EMPLOYEE_ID, 'document_full.json', res)
    if (lastRunKind.value === 'word_chain' && src) {
      resultSummary.value = buildWordChainSummary(src)
    } else if (isJsonOnlyReportContext()) {
      lastRunKind.value = 'json_only'
      lastRunSourceFile.value = selectedFile.value?.name || 'document_full.json'
    }
    shouldPreviewReport = Boolean(pickQuantitativeReportDownload(parseEmployeeOutputDownloads(res)))
    if (!shouldPreviewReport) {
      setPipelineStep('report', 'error', '未找到 quantitative_report.html')
      reportError.value = '报告已执行但未找到 quantitative_report.html，请查看试跑摘要或下载列表。'
    } else {
      setPipelineStep('report', 'done', 'HTML 量化报告已生成')
    }
  } catch (e: unknown) {
    reportError.value = formatRunError(e)
    setPipelineStep('report', 'error', reportError.value)
  } finally {
    reportFromReadLoading.value = false
  }
  if (shouldPreviewReport) {
    await previewHtmlReport()
  }
}

async function previewHtmlReport() {
  const d = htmlReportDownload.value
  if (!d) return
  if (pipelineStatuses.value.preview !== 'skipped') {
    setPipelineStep('preview', 'active', '加载 HTML 预览…')
  }
  htmlPreviewLoading.value = true
  try {
    const blob = await api.employeeOutputDownload(d.jobId, d.filename)
    revokeHtmlPreview()
    htmlReportPreviewUrl.value = URL.createObjectURL(blob)
    setPipelineStep('preview', 'done', '报告已就绪')
    await nextTick()
    reportHeroRef.value?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  } catch (e: unknown) {
    const msg = `预览失败：${(e as Error)?.message || String(e)}`
    runError.value = msg
    setPipelineStep('preview', 'error', msg)
  } finally {
    htmlPreviewLoading.value = false
  }
}

async function downloadHtmlReport() {
  const d = htmlReportDownload.value
  if (!d) return
  await downloadOutput(d)
}

function openHtmlReportInNewTab() {
  if (htmlReportPreviewUrl.value) {
    window.open(htmlReportPreviewUrl.value, '_blank', 'noopener,noreferrer')
  }
}

async function downloadOutput(d: EmployeeOutputDownload) {
  const key = `${d.jobId}:${d.filename}`
  downloadingKey.value = key
  try {
    const blob = await api.employeeOutputDownload(d.jobId, d.filename)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = d.filename
    a.click()
    URL.revokeObjectURL(url)
  } catch (e: unknown) {
    runError.value = `下载失败：${(e as Error)?.message || String(e)}`
  } finally {
    downloadingKey.value = ''
  }
}

watch(selectedEmployeeId, (next, prev) => {
  if (prev === undefined || next === prev) return
  runError.value = ''
  employeeAutoSwitchNote.value = ''
  if (!pipelineBusy.value) resetStaleRunUi()
})

onMounted(() => {
  void loadEmployees()
})
</script>

<style scoped>
.employee-exam-page {
  height: 100%;
  min-height: 0;
  padding: 12px 14px 16px;
  overflow: auto;
  color: var(--color-text-primary, #fff);
}

.exam-grid {
  display: grid;
  grid-template-columns: minmax(260px, 340px) minmax(0, 1fr);
  gap: 14px;
  align-items: stretch;
  min-height: min(100%, 720px);
}

@media (max-width: 960px) {
  .exam-grid {
    grid-template-columns: 1fr;
    min-height: 0;
  }
}

.exam-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
}

.exam-panel--control {
  padding: 14px;
  border-radius: 12px;
  border: 0.5px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.03);
}

.exam-panel--output {
  padding: 14px;
  border-radius: 12px;
  border: 0.5px solid rgba(255, 255, 255, 0.08);
  background: rgba(0, 0, 0, 0.15);
  min-height: 320px;
}

.exam-panel-head {
  margin-bottom: 2px;
}

.exam-page-title {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 600;
  letter-spacing: -0.02em;
}

.exam-page-sub {
  margin: 4px 0 0;
  font-size: 0.78rem;
  color: var(--color-text-muted, rgba(255, 255, 255, 0.5));
}

.exam-config {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 8px;
  align-items: center;
}

.exam-label {
  font-size: 0.78rem;
  color: var(--color-text-muted, rgba(255, 255, 255, 0.5));
  white-space: nowrap;
}

.exam-select {
  width: 100%;
  min-width: 0;
  padding: 7px 10px;
  border-radius: 8px;
  border: 0.5px solid rgba(255, 255, 255, 0.12);
  background: rgba(0, 0, 0, 0.2);
  color: inherit;
  font-size: 0.84rem;
}

.exam-alert {
  margin: 0;
  padding: 8px 10px;
  border-radius: 8px;
  font-size: 0.78rem;
  line-height: 1.45;
  background: rgba(255, 255, 255, 0.04);
}

.exam-alert--err {
  color: #fecaca;
  background: rgba(248, 113, 113, 0.12);
  border: 0.5px solid rgba(248, 113, 113, 0.25);
}

.exam-alert--warn {
  color: #fde68a;
  background: rgba(251, 191, 36, 0.1);
  border: 0.5px solid rgba(251, 191, 36, 0.2);
}

.exam-alert--ok {
  color: #bbf7d0;
  background: rgba(74, 222, 128, 0.08);
  border: 0.5px solid rgba(74, 222, 128, 0.2);
}

.exam-done-chip {
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 0.8rem;
  font-weight: 500;
  color: #86efac;
  background: rgba(74, 222, 128, 0.1);
  border: 0.5px solid rgba(74, 222, 128, 0.25);
  text-align: center;
}

.exam-run-status {
  margin: 0;
  font-size: 0.78rem;
  line-height: 1.45;
  color: rgba(255, 255, 255, 0.68);
}

.exam-dropzone {
  border: 1px dashed rgba(255, 255, 255, 0.18);
  border-radius: 10px;
  padding: 14px 12px;
  text-align: center;
  background: rgba(0, 0, 0, 0.12);
  transition: border-color 0.15s, background 0.15s;
}

.exam-dropzone--active {
  border-color: #60a5fa;
  background: rgba(96, 165, 250, 0.08);
}

.exam-dropzone--has-file {
  border-style: solid;
}

.exam-file-input {
  display: none;
}

.exam-drop-title {
  margin: 0 0 4px;
  font-weight: 500;
}

.exam-drop-sub {
  margin: 0 0 12px;
  font-size: 0.82rem;
  color: var(--color-text-muted, rgba(255, 255, 255, 0.5));
}

.exam-file-chip {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-bottom: 8px;
  text-align: left;
}

.exam-file-chip-name {
  font-size: 0.86rem;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.exam-file-chip-meta {
  font-size: 0.75rem;
  color: var(--color-text-muted, rgba(255, 255, 255, 0.45));
}

.exam-pipeline {
  padding: 10px 12px;
  border-radius: 10px;
  border: 0.5px solid rgba(96, 165, 250, 0.28);
  background: rgba(96, 165, 250, 0.05);
}

.exam-pipeline-bar-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.exam-pipeline-message {
  margin: 0 0 8px;
  font-size: 0.76rem;
  color: var(--color-text-muted, rgba(255, 255, 255, 0.6));
  line-height: 1.4;
}

.exam-pipeline-pct {
  font-size: 0.72rem;
  font-variant-numeric: tabular-nums;
  color: #93c5fd;
  flex-shrink: 0;
}

.exam-pipeline-bar {
  flex: 1;
  height: 5px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  overflow: hidden;
}

.exam-pipeline-bar-fill {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #3b82f6, #60a5fa);
  transition: width 0.35s ease;
}

.exam-pipeline-steps {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.exam-pipeline-step {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.82rem;
  color: var(--color-text-muted, rgba(255, 255, 255, 0.45));
}

.exam-pipeline-step--active {
  color: #93c5fd;
  font-weight: 500;
}

.exam-pipeline-step--done {
  color: #86efac;
}

.exam-pipeline-step--error {
  color: #f87171;
}

.exam-pipeline-step--skipped {
  display: none;
}

.exam-pipeline-step-icon {
  width: 1.1rem;
  text-align: center;
  flex-shrink: 0;
}

.exam-output-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 32px 16px;
  border-radius: 10px;
  border: 1px dashed rgba(255, 255, 255, 0.12);
  min-height: 280px;
}

.exam-output-empty--busy {
  border-style: solid;
  border-color: rgba(96, 165, 250, 0.25);
  background: rgba(96, 165, 250, 0.04);
}

.exam-output-empty-title {
  margin: 0 0 6px;
  font-size: 0.92rem;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.75);
}

.exam-output-empty-sub {
  margin: 0;
  font-size: 0.78rem;
  color: var(--color-text-muted, rgba(255, 255, 255, 0.45));
  max-width: 240px;
}

.exam-report-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  flex: 1;
  min-height: 0;
}

.exam-report-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  flex-shrink: 0;
}

.exam-report-card-title {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 600;
}

.exam-report-card-sub {
  margin: 2px 0 0;
  font-size: 0.74rem;
  color: var(--color-text-muted, rgba(255, 255, 255, 0.5));
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 280px;
}

.exam-report-card-actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}

.exam-report-card-frame {
  flex: 1;
  width: 100%;
  min-height: min(58vh, 560px);
  border: none;
  border-radius: 10px;
  background: #fff;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.35);
}

.exam-more {
  margin-top: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  border: 0.5px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.02);
  font-size: 0.78rem;
}

.exam-more summary {
  cursor: pointer;
  user-select: none;
  color: var(--color-text-muted, rgba(255, 255, 255, 0.55));
}

.exam-more-summary {
  margin-top: 10px;
  font-size: 0.8rem;
  line-height: 1.5;
  color: rgba(255, 255, 255, 0.7);
}

.exam-more-summary :deep(code) {
  font-size: 0.78em;
  padding: 1px 4px;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.08);
}

.exam-more-actions {
  margin-top: 8px;
}

.exam-more-files {
  list-style: none;
  margin: 10px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.exam-more-file-btn {
  width: 100%;
  text-align: left;
  padding: 6px 8px;
  border: none;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.05);
  color: #93c5fd;
  font-size: 0.78rem;
  cursor: pointer;
}

.exam-more-file-btn:hover:not(:disabled) {
  background: rgba(96, 165, 250, 0.12);
}

.exam-failure {
  margin-top: 12px;
  padding: 12px;
  border-radius: 10px;
  border: 0.5px solid rgba(248, 113, 113, 0.35);
  background: rgba(248, 113, 113, 0.08);
}

.exam-failure-title {
  margin: 0 0 8px;
  font-size: 0.9rem;
  color: #fca5a5;
}

.exam-failure-body {
  font-size: 0.82rem;
  line-height: 1.5;
}

.exam-raw {
  margin-top: 12px;
  font-size: 0.8rem;
}

.exam-raw-pre {
  margin: 8px 0 0;
  padding: 8px;
  max-height: 280px;
  overflow: auto;
  font-size: 0.72rem;
  background: rgba(0, 0, 0, 0.35);
  border-radius: 6px;
}

.btn {
  padding: 6px 14px;
  border-radius: 8px;
  font-size: 0.84rem;
  cursor: pointer;
  border: 0.5px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.06);
  color: var(--color-text-primary, #fff);
  transition: background 0.15s, border-color 0.15s;
  white-space: nowrap;
}

.btn-sm {
  padding: 5px 10px;
  font-size: 0.78rem;
}

.btn-block {
  width: 100%;
  padding: 10px 16px;
  font-weight: 500;
}

.btn-ghost {
  background: transparent;
  border-color: rgba(255, 255, 255, 0.1);
  color: var(--color-text-muted, rgba(255, 255, 255, 0.65));
}

.btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.1);
}

.btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.btn-connect {
  background: rgba(96, 165, 250, 0.15);
  color: #60a5fa;
  border-color: rgba(96, 165, 250, 0.3);
}

.btn-action {
  background: rgba(74, 222, 128, 0.12);
  color: #4ade80;
  border-color: rgba(74, 222, 128, 0.25);
}

html[data-workbench-theme='light'] .employee-exam-page {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .exam-panel--control,
html[data-workbench-theme='light'] .exam-panel--output {
  background: #f8fafc;
  border-color: rgba(0, 0, 0, 0.08);
}

html[data-workbench-theme='light'] .exam-select {
  border-color: rgba(0, 0, 0, 0.1);
  background: #fff;
}

html[data-workbench-theme='light'] .exam-dropzone {
  border-color: rgba(0, 0, 0, 0.12);
  background: #fff;
}

html[data-workbench-theme='light'] .exam-output-empty {
  border-color: rgba(0, 0, 0, 0.1);
}

html[data-workbench-theme='light'] .exam-report-card-frame {
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.08);
}
</style>
