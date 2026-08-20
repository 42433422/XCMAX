import { computed, ref, type ComputedRef, type Ref } from 'vue'
import { PERSY_KNOWLEDGE_DATASET_ID, knowledgeBaseApi, type KnowledgeBaseChunk } from '@/api/knowledgeBase'
import type { PersyGraphRecall } from '@/components/persy/PersyKnowledgeGraph.vue'
import { errorText, isMemoryChunk, normalizeAnswer } from '@/composables/persyKnowledgeFormatters'

export function usePersyRecallQuery(options: {
  activeDatasetId: Ref<string>
  adminOmniscient: ComputedRef<boolean>
  omniscientQueryEnabled: Ref<boolean>
  refreshMemories: () => Promise<void>
  refreshGraph: () => Promise<void>
  onRecallCommitted: () => void
}) {
  const { activeDatasetId, adminOmniscient, omniscientQueryEnabled, refreshMemories, refreshGraph, onRecallCommitted } = options

  const queryText = ref('')
  const topK = ref(6)
  const rerank = ref(true)
  const querying = ref(false)
  const queryMessage = ref('')
  const queryError = ref('')
  const answerText = ref('')
  const lastQuery = ref('')
  const resultChunks = ref<KnowledgeBaseChunk[]>([])

  const recallState = computed<PersyGraphRecall | null>(() =>
    lastQuery.value
      ? {
          query: lastQuery.value,
          chunks: resultChunks.value,
        }
      : null,
  )

  function resetRecall(): void {
    answerText.value = ''
    lastQuery.value = ''
    resultChunks.value = []
    queryMessage.value = ''
    queryError.value = ''
  }

  async function queryKnowledge(): Promise<void> {
    const query = queryText.value.trim()
    queryError.value = ''
    queryMessage.value = ''
    answerText.value = ''
    resultChunks.value = []
    if (!query) {
      queryError.value = '请输入问题'
      return
    }
    querying.value = true
    try {
      const boundedTopK = Math.max(1, Math.min(Number(topK.value) || 6, 20))
      let knowledge: Awaited<ReturnType<typeof knowledgeBaseApi.query>> | null = null
      let memory: Awaited<ReturnType<typeof knowledgeBaseApi.queryMemories>> | null = null
      let knowledgeFailure: unknown = null
      let memoryFailure: unknown = null
      try {
        knowledge =
          adminOmniscient.value && omniscientQueryEnabled.value
            ? await knowledgeBaseApi.omniscientQuery({
                query,
                topK: boundedTopK,
              })
            : await knowledgeBaseApi.query({
                datasetId: activeDatasetId.value,
                query,
                topK: boundedTopK,
                rerank: rerank.value,
              })
      } catch (error) {
        knowledgeFailure = error
      }
      if (activeDatasetId.value === PERSY_KNOWLEDGE_DATASET_ID && knowledge?.persy_memory === undefined) {
        try {
          memory = await knowledgeBaseApi.queryMemories({
            datasetId: activeDatasetId.value,
            query,
            topK: boundedTopK,
            reinforce: true,
          })
        } catch (error) {
          memoryFailure = error
        }
      }
      const knowledgeChunks = knowledge?.success && Array.isArray(knowledge.chunks) ? knowledge.chunks : []
      const memoryChunks = memory?.success && Array.isArray(memory.chunks) ? memory.chunks : []
      if (!knowledge?.success && !memory?.success) {
        const reason = knowledgeFailure || memoryFailure || knowledge?.message || memory?.message || '检索失败'
        throw new Error(errorText(reason))
      }
      const seen = new Set<string>()
      const mergedChunks = [...memoryChunks, ...knowledgeChunks]
        .sort((left, right) => Number(right.score || 0) - Number(left.score || 0))
        .filter((chunk) => {
          const key = String(chunk.metadata?.memory_id || `${chunk.source}:${chunk.text || ''}`)
          if (seen.has(key)) return false
          seen.add(key)
          return true
        })
        .slice(0, boundedTopK * 2)
      lastQuery.value = query
      resultChunks.value = mergedChunks
      answerText.value = normalizeAnswer(knowledge?.answer, resultChunks.value.length)
      const recalledMemoryCount = mergedChunks.filter((chunk) => isMemoryChunk(chunk)).length
      if (!answerText.value && recalledMemoryCount) {
        answerText.value = `已从长期记忆中召回 ${recalledMemoryCount} 条相关事实。`
      }
      queryMessage.value = resultChunks.value.length ? '' : '未检索到相关知识'
      onRecallCommitted()
      if (recalledMemoryCount) {
        await Promise.allSettled([refreshMemories(), refreshGraph()])
      }
    } catch (error) {
      queryError.value = errorText(error)
    } finally {
      querying.value = false
    }
  }

  return {
    queryText,
    topK,
    rerank,
    querying,
    queryMessage,
    queryError,
    answerText,
    lastQuery,
    resultChunks,
    recallState,
    resetRecall,
    queryKnowledge,
  }
}
