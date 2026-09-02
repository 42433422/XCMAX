/**
 * Facade：智慧分析工作台装配入口（实现拆分至 kittenAnalyzer/ 子模块，行为与拆分前一致）。
 */
import { ref, computed, nextTick, onMounted } from 'vue'
import { safeJsonRequest } from '@/utils/safeJsonRequest'
import { KITTEN_PHASE, type KittenPhase } from '@/composables/useKittenWorkflowState'
import type { KittenFieldProfile } from '@/utils/kittenDatasetParser'
import {
  KITTEN_WELCOME_HTML,
  MAX_CHAT_MESSAGES,
  buildRecommendedCharts,
  emptyChartConfig,
  extractKittenDocumentPickupUrl,
  htmlToPlainText,
  kittenQuickActions,
  makeKittenUserId,
  pushBounded,
  type KittenAnalysisResult,
  type KittenChartConfig,
  type KittenChatMessage,
  type KittenDatasetSummary,
} from './kittenAnalyzer/kittenAnalyzerShared'
import { useKittenBusinessSnapshot } from './kittenAnalyzer/useKittenBusinessSnapshot'
import { useKittenDataset } from './kittenAnalyzer/useKittenDataset'
import { useKittenChatSend } from './kittenAnalyzer/useKittenChatSend'
import { useKittenExport } from './kittenAnalyzer/useKittenExport'

export { KITTEN_WELCOME_HTML, kittenWorkflowSteps, kittenOrgCards, kittenQuickActions, extractKittenDocumentPickupUrl } from './kittenAnalyzer/kittenAnalyzerShared'
export type {
  KittenDatasetSummary,
  KittenChatMessage,
  KittenAnalysisResult,
  KittenChartType,
  KittenChartAggregate,
  KittenChartConfig,
  KittenChartRecommendation,
} from './kittenAnalyzer/kittenAnalyzerShared'

export function useKittenAnalyzer() {
  const messages = ref<KittenChatMessage[]>([
    {
      role: 'ai',
      content: KITTEN_WELCOME_HTML,
      time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
    },
  ])

  const inputText = ref('')
  const isChatLoading = ref(false)
  /** 流式生成时隐藏底部「正在分析」占位条，改由气泡内逐字更新 */
  const isKittenStreaming = ref(false)
  const isDatasetParsing = ref(false)
  const kittenPhase = ref<KittenPhase>(KITTEN_PHASE.idle)
  const currentResult = ref<KittenAnalysisResult | null>(null)
  const fileInput = ref<HTMLInputElement | null>(null)
  const chatMessagesRef = ref<HTMLElement | null>(null)

  const datasetSummary = ref<KittenDatasetSummary | null>(null)
  const datasetRows = ref<Record<string, unknown>[]>([])
  const fieldProfiles = ref<KittenFieldProfile[]>([])
  const chartConfig = ref<KittenChartConfig>(emptyChartConfig())
  const recommendedCharts = computed(() => buildRecommendedCharts(fieldProfiles.value))
  const kittenIncludeBusinessDb = ref(false)
  const kittenIncludeWebSearch = ref(true)
  const lastWebSearchHits = ref<Array<{ title: string; url: string; snippet: string }>>([])
  const kittenSessionUserId = ref(makeKittenUserId())

  const hasDataset = computed(() => Boolean(datasetSummary.value))

  /** 侧栏「下载本次生成的文档」：从最近一条含取件链接的 AI 气泡读取（不受 summary 截断影响） */
  const lastDocumentPickupUrl = computed(() => {
    const list = messages.value
    for (let i = list.length - 1; i >= 0; i--) {
      const m = list[i]
      if (m.role !== 'ai' || !m.content) continue
      const fromRaw = extractKittenDocumentPickupUrl(m.content)
      if (fromRaw) return fromRaw
      const plain = htmlToPlainText(m.content)
      const fromPlain = extractKittenDocumentPickupUrl(plain)
      if (fromPlain) return fromPlain
    }
    return null
  })

  const datasetFieldPreview = computed(() => {
    const names = datasetSummary.value?.fieldNames
    if (!Array.isArray(names)) return []
    return names.slice(0, 8)
  })

  const loadingStatusText = computed(() => {
    if (isDatasetParsing.value) return '正在解析数据文件...'
    if (isChatLoading.value) return '正在回复…'
    return ''
  })

  const scrollChatToBottom = () => {
    nextTick(() => {
      const el = chatMessagesRef.value
      if (el) el.scrollTop = el.scrollHeight
    })
  }

  const addMessage = (role: 'user' | 'ai', content: string) => {
    pushBounded(
      messages,
      {
        role,
        content,
        time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
      },
      MAX_CHAT_MESSAGES,
    )
    scrollChatToBottom()
  }

  const snapshot = useKittenBusinessSnapshot({ kittenIncludeBusinessDb })
  const dataset = useKittenDataset({
    fileInput,
    datasetSummary,
    datasetRows,
    fieldProfiles,
    chartConfig,
    currentResult,
    kittenPhase,
    isDatasetParsing,
    addMessage,
  })
  const chatSend = useKittenChatSend({
    messages,
    inputText,
    isChatLoading,
    isKittenStreaming,
    isDatasetParsing,
    kittenPhase,
    currentResult,
    kittenSessionUserId,
    kittenIncludeBusinessDb,
    kittenIncludeWebSearch,
    datasetSummary,
    lastWebSearchHits,
    addMessage,
    scrollChatToBottom,
  })
  const exporter = useKittenExport({
    messages,
    currentResult,
    kittenPhase,
    datasetSummary,
    chartConfig,
    lastWebSearchHits,
    addMessage,
  })

  const resetSession = async () => {
    const uid = kittenSessionUserId.value
    if (uid) {
      const clearResult = await safeJsonRequest('/api/ai/context/clear', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: uid }),
      })
      if (!clearResult.ok || (clearResult.data as { success?: boolean })?.success === false) {
        console.warn('清理会话上下文失败:', clearResult.message || (clearResult.data as { message?: string })?.message || 'unknown')
      }
    }
    kittenSessionUserId.value = makeKittenUserId()
    messages.value = [
      {
        role: 'ai',
        content: KITTEN_WELCOME_HTML,
        time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
      },
    ]
    inputText.value = ''
    isChatLoading.value = false
    isDatasetParsing.value = false
    kittenPhase.value = KITTEN_PHASE.idle
    currentResult.value = null
    datasetSummary.value = null
    datasetRows.value = []
    fieldProfiles.value = []
    chartConfig.value = emptyChartConfig()
    kittenIncludeBusinessDb.value = false
    kittenIncludeWebSearch.value = false
    snapshot.resetKittenSnapshotCache()
    lastWebSearchHits.value = []
    scrollChatToBottom()
  }

  const clearResult = () => {
    currentResult.value = null
    kittenPhase.value = hasDataset.value ? KITTEN_PHASE.schemaReady : KITTEN_PHASE.idle
  }

  onMounted(() => {
    scrollChatToBottom()
  })

  return {
    messages,
    inputText,
    isChatLoading,
    isKittenStreaming,
    isDatasetParsing,
    kittenPhase,
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
    kittenDbStatsHint: snapshot.kittenDbStatsHint,
    lastWebSearchHits,
    kittenQuickActions,
    datasetFieldPreview,
    lastDocumentPickupUrl,
    loadingStatusText,
    resetSession,
    onKittenBusinessDbToggle: snapshot.onKittenBusinessDbToggle,
    triggerFileUpload: dataset.triggerFileUpload,
    handleFileSelect: dataset.handleFileSelect,
    setChartConfig: dataset.setChartConfig,
    applyChartRecommendation: dataset.applyChartRecommendation,
    sendMessage: chatSend.sendMessage,
    sendQuickAction: chatSend.sendQuickAction,
    exportResult: exporter.exportResult,
    exportDocx: exporter.exportDocx,
    isDocGenLoading: exporter.isDocGenLoading,
    generateAiOfficeDocument: exporter.generateAiOfficeDocument,
    runFinancialBrief: exporter.runFinancialBrief,
    clearResult,
    handleInputKeydown: chatSend.handleInputKeydown,
  }
}
