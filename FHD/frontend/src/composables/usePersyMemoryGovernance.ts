import { computed, ref, type Ref } from 'vue'
import { knowledgeBaseApi, type KnowledgeGraphNode, type PersyMemoryRecord, type PersyMemoryValue } from '@/api/knowledgeBase'
import { buildMemoryStatement, errorText, memoryValue } from '@/composables/persyKnowledgeFormatters'

export function usePersyMemoryGovernance(options: {
  activeDatasetId: Ref<string>
  memories: Ref<PersyMemoryRecord[]>
  selectedNode: Ref<KnowledgeGraphNode | null>
  refreshMemories: () => Promise<void>
  refreshGraph: () => Promise<void>
  selectMemory: (memory: PersyMemoryRecord) => void
  setIngestMessage: (message: string) => void
}) {
  const { activeDatasetId, memories, selectedNode, refreshMemories, refreshGraph, selectMemory, setIngestMessage } = options

  const mutatingMemory = ref(false)
  const memoryEditing = ref(false)
  const memoryMessage = ref('')
  const memoryDraftSubject = ref('')
  const memoryDraftPredicate = ref('')
  const memoryDraftObject = ref('')

  const selectedMemory = computed(() => {
    const memoryId = String(selectedNode.value?.metadata?.memory_id || '')
    return memories.value.find((memory) => memory.memory_id === memoryId) || null
  })
  const orderedMemories = computed(() =>
    [...memories.value].sort((left, right) => {
      if (left.status !== right.status) return left.status === 'pending' ? -1 : 1
      return Number(right.strength || 0) - Number(left.strength || 0)
    }),
  )
  const pendingMemoryCount = computed(() => memories.value.filter((memory) => memory.status === 'pending').length)
  const activeMemoryCount = computed(() => memories.value.filter((memory) => memory.status === 'active').length)

  function startMemoryEdit(memory: PersyMemoryRecord): void {
    const value = memoryValue(memory)
    memoryDraftSubject.value = String(value.subject || '').trim()
    memoryDraftPredicate.value = String(value.predicate || '').trim()
    memoryDraftObject.value = String(value.object || '').trim()
    memoryMessage.value = ''
    memoryEditing.value = true
  }

  function cancelMemoryEdit(): void {
    memoryEditing.value = false
  }

  async function refreshAfterMemoryMutation(memoryId: string, message: string): Promise<void> {
    await Promise.all([refreshMemories(), refreshGraph()])
    const next = memories.value.find((memory) => memory.memory_id === memoryId)
    if (next) selectMemory(next)
    memoryEditing.value = false
    memoryMessage.value = message
    setIngestMessage(message)
  }

  async function confirmMemory(memory: PersyMemoryRecord): Promise<void> {
    if (mutatingMemory.value) return
    mutatingMemory.value = true
    memoryMessage.value = ''
    try {
      const result = await knowledgeBaseApi.confirmMemory(activeDatasetId.value, memory.memory_id)
      if (!result.success) throw new Error(result.message || '确认记忆失败')
      await refreshAfterMemoryMutation(memory.memory_id, '记忆已确认并进入召回范围')
    } catch (error) {
      memoryMessage.value = errorText(error)
    } finally {
      mutatingMemory.value = false
    }
  }

  async function rejectMemory(memory: PersyMemoryRecord): Promise<void> {
    if (mutatingMemory.value) return
    mutatingMemory.value = true
    memoryMessage.value = ''
    try {
      const result = await knowledgeBaseApi.rejectMemory(activeDatasetId.value, memory.memory_id, 'user_rejected_from_persy')
      if (!result.success) throw new Error(result.message || '忽略记忆失败')
      await refreshAfterMemoryMutation(memory.memory_id, '候选记忆已忽略')
    } catch (error) {
      memoryMessage.value = errorText(error)
    } finally {
      mutatingMemory.value = false
    }
  }

  async function saveMemoryEdit(): Promise<void> {
    const memory = selectedMemory.value
    const subject = memoryDraftSubject.value.trim()
    const predicate = memoryDraftPredicate.value.trim()
    const object = memoryDraftObject.value.trim()
    if (!memory || !subject || !predicate || !object || mutatingMemory.value) return
    mutatingMemory.value = true
    memoryMessage.value = ''
    try {
      const previous = memoryValue(memory)
      const value: PersyMemoryValue = {
        ...previous,
        subject,
        predicate,
        object,
        statement: buildMemoryStatement(subject, predicate, object),
        entities: [
          {
            name: subject,
            type: String(previous.entities?.[0]?.type || 'concept'),
            role: 'subject',
          },
          { name: object, type: String(previous.entities?.[1]?.type || 'concept'), role: 'object' },
        ],
      }
      const result = await knowledgeBaseApi.updateMemory(activeDatasetId.value, memory.memory_id, {
        key: `${subject}.${predicate}`,
        value,
        reason: 'user_corrected_from_persy',
      })
      if (!result.success) throw new Error(result.message || '纠正记忆失败')
      await refreshAfterMemoryMutation(memory.memory_id, '记忆已纠正')
    } catch (error) {
      memoryMessage.value = errorText(error)
    } finally {
      mutatingMemory.value = false
    }
  }

  async function deleteMemory(memory: PersyMemoryRecord): Promise<void> {
    if (mutatingMemory.value || !window.confirm(`删除记忆“${memory.statement}”？`)) return
    mutatingMemory.value = true
    memoryMessage.value = ''
    try {
      const result = await knowledgeBaseApi.deleteMemory(activeDatasetId.value, memory.memory_id, 'user_deleted_from_persy')
      if (!result.success) throw new Error(result.message || '删除记忆失败')
      await refreshAfterMemoryMutation(memory.memory_id, '记忆已删除')
    } catch (error) {
      memoryMessage.value = errorText(error)
    } finally {
      mutatingMemory.value = false
    }
  }

  return {
    mutatingMemory,
    memoryEditing,
    memoryMessage,
    memoryDraftSubject,
    memoryDraftPredicate,
    memoryDraftObject,
    selectedMemory,
    orderedMemories,
    pendingMemoryCount,
    activeMemoryCount,
    startMemoryEdit,
    cancelMemoryEdit,
    confirmMemory,
    rejectMemory,
    saveMemoryEdit,
    deleteMemory,
  }
}
