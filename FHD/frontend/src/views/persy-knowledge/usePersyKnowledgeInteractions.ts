import { nextTick } from 'vue'
import { knowledgeBaseApi } from '@/api/knowledgeBase'
import type { KnowledgeBaseDocument, KnowledgeGraphNode, PersyMemoryRecord } from '@/api/knowledgeBase'
import { errorText } from '@/composables/persyKnowledgeFormatters'
import type { usePersyKnowledgeData } from '@/composables/usePersyKnowledgeData'
import type { usePersyRecallQuery } from '@/composables/usePersyRecallQuery'
import type { usePersyMemoryGovernance } from '@/composables/usePersyMemoryGovernance'
import type { PersyKnowledgeUiState } from './usePersyKnowledgeUiState'

type PersyKnowledgeData = ReturnType<typeof usePersyKnowledgeData>
type PersyRecallQuery = ReturnType<typeof usePersyRecallQuery>
type PersyMemoryGovernance = ReturnType<typeof usePersyMemoryGovernance>

export interface PersyKnowledgeInteractionsDeps {
  ui: PersyKnowledgeUiState
  data: Pick<PersyKnowledgeData, 'activeDatasetId' | 'graph' | 'selectedNode' | 'pageError' | 'refreshAll' | 'applyDataset'>
  recall: Pick<PersyRecallQuery, 'queryText' | 'resetRecall'>
  governance: Pick<PersyMemoryGovernance, 'orderedMemories'>
  selectNode: (node: KnowledgeGraphNode) => void
  selectMemory: (memory: PersyMemoryRecord) => void
}

export interface PersyKnowledgeInteractions {
  applyDataset: () => Promise<void>
  openImport: (mode: 'file' | 'text') => void
  handleIngested: (message: string) => Promise<void>
  openPendingMemories: () => void
  selectDocument: (doc: KnowledgeBaseDocument) => void
  deleteDocument: (doc: KnowledgeBaseDocument) => Promise<void>
  askAboutSelectedNode: () => void
  handleOnboardingAction: (action: 'upload' | 'paste' | 'chat') => void
  resetGraphView: () => void
}

/** 交互动作域（由 PersyKnowledgeView.vue 机械切出，行为不变）：导入/删除资料、节点定位、图谱复位等 */
export function usePersyKnowledgeInteractions(deps: PersyKnowledgeInteractionsDeps): PersyKnowledgeInteractions {
  const { ui, data, recall, governance, selectNode, selectMemory } = deps
  const { viewMode, ingestMessage, deletingDocumentId, graphComponent, queryInput, importDrawer } = ui
  const { activeDatasetId, graph, selectedNode, pageError, refreshAll, applyDataset: switchDataset } = data
  const { queryText, resetRecall } = recall
  const { orderedMemories } = governance

  async function applyDataset(): Promise<void> {
    resetRecall()
    await switchDataset()
  }

  function openImport(mode: 'file' | 'text'): void {
    ingestMessage.value = ''
    importDrawer.value?.open(mode)
  }

  async function handleIngested(message: string): Promise<void> {
    ingestMessage.value = message
    viewMode.value = 'graph'
    await refreshAll()
  }

  function openPendingMemories(): void {
    viewMode.value = 'memories'
    const pending = orderedMemories.value.find((memory) => memory.status === 'pending')
    if (pending) selectMemory(pending)
  }

  function selectDocument(doc: KnowledgeBaseDocument): void {
    const node = graph.value?.nodes.find((candidate) => candidate.type === 'source' && candidate.document_id === doc.document_id)
    if (node) selectNode(node)
  }

  async function deleteDocument(doc: KnowledgeBaseDocument): Promise<void> {
    const documentId = String(doc.document_id || '')
    if (!documentId || deletingDocumentId.value || !window.confirm(`删除资料“${doc.source || '未命名资料'}”及其全部知识节点？`)) {
      return
    }
    deletingDocumentId.value = documentId
    ingestMessage.value = ''
    try {
      const result = await knowledgeBaseApi.deleteDocument(activeDatasetId.value, documentId)
      if (!result.success) throw new Error(result.message || '删除资料失败')
      ingestMessage.value = '资料及其知识节点已删除'
      await refreshAll()
    } catch (error) {
      pageError.value = errorText(error)
    } finally {
      deletingDocumentId.value = ''
    }
  }

  function askAboutSelectedNode(): void {
    if (!selectedNode.value) return
    queryText.value = `关于“${selectedNode.value.label}”，请结合已有知识说明关键事实。`
    ui.mobileInspectorOpen.value = false
    nextTick(() => queryInput.value?.focus())
  }

  function handleOnboardingAction(action: 'upload' | 'paste' | 'chat'): void {
    if (action === 'upload') openImport('file')
    if (action === 'paste') openImport('text')
    if (action === 'chat') nextTick(() => queryInput.value?.focus())
  }

  function resetGraphView(): void {
    graphComponent.value?.resetView()
  }

  return {
    applyDataset,
    openImport,
    handleIngested,
    openPendingMemories,
    selectDocument,
    deleteDocument,
    askAboutSelectedNode,
    handleOnboardingAction,
    resetGraphView,
  }
}
