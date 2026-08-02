import { computed, ref, type Ref } from 'vue'
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'
import {
  PERSY_KNOWLEDGE_DATASET_ID,
  knowledgeBaseApi,
  normalizeKnowledgeDatasetId,
  type KnowledgeBaseDocument,
  type KnowledgeBaseStatus,
  type KnowledgeGraphNode,
  type KnowledgeGraphResponse,
  type KnowledgeOmniscientOverview,
  type PersyMemoryRecord,
} from '@/api/knowledgeBase'
import { errorText } from '@/composables/persyKnowledgeFormatters'

export type PersyKnowledgeViewMode = 'graph' | 'memories' | 'cards' | 'sources'

export function usePersyKnowledgeData(options: { viewMode: Ref<PersyKnowledgeViewMode> }) {
  const { viewMode } = options

  const activeDatasetId = ref(PERSY_KNOWLEDGE_DATASET_ID)
  const datasetIdInput = ref(PERSY_KNOWLEDGE_DATASET_ID)
  const adminOmniscient = computed(() => isAdminConsoleSpa())
  const omniscient = ref<KnowledgeOmniscientOverview | null>(null)
  const rebuildingIndex = ref(false)
  const omniscientQueryEnabled = ref(true)
  const status = ref<KnowledgeBaseStatus | null>(null)
  const graph = ref<KnowledgeGraphResponse | null>(null)
  const memories = ref<PersyMemoryRecord[]>([])
  const selectedNode = ref<KnowledgeGraphNode | null>(null)
  const loadingStatus = ref(false)
  const loadingGraph = ref(false)
  const loadingMemories = ref(false)
  const pageError = ref('')

  const datasetOptions = computed(() => {
    const map = omniscient.value?.datasets || {}
    const rows = Object.entries(map).map(([id, item]) => ({
      id,
      label: `${id} · ${Number(item?.document_count || 0)} 文档`,
      docs: Number(item?.document_count || 0),
    }))
    rows.sort((a, b) => b.docs - a.docs || a.id.localeCompare(b.id))
    if (!rows.some((row) => row.id === PERSY_KNOWLEDGE_DATASET_ID)) {
      rows.unshift({
        id: PERSY_KNOWLEDGE_DATASET_ID,
        label: `${PERSY_KNOWLEDGE_DATASET_ID} · 0 文档`,
        docs: 0,
      })
    }
    return rows
  })

  const documentCount = computed(() => status.value?.document_count ?? 0)
  const chunkCount = computed(() => status.value?.chunk_count ?? 0)
  const documents = computed<KnowledgeBaseDocument[]>(() => status.value?.documents ?? [])
  const graphNodeCount = computed(
    () => graph.value?.nodes.filter((node) => node.type !== 'core').length ?? 0,
  )
  const graphEdgeCount = computed(
    () => graph.value?.stats?.edge_count ?? graph.value?.edges.length ?? 0,
  )
  const semanticAvailable = computed(
    () =>
      status.value?.index?.semantic_embedding_available === true ||
      omniscient.value?.semantic_embedding_available === true ||
      omniscient.value?.embedder_available === true,
  )
  const retrievalModeText = computed(() =>
    semanticAvailable.value ? '语义召回' : '关键词召回',
  )
  const knowledgeNodes = computed(() =>
    (graph.value?.nodes || []).filter((node) => node.type !== 'core'),
  )

  const omniscientHint = computed(() => {
    if (!adminOmniscient.value || !omniscient.value) return ''
    const persyDocs = Number(
      omniscient.value.datasets?.[PERSY_KNOWLEDGE_DATASET_ID]?.document_count || 0,
    )
    const total = Number(omniscient.value.document_count || 0)
    const activeExpected = Number(
      omniscient.value.datasets?.[activeDatasetId.value]?.document_count || 0,
    )
    if (total <= 0) return '全库仍空：请导入文档或等待员工/对话入库'
    if (persyDocs <= 0 && activeDatasetId.value === PERSY_KNOWLEDGE_DATASET_ID) {
      return `Persy 空间为空，已推荐查看 ${omniscient.value.recommended_dataset_id || '存量空间'}（全库 ${total} 文档）`
    }
    if (
      activeExpected > 0 &&
      documentCount.value <= 0 &&
      !loadingStatus.value &&
      !loadingGraph.value
    ) {
      return `当前空间全库计 ${activeExpected} 文档，但图谱未加载到内容：请点刷新，或切换空间后再切回`
    }
    return ''
  })

  let refreshEpoch = 0

  async function refreshStatus(
    expectedDatasetId?: string,
    epoch?: number,
    refreshOptions: { includeDocuments?: boolean } = {},
  ): Promise<void> {
    const datasetId = expectedDatasetId || activeDatasetId.value
    const token = epoch ?? refreshEpoch
    const includeDocuments =
      refreshOptions.includeDocuments === true || viewMode.value === 'sources'
    loadingStatus.value = true
    try {
      const next = await knowledgeBaseApi.status(datasetId, { includeDocuments })
      if (token !== refreshEpoch || datasetId !== activeDatasetId.value) return
      status.value = next
    } finally {
      if (token === refreshEpoch) loadingStatus.value = false
    }
  }

  async function refreshGraph(expectedDatasetId?: string, epoch?: number): Promise<void> {
    const datasetId = expectedDatasetId || activeDatasetId.value
    const token = epoch ?? refreshEpoch
    loadingGraph.value = true
    try {
      const nextGraph = await knowledgeBaseApi.graph(datasetId)
      if (token !== refreshEpoch || datasetId !== activeDatasetId.value) return
      if (!nextGraph.success) throw new Error(nextGraph.message || '知识图谱加载失败')
      graph.value = nextGraph
      const selectedId = selectedNode.value?.id
      selectedNode.value =
        nextGraph.nodes.find((node) => node.id === selectedId) ||
        nextGraph.nodes.find((node) => node.type === 'core') ||
        null
    } finally {
      if (token === refreshEpoch) loadingGraph.value = false
    }
  }

  async function refreshMemories(expectedDatasetId?: string, epoch?: number): Promise<void> {
    const datasetId = expectedDatasetId || activeDatasetId.value
    const token = epoch ?? refreshEpoch
    if (datasetId !== PERSY_KNOWLEDGE_DATASET_ID) {
      if (token === refreshEpoch && datasetId === activeDatasetId.value) memories.value = []
      return
    }
    loadingMemories.value = true
    try {
      const result = await knowledgeBaseApi.memories(datasetId, { limit: 1000 })
      if (token !== refreshEpoch || datasetId !== activeDatasetId.value) return
      if (!result.success) throw new Error(result.message || '记忆加载失败')
      memories.value = (Array.isArray(result.memories) ? result.memories : []).filter((memory) =>
        ['pending', 'active'].includes(memory.status),
      )
    } finally {
      if (token === refreshEpoch) loadingMemories.value = false
    }
  }

  async function loadOmniscientOverview(): Promise<boolean> {
    if (!adminOmniscient.value) {
      omniscient.value = null
      return false
    }
    try {
      const overview = await knowledgeBaseApi.omniscient()
      omniscient.value = overview
      const recommended = normalizeKnowledgeDatasetId(overview.recommended_dataset_id)
      const persyDocs = Number(
        overview.datasets?.[PERSY_KNOWLEDGE_DATASET_ID]?.document_count || 0,
      )
      if (
        persyDocs <= 0 &&
        recommended &&
        recommended !== activeDatasetId.value &&
        Number(overview.datasets?.[recommended]?.document_count || 0) > 0
      ) {
        activeDatasetId.value = recommended
        datasetIdInput.value = recommended
        return true
      }
    } catch (error) {
      console.warn('[PersyKnowledge] omniscient overview failed', error)
    }
    return false
  }

  async function rebuildActiveIndex(): Promise<void> {
    if (!adminOmniscient.value || rebuildingIndex.value) return
    rebuildingIndex.value = true
    try {
      await knowledgeBaseApi.rebuildIndex(activeDatasetId.value)
      await refreshAll()
    } catch (error) {
      console.warn('[PersyKnowledge] rebuild failed', error)
    } finally {
      rebuildingIndex.value = false
    }
  }

  async function refreshDatasetViews(epoch: number, datasetId: string): Promise<void> {
    const results = await Promise.allSettled([
      refreshStatus(datasetId, epoch),
      refreshGraph(datasetId, epoch),
      refreshMemories(datasetId, epoch),
    ])
    if (epoch !== refreshEpoch) return
    const rejected = results.find((result) => result.status === 'rejected')
    if (rejected?.status === 'rejected') pageError.value = errorText(rejected.reason)
  }

  async function refreshAll(): Promise<void> {
    pageError.value = ''
    const epoch = ++refreshEpoch
    await loadOmniscientOverview()
    if (epoch !== refreshEpoch) return
    const datasetId = activeDatasetId.value
    await refreshDatasetViews(epoch, datasetId)
    if (epoch !== refreshEpoch || !adminOmniscient.value || !omniscient.value) return
    const expected = Number(omniscient.value.datasets?.[datasetId]?.document_count || 0)
    const loadedDocs = Number(status.value?.document_count || 0)
    const loadedNodes = Number(
      graph.value?.nodes?.filter((node) => node.type !== 'core' && node.type !== 'onboarding')
        .length || 0,
    )
    if (
      expected > 0 &&
      (loadedDocs <= 0 || loadedNodes <= 0) &&
      datasetId === activeDatasetId.value
    ) {
      await refreshDatasetViews(epoch, datasetId)
    }
  }

  async function applyDataset(): Promise<void> {
    activeDatasetId.value = normalizeKnowledgeDatasetId(datasetIdInput.value)
    datasetIdInput.value = activeDatasetId.value
    await refreshAll()
  }

  return {
    activeDatasetId,
    datasetIdInput,
    adminOmniscient,
    omniscient,
    rebuildingIndex,
    omniscientQueryEnabled,
    status,
    graph,
    memories,
    selectedNode,
    loadingStatus,
    loadingGraph,
    loadingMemories,
    pageError,
    datasetOptions,
    documentCount,
    chunkCount,
    documents,
    graphNodeCount,
    graphEdgeCount,
    semanticAvailable,
    retrievalModeText,
    knowledgeNodes,
    omniscientHint,
    refreshStatus,
    refreshGraph,
    refreshMemories,
    refreshAll,
    applyDataset,
    rebuildActiveIndex,
  }
}
