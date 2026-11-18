import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PERSY_KNOWLEDGE_DATASET_ID, knowledgeBaseApi, normalizeKnowledgeDatasetId } from './knowledgeBase'

const mocks = vi.hoisted(() => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
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

function streamResponse(chunks: Array<string | Uint8Array>): Response {
  const encoder = new TextEncoder()
  return new Response(new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(typeof chunk === 'string' ? encoder.encode(chunk) : chunk)
      controller.close()
    },
  }), { headers: { 'Content-Type': 'text/event-stream' } })
}

describe('knowledgeBaseApi', () => {
  beforeEach(() => {
    mocks.api.get.mockReset().mockResolvedValue({ success: true })
    mocks.api.post.mockReset().mockResolvedValue({ success: true })
    mocks.api.put.mockReset().mockResolvedValue({ success: true })
    mocks.api.patch.mockReset().mockResolvedValue({ success: true })
    mocks.api.delete.mockReset().mockResolvedValue({ success: true })
    mocks.primeCsrfCookie.mockReset().mockResolvedValue(undefined)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    document.cookie = 'csrf_token=; Max-Age=0; Path=/'
  })

  it.each([
    ['runtime health', () => knowledgeBaseApi.health(), '/api/knowledge/v1/health'],
    ['dataset catalog', () => knowledgeBaseApi.listDatasets(), '/api/knowledge/v1/datasets'],
    ['omniscient overview', () => knowledgeBaseApi.omniscient(), '/api/knowledge/v1/omniscient'],
  ] as const)('returns the %s response from its read-only route', async (_name, request, route) => {
    const response = { success: true, dataset_count: 2 }
    mocks.api.get.mockResolvedValueOnce(response)
    await expect(request()).resolves.toBe(response)
    expect(mocks.api.get).toHaveBeenCalledWith(route)
    expect(mocks.primeCsrfCookie).not.toHaveBeenCalled()
  })

  it.each([undefined, 12])('waits for CSRF before an omniscient query with topK=%s', async (topK) => {
    let finishPrime!: () => void
    mocks.primeCsrfCookie.mockReturnValueOnce(new Promise<void>((resolve) => { finishPrime = resolve }))
    const pending = knowledgeBaseApi.omniscientQuery({ query: '退款流程', topK })
    expect(mocks.api.post).not.toHaveBeenCalled()
    finishPrime()
    await pending
    expect(mocks.api.post).toHaveBeenCalledWith('/api/knowledge/v1/omniscient/query', {
      query: '退款流程', top_k: topK ?? 8, include_citations: true,
    })
  })

  it('preserves dataset, tenant and version boundaries in maintenance requests', async () => {
    const dataset = ' team / docs '
    const prefix = '/api/knowledge/v1/datasets/team%20%2F%20docs'
    await knowledgeBaseApi.diffVersions(dataset, { leftVersion: 'v1', rightVersion: 'v2', tenantId: 'tenant7' })
    await knowledgeBaseApi.rollbackVersion(dataset, { version: 'v1', tenantId: 'tenant7' })
    await knowledgeBaseApi.rebuildIndex(dataset)
    expect(mocks.primeCsrfCookie).toHaveBeenCalledTimes(3)
    expect(mocks.api.post.mock.calls).toEqual([
      [`${prefix}/versions/diff`, { left_version: 'v1', right_version: 'v2', tenant_id: 'tenant7' }],
      [`${prefix}/versions/rollback`, { version: 'v1', tenant_id: 'tenant7' }],
      [`${prefix}/index/rebuild`, { tenant_id: '' }],
    ])
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

  it('submits answer feedback and reads the summary', async () => {
    await knowledgeBaseApi.submitFeedback({
      datasetId: 'office-docking',
      rating: 'down',
      query: '退款流程',
      answer: '未命中',
      citations: [{ source: '退款.md', chunk_index: 1, score: 0.4 }],
    })
    await knowledgeBaseApi.feedbackSummary('office-docking', 999)

    expect(mocks.primeCsrfCookie).toHaveBeenCalledTimes(1)
    expect(mocks.api.post).toHaveBeenCalledWith('/api/knowledge/v1/datasets/office-docking/feedback', {
      rating: 'down',
      query: '退款流程',
      answer: '未命中',
      comment: '',
      citations: [{ source: '退款.md', chunk_index: 1, score: 0.4 }],
    })
    expect(mocks.api.get).toHaveBeenCalledWith(
      '/api/knowledge/v1/datasets/office-docking/feedback?limit=100',
    )
  })

  it('manages external read-only dataset keys', async () => {
    await knowledgeBaseApi.listApiKeys('office-docking')
    await knowledgeBaseApi.createApiKey('office-docking', '网站')
    await knowledgeBaseApi.revokeApiKey('office-docking', 'key / 1')

    expect(mocks.api.get).toHaveBeenCalledWith(
      '/api/knowledge/v1/datasets/office-docking/api-keys',
    )
    expect(mocks.primeCsrfCookie).toHaveBeenCalledTimes(2)
    expect(mocks.api.post).toHaveBeenCalledWith(
      '/api/knowledge/v1/datasets/office-docking/api-keys',
      { label: '网站' },
    )
    expect(mocks.api.delete).toHaveBeenCalledWith(
      '/api/knowledge/v1/datasets/office-docking/api-keys/key%20%2F%201',
    )
  })

  it('exports and imports a dataset snapshot', async () => {
    await knowledgeBaseApi.exportDataset('office-docking')
    await knowledgeBaseApi.importDataset('office-docking', { documents: [], chunks: [] }, true)

    expect(mocks.api.get).toHaveBeenCalledWith(
      '/api/knowledge/v1/datasets/office-docking/export',
    )
    expect(mocks.primeCsrfCookie).toHaveBeenCalledTimes(1)
    expect(mocks.api.post).toHaveBeenCalledWith(
      '/api/knowledge/v1/datasets/office-docking/import',
      { payload: { documents: [], chunks: [] }, overwrite: true },
    )
  })

  it('lists and clears unanswered question gaps', async () => {
    await knowledgeBaseApi.queryGaps('office-docking', 999)
    await knowledgeBaseApi.clearQueryGaps('office-docking')

    expect(mocks.api.get).toHaveBeenCalledWith(
      '/api/knowledge/v1/datasets/office-docking/query-gaps?limit=100',
    )
    expect(mocks.primeCsrfCookie).toHaveBeenCalledTimes(1)
    expect(mocks.api.delete).toHaveBeenCalledWith(
      '/api/knowledge/v1/datasets/office-docking/query-gaps',
    )
  })

  it('loads and saves dataset synonyms', async () => {
    await knowledgeBaseApi.synonyms('office-docking')
    await knowledgeBaseApi.saveSynonyms('office-docking', { 退款: ['退货'] })

    expect(mocks.api.get).toHaveBeenCalledWith(
      '/api/knowledge/v1/datasets/office-docking/synonyms',
    )
    expect(mocks.primeCsrfCookie).toHaveBeenCalledTimes(1)
    expect(mocks.api.put).toHaveBeenCalledWith(
      '/api/knowledge/v1/datasets/office-docking/synonyms',
      { synonyms: { 退款: ['退货'] } },
    )
  })

  it('loads, saves and clears dataset question answer pairs', async () => {
    await knowledgeBaseApi.qaPairs('office-docking')
    await knowledgeBaseApi.saveQaPairs('office-docking', '退款多久到账？\t1-3 个工作日')
    await knowledgeBaseApi.clearQaPairs('office-docking')

    expect(mocks.api.get).toHaveBeenCalledWith(
      '/api/knowledge/v1/datasets/office-docking/qa-pairs',
    )
    expect(mocks.primeCsrfCookie).toHaveBeenCalledTimes(2)
    expect(mocks.api.put).toHaveBeenCalledWith(
      '/api/knowledge/v1/datasets/office-docking/qa-pairs',
      { pairs: '退款多久到账？\t1-3 个工作日', replace: true },
    )
    expect(mocks.api.delete).toHaveBeenCalledWith(
      '/api/knowledge/v1/datasets/office-docking/qa-pairs',
    )
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

  it('decodes fragmented UTF-8 and a final SSE block while carrying CSRF, scope and cancellation', async () => {
    document.cookie = 'csrf_token=tenant%2Fguard; Path=/'
    const text = '\n\n: keepalive\n\ndata: {malformed\n\nevent: delta\ndata: {"text":"退款"}\n\nevent: done\ndata: {"answer":"退款流程"}'
    const chunks = Array.from(new TextEncoder().encode(text), (byte) => Uint8Array.of(byte))
    const fetchMock = vi.fn().mockResolvedValue(streamResponse(chunks))
    vi.stubGlobal('fetch', fetchMock)
    const onDelta = vi.fn()
    const onDone = vi.fn()
    const controller = new AbortController()
    await knowledgeBaseApi.queryStream({
      datasetId: ' team / docs ', query: '退款流程', topK: 9, includeAnswer: false,
      tenantId: 'tenant7', version: 'v2', metadataFilter: { department: 'sales' },
      rerank: true, retrievalMode: 'vector', expandSection: true, mmrLambda: 0.4,
    }, { onDelta, onDone }, controller.signal)
    expect(onDelta.mock.calls).toEqual([['退款']])
    expect(onDone.mock.calls).toEqual([[{ answer: '退款流程' }]])
    expect(mocks.primeCsrfCookie).toHaveBeenCalledOnce()
    const [url, options] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/knowledge/v1/datasets/team%20%2F%20docs/query/stream')
    expect(options).toMatchObject({
      method: 'POST', credentials: 'include', signal: controller.signal,
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': 'tenant/guard' },
    })
    expect(JSON.parse(options.body)).toEqual({
      query: '退款流程', top_k: 9, include_answer: false, tenant_id: 'tenant7', version: 'v2',
      metadata_filter: { department: 'sales' }, rerank: true, retrieval_mode: 'vector',
      expand_section: true, mmr_lambda: 0.4,
    })
  })

  it.each([503, 200])('rejects an HTTP %s response without a readable stream', async (status) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status })))
    const onDone = vi.fn()
    await expect(knowledgeBaseApi.queryStream({ query: '退款' }, { onDone }))
      .rejects.toThrow(`stream failed: ${status}`)
    expect(onDone).not.toHaveBeenCalled()
  })

  it.each([
    ['{"message":"来源不可用"}', '来源不可用'],
    ['{}', 'stream error'],
  ])('propagates a stream error %s without reporting later completion', async (data, message) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamResponse([
      `event: error\ndata: ${data}\n\nevent: done\ndata: {"answer":"ignored"}\n\n`,
    ])))
    const onDone = vi.fn()
    await expect(knowledgeBaseApi.queryStream({ query: '退款' }, { onDone })).rejects.toThrow(message)
    expect(onDone).not.toHaveBeenCalled()
  })

  it.each(['', 'event: delta\ndata: {"text":"partial"}\n\n'])('rejects a stream ending before done: %s', async (text) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamResponse([text])))
    const onDelta = vi.fn()
    const onDone = vi.fn()
    await expect(knowledgeBaseApi.queryStream({ query: '退款' }, { onDelta, onDone }))
      .rejects.toThrow('stream ended before done')
    expect(onDelta.mock.calls).toEqual(text ? [['partial']] : [])
    expect(onDone).not.toHaveBeenCalled()
  })

  it('propagates a reader failure without converting it into successful completion', async () => {
    const failure = new Error('connection interrupted')
    const body = new ReadableStream<Uint8Array>({ start(controller) { controller.error(failure) } })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(body)))
    const onDone = vi.fn()
    await expect(knowledgeBaseApi.queryStream({ query: '退款' }, { onDone })).rejects.toBe(failure)
    expect(onDone).not.toHaveBeenCalled()
  })

  it('does not start a stream request when CSRF preparation fails', async () => {
    const failure = new Error('CSRF unavailable')
    mocks.primeCsrfCookie.mockRejectedValueOnce(failure)
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    await expect(knowledgeBaseApi.queryStream({ query: '退款' })).rejects.toBe(failure)
    expect(fetchMock).not.toHaveBeenCalled()
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

  it('encodes memory filters and enforces the lower page bound', async () => {
    await knowledgeBaseApi.memories('team / docs', { status: 'pending', memoryType: 'user / decision', limit: -5 })
    const url = new URL(mocks.api.get.mock.calls[0][0], 'https://app.example.test')
    expect(url.pathname).toBe('/api/knowledge/v1/datasets/team%20%2F%20docs/memories')
    expect(Object.fromEntries(url.searchParams)).toEqual({ status: 'pending', memory_type: 'user / decision', limit: '1' })
  })

  it('preserves a memory rejection reason and propagates authorization failure', async () => {
    const failure = new Error('permission denied')
    mocks.api.post.mockRejectedValueOnce(failure)
    await expect(knowledgeBaseApi.rejectMemory('team / docs', 'mem / 1', 'incorrect recipient'))
      .rejects.toBe(failure)
    expect(mocks.primeCsrfCookie).toHaveBeenCalledOnce()
    expect(mocks.api.post).toHaveBeenCalledWith(
      '/api/knowledge/v1/datasets/team%20%2F%20docs/memories/mem%20%2F%201/reject',
      { reason: 'incorrect recipient' },
    )
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
