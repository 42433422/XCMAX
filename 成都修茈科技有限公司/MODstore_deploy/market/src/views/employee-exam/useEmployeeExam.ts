// 考试试跑主逻辑：文件选择、流水线、试跑执行、报告生成与下载。
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import type { Ref } from 'vue'
import { api } from '../../api'
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
  suggestEmployeeForUploadedFile,
  type EmployeeOutputDownload,
} from '../../utils/tabularReadEmployees'
import {
  buildWordChainSummary,
  DEFAULT_EMPLOYEE_ID,
  EXAM_REPORT_INPUT,
  formatRunError,
  PIPELINE_JSON_FLOW,
  PIPELINE_WORD_FLOW,
  renderSummaryHtml,
  REPORT_EXECUTE_TIMEOUT_MS,
  type ExamRunKind,
} from './employeeExamTypes'
import { useEmployeeExamPipeline } from './useEmployeeExamPipeline'
import { useEmployeeExamReport } from './useEmployeeExamReport'

type ExamDeps = {
  selectedEmployeeId: Ref<string>
  employeeOptions: Ref<{ id: string; name: string }[]>
  loadingEmployees: Ref<boolean>
  loadEmployees: () => Promise<void>
}

export function useEmployeeExam(deps: ExamDeps) {
  const { selectedEmployeeId, employeeOptions, loadingEmployees } = deps

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

  const lastRunKind = ref<ExamRunKind | null>(null)
  /** 用户本次试跑选用的源文件名（如 1.docx），不随报告阶段改为 document_full.json */
  const lastRunSourceFile = ref('')
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

  const {
    pipelineFlow,
    pipelineStatuses,
    pipelineMessage,
    pipelineVisible,
    resetPipeline,
    setPipelineStep,
    showPipelinePanel,
    pipelineStepViews,
    pipelinePercent,
  } = useEmployeeExamPipeline()

  const pipelineBusy = computed(() => running.value || reportFromReadLoading.value || htmlPreviewLoading.value)

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

  const manualReportButtonLabel = computed(() => (htmlReportDownload.value || reportError.value ? '重新生成报告' : '生成量化报告'))

  const examPrimaryLabel = computed(() => {
    if (pipelineBusy.value) return '处理中，请稍候…'
    if (selectedEmployeeId.value === JSON_REPORT_EMPLOYEE_ID) return '生成 HTML 报告'
    if (selectedEmployeeId.value === DEFAULT_EMPLOYEE_ID) return '试跑并自动生成报告'
    return '开始考试'
  })

  const canRun = computed(() => Boolean(selectedEmployeeId.value && selectedFile.value && !pipelineBusy.value && !loadingEmployees.value))

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

  const resultSummaryHtml = computed(() => renderSummaryHtml(resultSummary.value))

  const {
    revokeHtmlPreview,
    previewHtmlReport,
    downloadHtmlReport,
    openHtmlReportInNewTab,
    downloadOutput,
  } = useEmployeeExamReport({
    htmlReportDownload,
    htmlReportPreviewUrl,
    downloadingKey,
    htmlPreviewLoading,
    reportHeroRef,
    runError,
    pipelineStatuses,
    setPipelineStep,
  })

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

  watch(selectedEmployeeId, (next, prev) => {
    if (prev === undefined || next === prev) return
    runError.value = ''
    employeeAutoSwitchNote.value = ''
    if (!pipelineBusy.value) resetStaleRunUi()
  })

  onMounted(() => {
    void deps.loadEmployees()
  })

  return {
    // 文件与选择
    selectedFile,
    fileInputRef,
    dragOver,
    onFileInput,
    onDrop,
    clearFile,
    acceptAttr,
    dropZoneSubtext,
    jsonReportUploadHint,
    // 流水线
    pipelineBusy,
    showPipelinePanel,
    pipelineStepViews,
    pipelinePercent,
    pipelineMessage,
    pipelineComplete,
    // 试跑与结果
    runExam,
    canRun,
    examPrimaryLabel,
    runError,
    reportError,
    employeeAutoSwitchNote,
    legacyDocHint,
    fileHint,
    lastRunStatusLine,
    lastRunKind,
    resultSummary,
    resultSummaryHtml,
    rawJsonPreview,
    downloads,
    downloadingKey,
    downloadOutput,
    showMoreDrawer,
    showFailurePanel,
    // 报告
    htmlReportPreviewUrl,
    htmlReportDownload,
    htmlReportDownloadKey,
    reportHeroRef,
    lastReadSourceFile,
    canGenerateReportFromRead,
    showManualReportButton,
    manualReportButtonLabel,
    generateReportFromRead,
    previewHtmlReport,
    downloadHtmlReport,
    openHtmlReportInNewTab,
    revokeHtmlPreview,
  }
}
