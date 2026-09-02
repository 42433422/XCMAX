import { describe, it, expect, vi, beforeEach } from 'vitest'
import { nextTick } from 'vue'
import { usePersyKnowledgeInteractions } from './usePersyKnowledgeInteractions'
import { knowledgeBaseApi } from '@/api/knowledgeBase'
import type { KnowledgeBaseDocument, KnowledgeGraphNode, PersyMemoryRecord } from '@/api/knowledgeBase'
import type { PersyKnowledgeUiState } from './usePersyKnowledgeUiState'

vi.mock('@/api/knowledgeBase', () => ({
  knowledgeBaseApi: { deleteDocument: vi.fn() },
}))

function ref<T>(initial: T) {
  return { value: initial }
}

function makeDeps() {
  const ui = {
    viewMode: ref<'graph' | 'memories'>('graph'),
    ingestMessage: ref(''),
    deletingDocumentId: ref(''),
    graphComponent: ref<{ resetView: () => void } | null>(null),
    queryInput: ref<{ focus: () => void } | null>(null),
    importDrawer: ref<{ open: (mode: 'file' | 'text') => void } | null>(null),
    mobileInspectorOpen: ref(false),
  } as unknown as PersyKnowledgeUiState

  const graph = ref<{ nodes: KnowledgeGraphNode[] } | null>(null)
  const selectedNode = ref<KnowledgeGraphNode | null>(null)

  const deps = {
    ui,
    data: {
      activeDatasetId: ref('ds-1'),
      graph,
      selectedNode,
      pageError: ref(''),
      refreshAll: vi.fn(async () => {}),
      applyDataset: vi.fn(async () => {}),
    },
    recall: { queryText: ref(''), resetRecall: vi.fn() },
    governance: { orderedMemories: ref<PersyMemoryRecord[]>([]) },
    selectNode: vi.fn(),
    selectMemory: vi.fn(),
  }

  return { ui, deps, graph, selectedNode }
}

const doc: KnowledgeBaseDocument = { document_id: 'doc-1', source: '手册.pdf' } as KnowledgeBaseDocument

describe('usePersyKnowledgeInteractions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
  })

  it('applyDataset 先重置召回再切换数据集', async () => {
    const { deps } = makeDeps()
    const interactions = usePersyKnowledgeInteractions(deps)
    await interactions.applyDataset()
    expect(deps.recall.resetRecall).toHaveBeenCalledTimes(1)
    expect(deps.data.applyDataset).toHaveBeenCalledTimes(1)
  })

  it('openImport 清空 ingestMessage 并打开抽屉', () => {
    const { ui, deps } = makeDeps()
    ui.ingestMessage.value = '旧消息'
    const open = vi.fn()
    ;(ui.importDrawer as unknown as { value: { open: (m: 'file') => void } }).value = { open }
    const interactions = usePersyKnowledgeInteractions(deps)
    interactions.openImport('file')
    expect(ui.ingestMessage.value).toBe('')
    expect(open).toHaveBeenCalledWith('file')
  })

  it('openImport 在抽屉缺失时不抛错', () => {
    const { ui, deps } = makeDeps()
    ;(ui.importDrawer as unknown as { value: null }).value = null
    const interactions = usePersyKnowledgeInteractions(deps)
    expect(() => interactions.openImport('text')).not.toThrow()
  })

  it('handleIngested 设置消息、切回 graph 视图并刷新', async () => {
    const { ui, deps } = makeDeps()
    const interactions = usePersyKnowledgeInteractions(deps)
    await interactions.handleIngested('导入完成')
    expect(ui.ingestMessage.value).toBe('导入完成')
    expect(ui.viewMode.value).toBe('graph')
    expect(deps.data.refreshAll).toHaveBeenCalledTimes(1)
  })

  it('openPendingMemories 切到 memories 视图并选中首个 pending 记忆', () => {
    const { deps } = makeDeps()
    const pending = { id: 'm1', status: 'pending' } as PersyMemoryRecord
    const other = { id: 'm2', status: 'active' } as PersyMemoryRecord
    ;(deps.governance.orderedMemories as unknown as { value: PersyMemoryRecord[] }).value = [other, pending]
    const interactions = usePersyKnowledgeInteractions(deps)
    interactions.openPendingMemories()
    expect(deps.ui.viewMode.value).toBe('memories')
    expect(deps.selectMemory).toHaveBeenCalledWith(pending)
  })

  it('openPendingMemories 无 pending 记忆时不选中', () => {
    const { deps } = makeDeps()
    const interactions = usePersyKnowledgeInteractions(deps)
    interactions.openPendingMemories()
    expect(deps.selectMemory).not.toHaveBeenCalled()
  })

  it('selectDocument 按 document_id 定位 source 节点', () => {
    const { deps, graph } = makeDeps()
    const node = { id: 'n1', label: '手册', type: 'source', document_id: 'doc-1' } as KnowledgeGraphNode
    ;(graph as unknown as { value: { nodes: KnowledgeGraphNode[] } | null }).value = { nodes: [node] }
    const interactions = usePersyKnowledgeInteractions(deps)
    interactions.selectDocument(doc)
    expect(deps.selectNode).toHaveBeenCalledWith(node)
  })

  it('selectDocument 找不到节点时不选中', () => {
    const { deps, graph } = makeDeps()
    ;(graph as unknown as { value: { nodes: KnowledgeGraphNode[] } | null }).value = { nodes: [] }
    const interactions = usePersyKnowledgeInteractions(deps)
    interactions.selectDocument(doc)
    expect(deps.selectNode).not.toHaveBeenCalled()
  })

  it('deleteDocument 确认后调用 API 并刷新；取消时不调用', async () => {
    const { ui, deps } = makeDeps()
    const interactions = usePersyKnowledgeInteractions(deps)
    ;(knowledgeBaseApi.deleteDocument as ReturnType<typeof vi.fn>).mockResolvedValue({ success: true })

    await interactions.deleteDocument(doc)
    expect(knowledgeBaseApi.deleteDocument).toHaveBeenCalledWith('ds-1', 'doc-1')
    expect(ui.ingestMessage.value).toBe('资料及其知识节点已删除')
    expect(deps.data.refreshAll).toHaveBeenCalledTimes(1)
    expect(ui.deletingDocumentId.value).toBe('')

    vi.mocked(window.confirm).mockReturnValue(false)
    await interactions.deleteDocument(doc)
    expect(knowledgeBaseApi.deleteDocument).toHaveBeenCalledTimes(1)
  })

  it('deleteDocument 空 document_id 直接返回', async () => {
    const { deps } = makeDeps()
    const interactions = usePersyKnowledgeInteractions(deps)
    await interactions.deleteDocument({ document_id: '' } as KnowledgeBaseDocument)
    expect(knowledgeBaseApi.deleteDocument).not.toHaveBeenCalled()
  })

  it('deleteDocument API 失败时写入 pageError', async () => {
    const { ui, deps } = makeDeps()
    const interactions = usePersyKnowledgeInteractions(deps)
    ;(knowledgeBaseApi.deleteDocument as ReturnType<typeof vi.fn>).mockResolvedValue({ success: false, message: '删除失败' })
    await interactions.deleteDocument(doc)
    expect((deps.data.pageError as unknown as { value: string }).value).toBe('删除失败')
    expect(ui.deletingDocumentId.value).toBe('')
  })

  it('askAboutSelectedNode 填充 queryText 并聚焦输入框', async () => {
    const { ui, deps, selectedNode } = makeDeps()
    const focus = vi.fn()
    ;(ui.queryInput as unknown as { value: { focus: () => void } | null }).value = { focus }
    ;(selectedNode as unknown as { value: KnowledgeGraphNode | null }).value = { id: 'n1', label: '退费政策', type: 'concept' }
    const interactions = usePersyKnowledgeInteractions(deps)
    interactions.askAboutSelectedNode()
    expect(deps.recall.queryText.value).toContain('退费政策')
    expect(ui.mobileInspectorOpen.value).toBe(false)
    await nextTick()
    expect(focus).toHaveBeenCalledTimes(1)
  })

  it('askAboutSelectedNode 无选中节点时不动作', () => {
    const { deps } = makeDeps()
    const interactions = usePersyKnowledgeInteractions(deps)
    interactions.askAboutSelectedNode()
    expect(deps.recall.queryText.value).toBe('')
  })

  it('handleOnboardingAction 分发 upload/paste/chat', async () => {
    const { ui, deps } = makeDeps()
    const open = vi.fn()
    ;(ui.importDrawer as unknown as { value: { open: (m: 'file' | 'text') => void } | null }).value = { open }
    const focus = vi.fn()
    ;(ui.queryInput as unknown as { value: { focus: () => void } | null }).value = { focus }
    const interactions = usePersyKnowledgeInteractions(deps)

    interactions.handleOnboardingAction('upload')
    expect(open).toHaveBeenLastCalledWith('file')
    interactions.handleOnboardingAction('paste')
    expect(open).toHaveBeenLastCalledWith('text')
    interactions.handleOnboardingAction('chat')
    await nextTick()
    expect(focus).toHaveBeenCalled()
  })

  it('resetGraphView 调用图谱组件复位；组件缺失不抛错', () => {
    const { ui, deps } = makeDeps()
    const resetView = vi.fn()
    ;(ui.graphComponent as unknown as { value: { resetView: () => void } | null }).value = { resetView }
    const interactions = usePersyKnowledgeInteractions(deps)
    interactions.resetGraphView()
    expect(resetView).toHaveBeenCalledTimes(1)

    ;(ui.graphComponent as unknown as { value: null }).value = null
    expect(() => interactions.resetGraphView()).not.toThrow()
  })
})
