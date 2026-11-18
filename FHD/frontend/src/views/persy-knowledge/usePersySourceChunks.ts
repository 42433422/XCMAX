import { ref, type Ref } from 'vue'
import { knowledgeBaseApi, type KnowledgeBaseChunk, type KnowledgeBaseDocument } from '@/api/knowledgeBase'
import { errorText } from '@/composables/persyKnowledgeFormatters'

const PAGE_SIZE = 50

/** 资料来源分块预览：按文档顺序分页读取，供命中测试与解析结果核对。 */
export function usePersySourceChunks(options: { activeDatasetId: Ref<string> }) {
  const documentId = ref('')
  const documentLabel = ref('')
  const chunks = ref<KnowledgeBaseChunk[]>([])
  const total = ref(0)
  const loading = ref(false)
  const loadingMore = ref(false)
  const error = ref('')

  function reset(): void {
    documentId.value = ''
    documentLabel.value = ''
    chunks.value = []
    total.value = 0
    loading.value = false
    loadingMore.value = false
    error.value = ''
  }

  async function open(doc: KnowledgeBaseDocument): Promise<void> {
    const id = String(doc.document_id || '')
    reset()
    if (!id) {
      error.value = '该资料缺少文档 ID，无法预览分块'
      return
    }
    documentId.value = id
    documentLabel.value = String(doc.source || id)
    loading.value = true
    try {
      const result = await knowledgeBaseApi.documentChunks(options.activeDatasetId.value, id, {
        limit: PAGE_SIZE,
      })
      if (!result.success) throw new Error(result.message || '加载分块失败')
      chunks.value = Array.isArray(result.chunks) ? result.chunks : []
      total.value = Number(result.total || chunks.value.length)
    } catch (cause) {
      error.value = `加载分块失败：${errorText(cause)}`
    } finally {
      loading.value = false
    }
  }

  async function loadMore(): Promise<void> {
    if (loading.value || loadingMore.value || !documentId.value) return
    if (chunks.value.length >= total.value) return
    loadingMore.value = true
    try {
      const result = await knowledgeBaseApi.documentChunks(
        options.activeDatasetId.value,
        documentId.value,
        { offset: chunks.value.length, limit: PAGE_SIZE },
      )
      if (result.success) {
        chunks.value = [...chunks.value, ...(Array.isArray(result.chunks) ? result.chunks : [])]
        total.value = Number(result.total || total.value)
      }
    } catch {
      // 保留已加载内容，用户可再次点击重试。
    } finally {
      loadingMore.value = false
    }
  }

  return {
    documentId,
    documentLabel,
    chunks,
    total,
    loading,
    loadingMore,
    error,
    open,
    reset,
    loadMore,
  }
}
