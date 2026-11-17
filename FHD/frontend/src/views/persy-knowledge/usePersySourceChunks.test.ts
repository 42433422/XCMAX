import { beforeEach, describe, expect, it, vi } from 'vitest'
import { usePersySourceChunks } from './usePersySourceChunks'
import { knowledgeBaseApi } from '@/api/knowledgeBase'

vi.mock('@/api/knowledgeBase', () => ({
  knowledgeBaseApi: { documentChunks: vi.fn() },
}))

const documentChunks = vi.mocked(knowledgeBaseApi.documentChunks)

function activeDatasetId() {
  return { value: 'ds-1' }
}

describe('usePersySourceChunks', () => {
  beforeEach(() => {
    documentChunks.mockReset()
  })

  it('loads the first page of chunks for a document', async () => {
    documentChunks.mockResolvedValue({
      success: true,
      total: 3,
      chunks: [
        { text: '第一块', chunk_index: 0 },
        { text: '第二块', chunk_index: 1 },
      ],
    })

    const state = usePersySourceChunks({ activeDatasetId: activeDatasetId() })
    await state.open({ document_id: 'doc-1', source: '退款.md' })

    expect(documentChunks).toHaveBeenCalledWith('ds-1', 'doc-1', { limit: 50 })
    expect(state.documentId.value).toBe('doc-1')
    expect(state.documentLabel.value).toBe('退款.md')
    expect(state.chunks.value).toHaveLength(2)
    expect(state.total.value).toBe(3)
    expect(state.error.value).toBe('')
  })

  it('records an error when the document has no id', async () => {
    const state = usePersySourceChunks({ activeDatasetId: activeDatasetId() })
    await state.open({ source: '无 ID 资料' })

    expect(documentChunks).not.toHaveBeenCalled()
    expect(state.error.value).toContain('缺少文档 ID')
  })

  it('appends the next page without duplicating the first page', async () => {
    documentChunks
      .mockResolvedValueOnce({
        success: true,
        total: 3,
        chunks: [
          { text: '第一块', chunk_index: 0 },
          { text: '第二块', chunk_index: 1 },
        ],
      })
      .mockResolvedValueOnce({
        success: true,
        total: 3,
        chunks: [{ text: '第三块', chunk_index: 2 }],
      })

    const state = usePersySourceChunks({ activeDatasetId: activeDatasetId() })
    await state.open({ document_id: 'doc-1', source: '退款.md' })
    await state.loadMore()

    expect(documentChunks).toHaveBeenLastCalledWith('ds-1', 'doc-1', { offset: 2, limit: 50 })
    expect(state.chunks.value.map((chunk) => chunk.text)).toEqual(['第一块', '第二块', '第三块'])
  })

  it('reports load failures without throwing', async () => {
    documentChunks.mockRejectedValue(new Error('network down'))

    const state = usePersySourceChunks({ activeDatasetId: activeDatasetId() })
    await state.open({ document_id: 'doc-1', source: '退款.md' })

    expect(state.error.value).toContain('加载分块失败')
    expect(state.loading.value).toBe(false)
  })
})
