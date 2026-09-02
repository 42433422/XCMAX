/**
 * Facade：办公对接 composable 装配入口（实现拆分至 officeDocking/ 子模块，行为与拆分前一致）。
 */
import { computed, ref } from 'vue'
import {
  CSV_FULL_READ_EMPLOYEE_ID,
  EXCEL_FULL_READ_EMPLOYEE_ID,
  PPT_FULL_READ_EMPLOYEE_ID,
} from '@/constants/officeEmployeePack'
import {
  isOfficeDockingFileSupported,
  readOfficeEmployeeOutputs,
  resolveOfficeReadEmployeeForFile,
  runOfficeEmployeeRead,
  uploadChatOfficeFile,
} from '@/utils/officeEmployeeReadApi'
import { asArray, asRecord, asString } from '@/utils/typeGuards'
import { buildCsvExcelAnalysis, buildKnowledgeText, buildPptText, buildWorkbookExcelAnalysis } from './officeDocking/officeDockingAnalysis'
import {
  applyShipmentEtlIntent,
  inferOfficeDockingIntent,
} from './officeDocking/officeDockingIntent'
import {
  executeShipmentExcelEtl,
  ingestAttendanceDatabase,
  ingestKnowledge,
  previewShipmentExcelEtl,
} from './officeDocking/officeDockingApi'
import {
  EMPLOYEE_LABELS,
  KIND_LABELS,
  collectEmployeeOutputPaths,
  extractFieldNames,
  extractSampleRows,
  firstJsonData,
  firstText,
  newItemId,
  outputRelpathFor,
  stringifyPreview,
  truncate,
  type ChatOfficeDockingReviewItem,
  type OfficeDockingTarget,
  type UseChatOfficeDockingDeps,
} from './officeDocking/officeDockingShared'

export type { ChatOfficeDockingReviewItem, ShipmentEtlNotePreview, ShipmentEtlPreview } from './officeDocking/officeDockingShared'

export function useChatOfficeDocking(deps: UseChatOfficeDockingDeps) {
  const officeDockingInputRef = ref<HTMLInputElement | null>(null)
  const officeDockingProcessing = ref(false)
  const officeDockingPanelOpen = ref(false)
  const officeDockingReviewItems = ref<ChatOfficeDockingReviewItem[]>([])
  const officeDockingPendingCount = computed(() => officeDockingReviewItems.value.filter((item) => item.status === 'ready').length)

  function triggerOfficeDocking() {
    if (officeDockingProcessing.value) return
    officeDockingInputRef.value?.click()
  }

  function touchItems() {
    officeDockingReviewItems.value = [...officeDockingReviewItems.value]
  }

  async function analyzeFile(file: File): Promise<void> {
    const employeeId = resolveOfficeReadEmployeeForFile(file.name)
    const item: ChatOfficeDockingReviewItem = {
      id: newItemId(),
      fileName: file.name,
      employeeId,
      employeeLabel: EMPLOYEE_LABELS[employeeId] || employeeId || '办公员工',
      kindLabel: KIND_LABELS[employeeId] || '办公文件',
      status: 'running',
      commitStatus: '',
      intentId: 'pending',
      intentLabel: '待识别',
      intentSummary: '正在读取文件内容并判断业务用途',
      databaseTargetLabel: '',
      databaseAction: '',
      databaseDisabledReason: '',
      selectedKnowledge: true,
      selectedDatabase: false,
      summary: '正在调用办公员工识别...',
      warnings: [],
      error: '',
      outputFiles: [],
      knowledgeText: '',
      fieldNames: [],
      sampleRows: [],
      rowCount: 0,
      textPreview: '',
    }
    officeDockingReviewItems.value.push(item)
    touchItems()

    if (!employeeId || !isOfficeDockingFileSupported(file.name)) {
      item.status = 'error'
      item.summary = ''
      item.error = '该文件类型未匹配到办公读取员工'
      touchItems()
      return
    }

    try {
      const upload = await uploadChatOfficeFile(file)
      item.upload = upload
      item.summary = `已上传，正在由 ${item.employeeLabel} 读取...`
      touchItems()
      const employeeData = await runOfficeEmployeeRead(employeeId, upload.file_path, upload.workspace_root, {
        outputRelpath: outputRelpathFor(item.id, employeeId),
      })
      const warnings = [
        ...asArray<unknown>(employeeData.warnings)
          .map((w) => asString(w))
          .filter(Boolean),
        ...asArray<Record<string, unknown>>(employeeData.items)
          .flatMap((row) => asArray<unknown>(row.warnings).map((w) => asString(w)))
          .filter(Boolean),
      ]
      item.warnings = warnings
      const outputs = await readOfficeEmployeeOutputs(upload.workspace_root, collectEmployeeOutputPaths(employeeData))
      item.outputFiles = outputs
      const jsonData = firstJsonData(outputs)
      const textData = firstText(outputs)
      const rawSummary = asString(employeeData.summary).trim()
      item.summary = rawSummary || `${item.employeeLabel} 已完成识别`

      if (employeeId === EXCEL_FULL_READ_EMPLOYEE_ID) {
        item.excelAnalysis = buildWorkbookExcelAnalysis(upload, jsonData, item.summary)
      } else if (employeeId === CSV_FULL_READ_EMPLOYEE_ID) {
        item.excelAnalysis = buildCsvExcelAnalysis(upload, jsonData, item.summary)
      }

      if (employeeId === PPT_FULL_READ_EMPLOYEE_ID) {
        item.textPreview = buildPptText(jsonData)
      } else if (textData) {
        item.textPreview = truncate(textData, 12_000)
      } else if (Object.keys(jsonData).length) {
        item.textPreview = stringifyPreview(jsonData, 12_000)
      }

      item.fieldNames = extractFieldNames(item.excelAnalysis)
      item.sampleRows = extractSampleRows(item.excelAnalysis)
      item.rowCount = item.sampleRows.length
      if (employeeId === CSV_FULL_READ_EMPLOYEE_ID) {
        item.rowCount = Number(jsonData.row_count || item.sampleRows.length) || item.sampleRows.length
      } else if (employeeId === EXCEL_FULL_READ_EMPLOYEE_ID) {
        const sheets = asArray<Record<string, unknown>>(jsonData.sheets)
        item.rowCount = sheets.reduce((sum, sheet) => sum + (Number(sheet.row_count) || 0), 0)
      }
      const intent = inferOfficeDockingIntent(item)
      item.intentId = intent.intentId
      item.intentLabel = intent.intentLabel
      item.intentSummary = intent.intentSummary
      item.databaseTargetLabel = intent.databaseTargetLabel
      item.databaseAction = intent.databaseAction
      item.databaseDisabledReason = intent.databaseDisabledReason
      item.selectedDatabase = intent.selectedDatabase

      const canRunShipmentEtl =
        Boolean(item.upload?.file_path) &&
        item.excelAnalysis &&
        item.intentId !== 'attendance_roster' &&
        item.intentId !== 'attendance_source' &&
        (employeeId === EXCEL_FULL_READ_EMPLOYEE_ID || employeeId === CSV_FULL_READ_EMPLOYEE_ID)
      if (canRunShipmentEtl) {
        try {
          const shipmentPreview = await previewShipmentExcelEtl(item.upload!.file_path, item.upload!.workspace_root)
          if (shipmentPreview) applyShipmentEtlIntent(item, shipmentPreview)
        } catch {
          // 预览失败不阻断办公对接；仍保留字段启发式意图
        }
      }

      item.knowledgeText = buildKnowledgeText(item)
      item.status = 'ready'
      const shipmentNoteCount = Number(item.shipmentEtlPreview?.note_count || 0)
      item.summary = shipmentNoteCount
        ? `${item.employeeLabel} 已识别 ${item.fileName}：送货单 ${shipmentNoteCount} 张；意图：${item.intentLabel}`
        : `${item.employeeLabel} 已识别 ${item.fileName}${item.fieldNames.length ? `，字段 ${item.fieldNames.length} 个` : ''}${item.rowCount ? `，行 ${item.rowCount} 条` : ''}；意图：${item.intentLabel}`
    } catch (err) {
      item.status = 'error'
      item.error = err instanceof Error ? err.message : String(err || '识别失败')
      item.summary = ''
    } finally {
      touchItems()
    }
  }

  async function onOfficeDockingFileChange(event: Event) {
    const input = event.target as HTMLInputElement | null
    const files = Array.from(input?.files || [])
    if (input) input.value = ''
    if (!files.length) return
    officeDockingPanelOpen.value = true
    officeDockingProcessing.value = true
    officeDockingReviewItems.value = []
    await deps.addAndSaveMessage(`[对接] 已收到 ${files.length} 个文件，开始调用办公员工识别。`, 'ai')
    try {
      for (const file of files) {
        await analyzeFile(file)
      }
    } finally {
      officeDockingProcessing.value = false
    }
  }

  function toggleOfficeDockingTarget(id: string, target: OfficeDockingTarget, enabled: boolean) {
    const item = officeDockingReviewItems.value.find((row) => row.id === id)
    if (!item) return
    if (target === 'knowledge') item.selectedKnowledge = enabled
    if (target === 'database' && item.excelAnalysis && item.databaseAction) {
      item.selectedDatabase = enabled
    }
    touchItems()
  }

  async function confirmOfficeDockingReview() {
    const ready = officeDockingReviewItems.value.filter(
      (item) =>
        item.status === 'ready' &&
        item.commitStatus !== 'committed' &&
        item.commitStatus !== 'committing' &&
        (item.selectedKnowledge || item.selectedDatabase),
    )
    if (!ready.length) return
    for (const item of ready) {
      item.commitStatus = 'committing'
      touchItems()
      try {
        if (item.selectedKnowledge) {
          await ingestKnowledge(item)
        }
        if (item.selectedDatabase) {
          if (!item.excelAnalysis) {
            throw new Error('该文件没有可导入数据库的表格上下文')
          }
          if (item.databaseAction === 'attendance_import') {
            const result = await ingestAttendanceDatabase(item)
            const employeeRows = Number(result.employee_rows || 0)
            const departmentRows = Number(result.department_rows || 0)
            item.summary = `考勤入库完成：人员 ${employeeRows} 条，部门 ${departmentRows} 条`
          } else if (item.databaseAction === 'shipment_etl_execute') {
            const result = await executeShipmentExcelEtl(item)
            const noteCount = Number(result.note_count || item.shipmentEtlPreview?.note_count || 0)
            const shipmentCreated = Number(result.shipment_created || 0)
            const productImported = Number(asRecord(result.product_result).imported || 0)
            item.summary = `送货单 ETL 完成：单 ${noteCount || shipmentCreated} 张，发货单新建 ${shipmentCreated}，产品写入 ${productImported}`
          } else if (item.databaseAction === 'customer_product_import') {
            deps.stageExcelAnalysisContext(item.excelAnalysis)
            await deps.sendDatabaseImportMessage(`导入数据库，确认导入：${item.fileName}`)
          } else {
            throw new Error(item.databaseDisabledReason || '未识别到可写入的业务数据库')
          }
        }
        item.commitStatus = 'committed'
      } catch (err) {
        item.commitStatus = 'failed'
        item.error = err instanceof Error ? err.message : String(err || '提交失败')
      } finally {
        touchItems()
      }
    }
    const okCount = ready.filter((item) => item.commitStatus === 'committed').length
    const failCount = ready.filter((item) => item.commitStatus === 'failed').length
    await deps.addAndSaveMessage(
      `[对接] 审核提交完成：成功 ${okCount} 个${failCount ? `，失败 ${failCount} 个` : ''}。`,
      failCount ? 'ai' : 'ai',
    )
  }

  function clearOfficeDockingReview() {
    officeDockingPanelOpen.value = false
    officeDockingReviewItems.value = []
  }

  return {
    officeDockingInputRef,
    officeDockingProcessing,
    officeDockingPanelOpen,
    officeDockingReviewItems,
    officeDockingPendingCount,
    triggerOfficeDocking,
    onOfficeDockingFileChange,
    toggleOfficeDockingTarget,
    confirmOfficeDockingReview,
    clearOfficeDockingReview,
  }
}
