import { beforeEach, describe, expect, it, vi } from 'vitest'
import { PERSY_KNOWLEDGE_DATASET_ID, knowledgeBaseApi, normalizeKnowledgeDatasetId } from './knowledgeBase'

const mocks = vi.hoisted(() => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
  primeCsrfCookie: vi.fn(),
}))

vi.mock('./core', () => ({
  api: mocks.api,
  primeCsrfCookie: mocks.primeCsrfCookie,
  buildFullApiUrl: (path: string) => path,
}))

describe('knowledgeBaseApi', () => {
  beforeEach(() => {
    mocks.api.get.mockReset().mockResolvedValue({ success: true })
    mocks.api.post.mockReset().mockResolvedValue({ success: true })
    mocks.api.patch.mockReset().mockResolvedValue({ success: true })
    mocks.api.delete.mockReset().mockResolvedValue({ success: true })
    mocks.primeCsrfCookie.mockReset().mockResolvedValue(undefined)
  })

  it('normalizes blank dataset id to Persy default', () => {
    expect(normalizeKnowledgeDatasetId('')).toBe(PERSY_KNOWLEDGE_DATASET_ID)
    expect(normalizeKnowledgeDatasetId(' team-docs ')).toBe('team-docs')
  })

  it('loads default Persy dataset status', async () => {
    await knowledgeBaseApi.status()

    expect(mocks.api.get).toHaveBeenCalledWith(`/api/knowledge/v1/datasets/${PERSY_KNOWLEDGE_DATASET_ID}/status`)
  })

  it('loads the bounded Persy knowledge graph', async () => {
    await knowledgeBaseApi.graph('team brain', 999)

    expect(mocks.api.get).toHaveBeenCalledWith('/api/knowledge/v1/datasets/team%20brain/graph?limit=160')
  })

  it('can skip document rows on status for lighter HUD loads', async () => {
    await knowledgeBaseApi.status('persy-knowledge', { includeDocuments: false })

    expect(mocks.api.get).toHaveBeenCalledWith(`/api/knowledge/v1/datasets/${PERSY_KNOWLEDGE_DATASET_ID}/status?include_documents=false`)
  })

  it('loads a bounded page of one document chunks', async () => {
    await knowledgeBaseApi.documentChunks('team docs', 'doc 1', { offset: -3, limit: 999 })

    expect(mocks.api.get).toHaveBeenCalledWith(
      '/api/knowledge/v1/datasets/team%20docs/documents/doc%201/chunks?offset=0&limit=200',
    )
  })

  it('ingests text through dataset document route', async () => {
    await knowledgeBaseApi.ingestDocument({
      datasetId: 'persy docs',
      source: 'policy',
      text: 'Use citations.',
      metadata: { scope: 'persy' },
    })

    expect(mocks.primeCsrfCookie).toHaveBeenCalledTimes(1)
    expect(mocks.api.post).toHaveBeenCalledWith('/api/knowledge/v1/datasets/persy%20docs/documents', {
      source: 'policy',
      text: 'Use citations.',
      document_id: '',
      tenant_id: '',
      version: '',
      version_label: '',
      chunk_strategy: 'semantic',
      metadata: { scope: 'persy' },
    })
  })

  it('uploads a document through multipart dataset route', async () => {
    const file = new File(['policy body'], 'policy.txt', { type: 'text/plain' })

    await knowledgeBaseApi.uploadDocument({
      datasetId: 'persy-knowledge',
      source: 'Policy',
      file,
    })

    expect(mocks.primeCsrfCookie).toHaveBeenCalledTimes(1)
    expect(mocks.api.post).toHaveBeenCalledTimes(1)
    const [path, form] = mocks.api.post.mock.calls[0]
    expect(path).toBe('/api/knowledge/v1/datasets/persy-knowledge/documents/upload')
    expect(form).toBeInstanceOf(FormData)
    expect((form as FormData).get('file')).toBe(file)
    expect((form as FormData).get('source')).toBe('Policy')
    expect((form as FormData).get('chunk_strategy')).toBe('semantic')
  })

  it('queries dataset with answer and rerank options', async () => {
    await knowledgeBaseApi.query({
      datasetId: 'persy-knowledge',
      query: 'How should Persy answer?',
      topK: 8,
      rerank: true,
    })

    expect(mocks.primeCsrfCookie).toHaveBeenCalledTimes(1)
    expect(mocks.api.post).toHaveBeenCalledWith('/api/knowledge/v1/datasets/persy-knowledge/query', {
      query: 'How should Persy answer?',
      top_k: 8,
      include_answer: true,
      tenant_id: '',
      version: '',
      metadata_filter: {},
      rerank: true,
      retrieval_mode: 'hybrid',
      expand_section: false,
      mmr_lambda: 0,
    })
  })

  it('maps retrieval mode, section expansion and mmr lambda', async () => {
    await knowledgeBaseApi.query({
      datasetId: 'office-docking',
      query: '退款流程',
      retrievalMode: 'keyword',
      expandSection: true,
      mmrLambda: 2,
    })

    expect(mocks.api.post).toHaveBeenCalledWith('/api/knowledge/v1/datasets/office-docking/query', {
      query: '退款流程',
      top_k: 5,
      include_answer: true,
      tenant_id: '',
      version: '',
      metadata_filter: {},
      rerank: false,
      retrieval_mode: 'keyword',
      expand_section: true,
      mmr_lambda: 1,
    })
  })

  it('queries multiple datasets with deduplicated ids', async () => {
    await knowledgeBaseApi.multiQuery({
      datasetIds: ['office-docking', ' persy-knowledge ', 'office-docking', ''],
      query: '退款流程',
      topK: 6,
      rerank: true,
    })

    expect(mocks.primeCsrfCookie).toHaveBeenCalledTimes(1)
    expect(mocks.api.post).toHaveBeenCalledWith('/api/knowledge/v1/datasets/multi-query', {
      query: '退款流程',
      top_k: 6,
      include_answer: true,
      tenant_id: '',
      version: '',
      metadata_filter: {},
      rerank: true,
      retrieval_mode: 'hybrid',
      expand_section: false,
      mmr_lambda: 0,
      dataset_ids: ['office-docking', 'persy-knowledge'],
    })
  })

  it('parses SSE knowledge query events', async () => {
    const encoder = new TextEncoder()
    const chunks = [
      'event: meta\ndata: {"success":true,"chunks":[],"grounding":0.9}\n\n',
      'event: delta\ndata: {"text":"退款"}\n\n',
      'event: done\ndata: {"answer":"退款流程","citations":[]}\n\n',
    ]
    const body = new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
        controller.close()
      },
    })
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, body })
    vi.stubGlobal('fetch', fetchMock)
    const events: string[] = []

    await knowledgeBaseApi.queryStream(
      { datasetId: 'kb', query: '退款流程' },
      {
        onMeta: () => events.push('meta'),
        onDelta: (text) => events.push(`delta:${text}`),
        onDone: (data) => events.push(`done:${String(data.answer)}`),
      },
    )

    expect(events).toEqual(['meta', 'delta:退款', 'done:退款流程'])
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/knowledge/v1/datasets/kb/query/stream',
      expect.objectContaining({ method: 'POST', credentials: 'include' }),
    )
    vi.unstubAllGlobals()
  })

  it('loads and queries governed Persy memories', async () => {
    await knowledgeBaseApi.memories('persy-knowledge', { status: 'pending', limit: 5000 })
    await knowledgeBaseApi.queryMemories({
      datasetId: 'persy-knowledge',
      query: '北辰科技负责人',
      topK: 30,
    })

    expect(mocks.api.get).toHaveBeenCalledWith('/api/knowledge/v1/datasets/persy-knowledge/memories?status=pending&limit=1000')
    expect(mocks.api.post).toHaveBeenCalledWith('/api/knowledge/v1/datasets/persy-knowledge/memories/query', {
      query: '北辰科技负责人',
      top_k: 20,
      reinforce: true,
    })
  })

  it('mutates memories and deletes documents through CSRF-protected routes', async () => {
    await knowledgeBaseApi.confirmMemory('persy-knowledge', 'mem / 1')
    await knowledgeBaseApi.updateMemory('persy-knowledge', 'mem / 1', {
      key: '客户.负责人',
    })
    await knowledgeBaseApi.deleteMemory('persy-knowledge', 'mem / 1', 'outdated')
    await knowledgeBaseApi.deleteDocument('persy-knowledge', 'doc / 1')

    expect(mocks.primeCsrfCookie).toHaveBeenCalledTimes(4)
    expect(mocks.api.post).toHaveBeenCalledWith('/api/knowledge/v1/datasets/persy-knowledge/memories/mem%20%2F%201/confirm', {})
    expect(mocks.api.patch).toHaveBeenCalledWith('/api/knowledge/v1/datasets/persy-knowledge/memories/mem%20%2F%201', {
      key: '客户.负责人',
    })
    expect(mocks.api.delete).toHaveBeenCalledWith('/api/knowledge/v1/datasets/persy-knowledge/memories/mem%20%2F%201?reason=outdated')
    expect(mocks.api.delete).toHaveBeenCalledWith('/api/knowledge/v1/datasets/persy-knowledge/documents/doc%20%2F%201')
  })
})
