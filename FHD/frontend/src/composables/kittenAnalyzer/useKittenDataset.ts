/**
 * useKittenAnalyzer 拆分：数据文件解析、图表配置与推荐。
 */
import { type Ref } from 'vue'
import type { KittenFieldProfile } from '@/utils/kittenDatasetParser'
import { KITTEN_PHASE, type KittenPhase } from '@/composables/useKittenWorkflowState'
import {
  buildPreviewTextFromData,
  buildRecommendedCharts,
  emptyChartConfig,
  type KittenAnalysisResult,
  type KittenChartConfig,
  type KittenChartRecommendation,
  type KittenDatasetSummary,
} from './kittenAnalyzerShared'

export interface KittenDatasetDeps {
  fileInput: Ref<HTMLInputElement | null>
  datasetSummary: Ref<KittenDatasetSummary | null>
  datasetRows: Ref<Record<string, unknown>[]>
  fieldProfiles: Ref<KittenFieldProfile[]>
  chartConfig: Ref<KittenChartConfig>
  currentResult: Ref<KittenAnalysisResult | null>
  kittenPhase: Ref<KittenPhase>
  isDatasetParsing: Ref<boolean>
  addMessage: (role: 'user' | 'ai', content: string) => void
}

export function useKittenDataset(deps: KittenDatasetDeps) {
  const { fileInput, datasetSummary, datasetRows, fieldProfiles, chartConfig, currentResult, kittenPhase, isDatasetParsing, addMessage } = deps

  let parseDatasetFilePromise: Promise<typeof import('@/utils/kittenDatasetParser')> | null = null

  const loadDatasetParser = async () => {
    if (!parseDatasetFilePromise) parseDatasetFilePromise = import('@/utils/kittenDatasetParser')
    return parseDatasetFilePromise
  }

  const triggerFileUpload = () => {
    fileInput.value?.click()
  }

  const generateDataPreview = (data: { columns: string[]; rows: number }) =>
    `字段：${data.columns.slice(0, 5).join('、')}${data.columns.length > 5 ? '...' : ''}<br>共 ${data.rows} 条记录`

  const setChartConfig = (next: Partial<KittenChartConfig>) => {
    chartConfig.value = {
      ...chartConfig.value,
      ...next,
    }
    const cfg = chartConfig.value
    if (cfg.xField) {
      currentResult.value = {
        id: Date.now(),
        title: '图表分析',
        summary: `${cfg.type} · ${cfg.xField}${cfg.yField ? ` / ${cfg.yField}` : ''} · ${cfg.aggregate}`,
        chart: true,
        type: 'chart',
        kind: 'datasetChart',
      }
      kittenPhase.value = KITTEN_PHASE.delivered
    }
  }

  const applyChartRecommendation = (rec: KittenChartRecommendation) => {
    setChartConfig(rec.config)
  }

  const handleFileSelect = async (e: Event) => {
    const input = e.target as HTMLInputElement
    const file = input.files?.[0]
    if (!file) return

    addMessage('user', `上传文件：${file.name}`)
    isDatasetParsing.value = true
    kittenPhase.value = KITTEN_PHASE.ingesting

    try {
      const { parseDatasetFile } = await loadDatasetParser()
      const data = await parseDatasetFile(file)
      const preview = generateDataPreview(data)
      const fieldNames = Array.isArray(data.columns) ? data.columns.map((c) => String(c)) : []

      datasetSummary.value = {
        name: file.name,
        rows: data.rows,
        columns: fieldNames.length,
        fieldNames,
        previewText: buildPreviewTextFromData(data),
      }
      datasetRows.value = Array.isArray(data.sampleRows) ? data.sampleRows : []
      fieldProfiles.value = Array.isArray(data.fieldProfiles) ? data.fieldProfiles : []
      const firstRecommendation = buildRecommendedCharts(fieldProfiles.value)[0]
      chartConfig.value = firstRecommendation?.config || emptyChartConfig()

      addMessage(
        'ai',
        `文件解析完成！<br>检测到 <strong>${data.rows} 行</strong> 数据，<strong>${fieldNames.length} 个字段</strong><br>${preview}`,
      )

      currentResult.value = {
        id: Date.now(),
        title: '数据概览',
        summary: `${fieldNames.slice(0, 12).join('、')}${fieldNames.length > 12 ? '…' : ''}`,
        chart: Boolean(firstRecommendation),
        type: firstRecommendation ? 'chart' : 'table',
        kind: firstRecommendation ? 'datasetChart' : 'datasetOverview',
      }
      kittenPhase.value = KITTEN_PHASE.schemaReady
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      addMessage('ai', `文件解析失败：${msg}`)
      kittenPhase.value = KITTEN_PHASE.error
    } finally {
      isDatasetParsing.value = false
      input.value = ''
    }
  }

  return {
    triggerFileUpload,
    setChartConfig,
    applyChartRecommendation,
    handleFileSelect,
  }
}
