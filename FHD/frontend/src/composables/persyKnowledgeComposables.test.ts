import { computed, ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { KnowledgeGraphNode, PersyMemoryRecord } from '@/api/knowledgeBase'
import { usePersyKnowledgeData } from './usePersyKnowledgeData'
import { usePersyMemoryGovernance } from './usePersyMemoryGovernance'
import { usePersyRecallQuery } from './usePersyRecallQuery'

const mocks = vi.hoisted(() => ({
  confirmMemory: vi.fn(),
  rejectMemory: vi.fn(),
  updateMemory: vi.fn(),
  deleteMemory: vi.fn(),
  omniscient: vi.fn(),
  status: vi.fn(),
  graph: vi.fn(),
  memories: vi.fn(),
  rebuildIndex: vi.fn(),
}))

vi.mock('@/api/knowledgeBase', () => ({
  PERSY_KNOWLEDGE_DATASET_ID: 'persy-knowledge',
  normalizeKnowledgeDatasetId: (value?: string) => value?.trim() || 'persy-knowledge',
  knowledgeBaseApi: mocks,
}))

vi.mock('@/utils/adminConsoleUrl', () => ({
  isAdminConsoleSpa: () => true,
}))

function memory(memoryId: string, status: 'pending' | 'active', strength: number) {
  return {
    memory_id: memoryId,
    memory_type: 'entity',
    statement: `${memoryId} statement`,
    status,
    scope: 'user',
    strength,
    value: {
      subject: '客户',
      predicate: '偏好',
      object: '周五交付',
      entities: [{ name: '客户', type: 'party', role: 'subject' }],
    },
  } satisfies PersyMemoryRecord
}

describe('Persy knowledge composables', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    for (const action of [
      mocks.confirmMemory,
      mocks.rejectMemory,
      mocks.updateMemory,
      mocks.deleteMemory,
      mocks.rebuildIndex,
    ]) {
      action.mockResolvedValue({ success: true })
    }
  })

  it('governs pending memories through confirm, reject, edit, and delete', async () => {
    const pending = memory('m-pending', 'pending', 0.4)
    const active = memory('m-active', 'active', 0.9)
    const memories = ref<PersyMemoryRecord[]>([active, pending])
    const selectedNode = ref<KnowledgeGraphNode | null>({
      id: 'memory:m-pending',
      label: 'pending',
      type: 'memory',
      metadata: { memory_id: pending.memory_id },
    })
    const selectMemory = vi.fn()
    const setIngestMessage = vi.fn()
    const governance = usePersyMemoryGovernance({
      activeDatasetId: ref('persy-knowledge'),
      memories,
      selectedNode,
      refreshMemories: vi.fn().mockResolvedValue(undefined),
      refreshGraph: vi.fn().mockResolvedValue(undefined),
      selectMemory,
      setIngestMessage,
    })

    expect(governance.selectedMemory.value?.memory_id).toBe(pending.memory_id)
    expect(governance.orderedMemories.value[0]?.memory_id).toBe(pending.memory_id)
    expect(governance.pendingMemoryCount.value).toBe(1)
    expect(governance.activeMemoryCount.value).toBe(1)

    governance.startMemoryEdit(pending)
    expect(governance.memoryEditing.value).toBe(true)
    governance.cancelMemoryEdit()
    expect(governance.memoryEditing.value).toBe(false)

    await governance.confirmMemory(pending)
    await governance.rejectMemory(pending)
    governance.startMemoryEdit(pending)
    governance.memoryDraftObject.value = '下周一交付'
    await governance.saveMemoryEdit()

    vi.spyOn(window, 'confirm').mockReturnValueOnce(true)
    await governance.deleteMemory(pending)

    expect(mocks.confirmMemory).toHaveBeenCalledWith('persy-knowledge', 'm-pending')
    expect(mocks.rejectMemory).toHaveBeenCalledWith(
      'persy-knowledge',
      'm-pending',
      'user_rejected_from_persy',
    )
    expect(mocks.updateMemory).toHaveBeenCalledWith(
      'persy-knowledge',
      'm-pending',
      expect.objectContaining({ reason: 'user_corrected_from_persy' }),
    )
    expect(mocks.deleteMemory).toHaveBeenCalledWith(
      'persy-knowledge',
      'm-pending',
      'user_deleted_from_persy',
    )
    expect(selectMemory).toHaveBeenCalled()
    expect(setIngestMessage).toHaveBeenLastCalledWith('记忆已删除')
  })

  it('resets an existing recall without querying the server', () => {
    const recall = usePersyRecallQuery({
      activeDatasetId: ref('persy-knowledge'),
      adminOmniscient: computed(() => false),
      omniscientQueryEnabled: ref(false),
      refreshMemories: vi.fn().mockResolvedValue(undefined),
      refreshGraph: vi.fn().mockResolvedValue(undefined),
      onRecallCommitted: vi.fn(),
    })
    recall.lastQuery.value = '客户偏好'
    recall.answerText.value = '周五交付'
    recall.resultChunks.value = [{ source: 'memory', text: '周五交付' }]
    expect(recall.recallState.value?.query).toBe('客户偏好')

    recall.resetRecall()

    expect(recall.recallState.value).toBeNull()
    expect(recall.answerText.value).toBe('')
    expect(recall.resultChunks.value).toEqual([])
  })

  it('applies a dataset and rebuilds its active index', async () => {
    mocks.omniscient.mockResolvedValue({
      success: true,
      document_count: 1,
      datasets: {
        'tenant-space': { document_count: 1 },
        'persy-knowledge': { document_count: 1 },
      },
    })
    mocks.status.mockResolvedValue({
      success: true,
      dataset_id: 'tenant-space',
      document_count: 1,
      chunk_count: 1,
      documents: [],
    })
    mocks.graph.mockResolvedValue({
      success: true,
      dataset_id: 'tenant-space',
      nodes: [
        { id: 'root', label: 'root', type: 'core' },
        { id: 'source', label: 'source', type: 'source' },
      ],
      edges: [],
    })
    mocks.memories.mockResolvedValue({ success: true, memories: [] })

    const data = usePersyKnowledgeData({ viewMode: ref('graph') })
    data.datasetIdInput.value = ' tenant-space '
    await data.applyDataset()

    expect(data.activeDatasetId.value).toBe('tenant-space')
    expect(mocks.status).toHaveBeenCalledWith('tenant-space', { includeDocuments: false })
    expect(mocks.graph).toHaveBeenCalledWith('tenant-space')

    await data.rebuildActiveIndex()

    expect(mocks.rebuildIndex).toHaveBeenCalledWith('tenant-space')
    expect(data.rebuildingIndex.value).toBe(false)
  })
})
