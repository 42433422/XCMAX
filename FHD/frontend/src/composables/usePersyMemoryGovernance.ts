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
  const memoryDraftSubjectType = ref('concept')
  const memoryDraftObjectType = ref('concept')
  const memoryDraftCardinality = ref<'' | 'one' | 'many'>('')
  const memoryDraftEffectiveFrom = ref('')
  const memoryDraftEffectiveUntil = ref('')
  const memoryEntityTypes = [
    { value: 'person', label: '人物' }, { value: 'organization', label: '组织' },
    { value: 'project', label: '项目' }, { value: 'product', label: '产品' },
    { value: 'place', label: '地点' }, { value: 'concept', label: '未明确类型' },
    { value: 'literal', label: '属性值' }, { value: 'preference', label: '偏好' },
  ]

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
    const subjectEntity = value.entities?.find(entity => entity.role === 'subject') || value.entities?.[0]
    const objectEntity = value.entities?.find(entity => entity.role === 'object') || value.entities?.[1]
    memoryDraftSubjectType.value = String(subjectEntity?.type || 'concept')
    memoryDraftObjectType.value = String(objectEntity?.type || 'concept')
    memoryDraftCardinality.value = value.relation_cardinality || ''
    memoryDraftEffectiveFrom.value = value.relation_validity?.effective_from || ''
    memoryDraftEffectiveUntil.value = value.relation_validity?.effective_until || ''
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
      const previousSubject = previous.entities?.find(entity => entity.role === 'subject') || previous.entities?.[0]
      const previousObject = previous.entities?.find(entity => entity.role === 'object') || previous.entities?.[1]
      const value: PersyMemoryValue = {
        ...previous,
        subject,
        predicate,
        object,
        statement: buildMemoryStatement(subject, predicate, object),
        entities: [
          {
            name: subject,
            type: memoryDraftSubjectType.value,
            role: 'subject',
            ...(previousSubject?.name === subject && previousSubject?.type === memoryDraftSubjectType.value && previousSubject?.entity_id
              ? { entity_id: previousSubject.entity_id } : {}),
          },
          {
            name: object, type: memoryDraftObjectType.value, role: 'object',
            ...(previousObject?.name === object && previousObject?.type === memoryDraftObjectType.value && previousObject?.entity_id
              ? { entity_id: previousObject.entity_id } : {}),
          },
        ],
      }
      delete value.relation_cardinality
      delete value.relation_validity
      if (memoryDraftCardinality.value) value.relation_cardinality = memoryDraftCardinality.value
      if (memoryDraftEffectiveFrom.value || memoryDraftEffectiveUntil.value) {
        value.relation_validity = {
          ...(memoryDraftEffectiveFrom.value ? { effective_from: memoryDraftEffectiveFrom.value } : {}),
          ...(memoryDraftEffectiveUntil.value ? { effective_until: memoryDraftEffectiveUntil.value } : {}),
        }
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
    memoryEntityTypes,
    memoryDraftSubjectType,
    memoryDraftObjectType,
    memoryDraftCardinality,
    memoryDraftEffectiveFrom,
    memoryDraftEffectiveUntil,
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
