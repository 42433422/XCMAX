/**
 * useKittenAnalyzer 拆分：报告导出（后端/本地回退）、AI 文档生成与财务简报。
 */
import { ref, type Ref } from 'vue'
import { kittenApi } from '@/api/kitten'
import { downloadBlob, getFilenameFromDisposition } from '@/utils'
import { safeJsonRequest } from '@/utils/safeJsonRequest'
import { appAlert } from '@/utils/appDialog'
import { openDocumentPreviewFromBlob } from '@/state/documentPreviewPip'
import { KITTEN_PHASE, type KittenPhase } from '@/composables/useKittenWorkflowState'
import {
  assertKittenFileBlob,
  formatExportTimestamp,
  htmlToPlainText,
  textToHtml,
  type KittenAnalysisResult,
  type KittenChartConfig,
  type KittenChatMessage,
  type KittenDatasetSummary,
} from './kittenAnalyzerShared'

export interface KittenExportDeps {
  messages: Ref<KittenChatMessage[]>
  currentResult: Ref<KittenAnalysisResult | null>
  kittenPhase: Ref<KittenPhase>
  datasetSummary: Ref<KittenDatasetSummary | null>
  chartConfig: Ref<KittenChartConfig>
  lastWebSearchHits: Ref<Array<{ title: string; url: string; snippet: string }>>
  addMessage: (role: 'user' | 'ai', content: string) => void
}

export function useKittenExport(deps: KittenExportDeps) {
  const { messages, currentResult, kittenPhase, datasetSummary, chartConfig, lastWebSearchHits, addMessage } = deps

  let xlsxLibPromise: Promise<typeof import('xlsx')> | null = null

  const loadXlsx = async () => {
    if (!xlsxLibPromise) xlsxLibPromise = import('xlsx')
    return xlsxLibPromise
  }

  const buildReportWorkbook = (XLSX: typeof import('xlsx')) => {
    const workbook = XLSX.utils.book_new()
    const now = new Date()
    const ds = datasetSummary.value
    const result = currentResult.value
    const summaryRows: (string | number)[][] = [
      ['报告标题', result?.title || 'AI 分析'],
      ['报告时间', now.toLocaleString('zh-CN')],
      ['分析阶段', kittenPhase.value],
      ['摘要', result?.summary || ''],
      ['来源', '智慧分析工作台'],
    ]
    if (ds) {
      summaryRows.push(['数据文件', ds.name || ''])
      summaryRows.push(['数据规模', `${ds.rows || 0} 行 / ${ds.columns || 0} 列`])
    }
    XLSX.utils.book_append_sheet(workbook, XLSX.utils.aoa_to_sheet(summaryRows), '报告摘要')

    const messageRows = messages.value.map((msg, idx) => ({
      序号: idx + 1,
      角色: msg.role === 'ai' ? 'AI' : '用户',
      时间: msg.time || '',
      内容: htmlToPlainText(msg.content),
    }))
    XLSX.utils.book_append_sheet(
      workbook,
      XLSX.utils.json_to_sheet(messageRows.length ? messageRows : [{ 序号: 1, 角色: '系统', 时间: '', 内容: '暂无对话记录' }]),
      '对话记录',
    )

    if (ds) {
      const dataRows: (string | number)[][] = [
        ['文件名', ds.name || ''],
        ['总行数', ds.rows || 0],
        ['总列数', ds.columns || 0],
        ['字段列表', Array.isArray(ds.fieldNames) ? ds.fieldNames.join('、') : ''],
        ['预览文本', ds.previewText || ''],
      ]
      XLSX.utils.book_append_sheet(workbook, XLSX.utils.aoa_to_sheet(dataRows), '数据摘要')
    }

    if (chartConfig.value.xField) {
      const chartRows: (string | number)[][] = [
        ['图表类型', chartConfig.value.type],
        ['X 字段', chartConfig.value.xField],
        ['Y 字段', chartConfig.value.yField || '记录数'],
        ['分组字段', chartConfig.value.groupField || ''],
        ['聚合方式', chartConfig.value.aggregate],
      ]
      XLSX.utils.book_append_sheet(workbook, XLSX.utils.aoa_to_sheet(chartRows), '图表配置')
    }

    return workbook
  }

  const exportReportViaBackend = async () => {
    const payload = {
      phase: kittenPhase.value,
      result: currentResult.value || {},
      dataset: datasetSummary.value || null,
      chart: chartConfig.value.xField ? chartConfig.value : undefined,
      messages: messages.value || [],
      industry: localStorage.getItem('currentIndustry') || '通用行业',
      web_search_results: lastWebSearchHits.value.length ? lastWebSearchHits.value : undefined,
    }
    const resp = await kittenApi.exportReport(payload)
    const blob = await resp.blob()
    await assertKittenFileBlob(resp, blob, 'Excel 导出')
    const filename = getFilenameFromDisposition(resp.headers.get('content-disposition'), `智慧分析报告_${formatExportTimestamp()}.xlsx`)
    downloadBlob(blob, filename)
  }

  const exportDocxViaBackend = async () => {
    const payload = {
      phase: kittenPhase.value,
      result: currentResult.value || {},
      dataset: datasetSummary.value || null,
      chart: chartConfig.value.xField ? chartConfig.value : undefined,
      messages: messages.value || [],
      industry: localStorage.getItem('currentIndustry') || '通用行业',
      web_search_results: lastWebSearchHits.value.length ? lastWebSearchHits.value : undefined,
    }
    const resp = await kittenApi.exportReportDocx(payload)
    const blob = await resp.blob()
    await assertKittenFileBlob(resp, blob, 'Word 导出')
    const filename = getFilenameFromDisposition(resp.headers.get('content-disposition'), `智慧分析报告_${formatExportTimestamp()}.docx`)
    downloadBlob(blob, filename)
  }

  const isDocGenLoading = ref(false)

  const generateAiOfficeDocument = async (prompt: string, format: 'docx' | 'xlsx') => {
    const p = (prompt || '').trim()
    if (!p) {
      await appAlert('请先描述要生成的文档内容')
      return
    }
    isDocGenLoading.value = true
    try {
      const resp = await kittenApi.generateDocument({ prompt: p, format })
      const blob = await resp.blob()
      await assertKittenFileBlob(resp, blob, format === 'xlsx' ? '表格生成' : '文档生成')
      const filename = getFilenameFromDisposition(
        resp.headers.get('content-disposition'),
        format === 'xlsx' ? `生成表格_${formatExportTimestamp()}.xlsx` : `生成文档_${formatExportTimestamp()}.docx`,
      )
      openDocumentPreviewFromBlob(blob, filename, p)
      downloadBlob(blob, filename)
      addMessage('ai', `已生成并下载：<strong>${filename}</strong><br>（内容由模型起草，正式签署前请法务审核）`)
    } catch (err) {
      const errMessage = err instanceof Error ? err.message : '未知错误'
      await appAlert(`文档生成失败：${errMessage}`)
    } finally {
      isDocGenLoading.value = false
    }
  }

  const runFinancialBrief = async () => {
    const r = await safeJsonRequest<{
      success?: boolean
      message?: string
      data?: Record<string, unknown>
      analysis_id?: string
    }>('/api/ai/kitten/financial/report', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        metadata: {
          source: 'kitten-workbench',
          industry: localStorage.getItem('currentIndustry') || '',
        },
      }),
    })
    if (!r.ok || r.data?.success === false) {
      const msg = (r.data as { message?: string })?.message || r.message || '财务简报生成失败'
      addMessage('ai', textToHtml(msg))
      return
    }
    const data = r.data?.data
    let summary = ''
    if (data && typeof data === 'object') {
      try {
        summary = JSON.stringify(data, null, 2)
      } catch {
        summary = String(data)
      }
    } else {
      summary = (r.data as { message?: string })?.message || '财务简报已生成'
    }
    const clipped = summary.length > 8000 ? `${summary.slice(0, 8000)}…` : summary
    addMessage('ai', textToHtml(`【财务简报】\n${clipped}`))
    kittenPhase.value = KITTEN_PHASE.delivered
  }

  const exportResult = async () => {
    if (!currentResult.value) return
    try {
      await exportReportViaBackend()
    } catch (backendErr) {
      console.warn('后端导出失败，回退前端本地导出：', backendErr)
      try {
        const XLSX = await loadXlsx()
        const workbook = buildReportWorkbook(XLSX)
        const workbookArray = XLSX.write(workbook, { bookType: 'xlsx', type: 'array' })
        const blob = new Blob([workbookArray as unknown as BlobPart], {
          type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
        const fileName = `智慧分析报告_${formatExportTimestamp()}.xlsx`
        downloadBlob(blob, fileName)
      } catch (err) {
        console.error('导出报告失败:', err)
        const errMessage = err instanceof Error ? err.message : '未知错误'
        await appAlert(`导出失败：${errMessage}`)
      }
    }
  }

  const exportDocx = async () => {
    if (!currentResult.value) return
    try {
      await exportDocxViaBackend()
    } catch (err) {
      console.error('Word 导出失败:', err)
      const errMessage = err instanceof Error ? err.message : '未知错误'
      await appAlert(`Word 导出失败：${errMessage}`)
    }
  }

  return {
    isDocGenLoading,
    generateAiOfficeDocument,
    runFinancialBrief,
    exportResult,
    exportDocx,
  }
}
