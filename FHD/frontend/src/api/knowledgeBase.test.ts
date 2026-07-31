import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  PERSY_KNOWLEDGE_DATASET_ID,
  knowledgeBaseApi,
  normalizeKnowledgeDatasetId,
} from './knowledgeBase'

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

    expect(mocks.api.get).toHaveBeenCalledWith(
      `/api/knowledge/v1/datasets/${PERSY_KNOWLEDGE_DATASET_ID}/status`,
    )
  })

  it('loads the active enterprise tenant directory', async () => {
    await knowledgeBaseApi.tenants()

    expect(mocks.api.get).toHaveBeenCalledWith('/api/rbac/tenants')
  })

  it('loads the bounded Persy knowledge graph', async () => {
    await knowledgeBaseApi.graph('team brain', 999)

    expect(mocks.api.get).toHaveBeenCalledWith(
      '/api/knowledge/v1/datasets/team%20brain/graph?limit=160',
    )
  })

  it('can skip document rows on status for lighter HUD loads', async () => {
    await knowledgeBaseApi.status('persy-knowledge', { includeDocuments: false })

    expect(mocks.api.get).toHaveBeenCalledWith(
      `/api/knowledge/v1/datasets/${PERSY_KNOWLEDGE_DATASET_ID}/status?include_documents=false`,
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
    expect(mocks.api.post).toHaveBeenCalledWith(
      '/api/knowledge/v1/datasets/persy%20docs/documents',
      {
        source: 'policy',
        text: 'Use citations.',
        document_id: '',
        tenant_id: '',
        version: '',
        version_label: '',
        chunk_strategy: 'semantic',
        metadata: { scope: 'persy' },
      },
    )
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
    expect((form as FormData).get('metadata_json')).toBe('{}')
  })

  it('queries dataset with answer and rerank options', async () => {
    await knowledgeBaseApi.query({
      datasetId: 'persy-knowledge',
      query: 'How should Persy answer?',
      topK: 8,
      rerank: true,
    })

    expect(mocks.primeCsrfCookie).toHaveBeenCalledTimes(1)
    expect(mocks.api.post).toHaveBeenCalledWith(
      '/api/knowledge/v1/datasets/persy-knowledge/query',
      {
        query: 'How should Persy answer?',
        top_k: 8,
        include_answer: true,
        tenant_id: '',
        version: '',
        metadata_filter: {},
        rerank: true,
        include_public: true,
      },
    )
  })

  it('scopes status, graph, and queries to an explicit admin tenant', async () => {
    await knowledgeBaseApi.status('persy-knowledge', {
      includeDocuments: true,
      tenantId: 'tenant-a',
    })
    await knowledgeBaseApi.graph('persy-knowledge', 80, { tenantId: 'tenant-a' })
    await knowledgeBaseApi.query({
      datasetId: 'persy-knowledge',
      query: 'private policy',
      tenantId: 'tenant-a',
      includePublic: false,
    })

    expect(mocks.api.get).toHaveBeenCalledWith(
      '/api/knowledge/v1/datasets/persy-knowledge/status?tenant_id=tenant-a',
    )
    expect(mocks.api.get).toHaveBeenCalledWith(
      '/api/knowledge/v1/datasets/persy-knowledge/graph?limit=80&tenant_id=tenant-a',
    )
    expect(mocks.api.post).toHaveBeenCalledWith(
      '/api/knowledge/v1/datasets/persy-knowledge/query',
      expect.objectContaining({
        tenant_id: 'tenant-a',
        include_public: false,
      }),
    )
  })

  it('loads and queries governed Persy memories', async () => {
    await knowledgeBaseApi.memories('persy-knowledge', { status: 'pending', limit: 5000 })
    await knowledgeBaseApi.queryMemories({
      datasetId: 'persy-knowledge',
      query: '北辰科技负责人',
      topK: 30,
    })

    expect(mocks.api.get).toHaveBeenCalledWith(
      '/api/knowledge/v1/datasets/persy-knowledge/memories?status=pending&limit=1000',
    )
    expect(mocks.api.post).toHaveBeenCalledWith(
      '/api/knowledge/v1/datasets/persy-knowledge/memories/query',
      { query: '北辰科技负责人', top_k: 20, reinforce: true },
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
    expect(mocks.api.post).toHaveBeenCalledWith(
      '/api/knowledge/v1/datasets/persy-knowledge/memories/mem%20%2F%201/confirm',
      {},
    )
    expect(mocks.api.patch).toHaveBeenCalledWith(
      '/api/knowledge/v1/datasets/persy-knowledge/memories/mem%20%2F%201',
      { key: '客户.负责人' },
    )
    expect(mocks.api.delete).toHaveBeenCalledWith(
      '/api/knowledge/v1/datasets/persy-knowledge/memories/mem%20%2F%201?reason=outdated',
    )
    expect(mocks.api.delete).toHaveBeenCalledWith(
      '/api/knowledge/v1/datasets/persy-knowledge/documents/doc%20%2F%201',
    )
  })

  it('publishes a public draft through the governed publication route', async () => {
    await knowledgeBaseApi.setDocumentPublication(
      'persy-knowledge',
      'doc / 1',
      'published',
      '内容审核完成',
      'draft',
    )

    expect(mocks.primeCsrfCookie).toHaveBeenCalledTimes(1)
    expect(mocks.api.patch).toHaveBeenCalledWith(
      '/api/knowledge/v1/datasets/persy-knowledge/documents/doc%20%2F%201/publication',
      {
        status: 'published',
        reason: '内容审核完成',
        expected_status: 'draft',
      },
    )
  })

  it('covers health, catalogs, version ops, rebuild, reject, and omniscient query', async () => {
    await knowledgeBaseApi.health()
    await knowledgeBaseApi.listDatasets()
    await knowledgeBaseApi.omniscient()
    await knowledgeBaseApi.omniscientQuery({ query: 'platform issue', topK: 5 })
    await knowledgeBaseApi.diffVersions('persy-knowledge', {
      leftVersion: 'v1',
      rightVersion: 'v2',
      tenantId: 'tenant-a',
    })
    await knowledgeBaseApi.rollbackVersion('persy-knowledge', {
      version: 'v1',
      tenantId: 'tenant-a',
    })
    await knowledgeBaseApi.rebuildIndex('persy-knowledge', { tenantId: 'tenant-a' })
    await knowledgeBaseApi.rejectMemory('persy-knowledge', 'mem / 2', '噪声')
    await knowledgeBaseApi.graph('persy-knowledge', Number.NaN)

    expect(mocks.api.get).toHaveBeenCalledWith('/api/knowledge/v1/health')
    expect(mocks.api.get).toHaveBeenCalledWith('/api/knowledge/v1/datasets')
    expect(mocks.api.get).toHaveBeenCalledWith('/api/knowledge/v1/omniscient')
    expect(mocks.api.post).toHaveBeenCalledWith(
      '/api/knowledge/v1/omniscient/query',
      expect.objectContaining({ query: 'platform issue', top_k: 5 }),
    )
    expect(mocks.api.post).toHaveBeenCalledWith(
      '/api/knowledge/v1/datasets/persy-knowledge/versions/diff',
      expect.objectContaining({
        left_version: 'v1',
        right_version: 'v2',
        tenant_id: 'tenant-a',
      }),
    )
    expect(mocks.api.post).toHaveBeenCalledWith(
      '/api/knowledge/v1/datasets/persy-knowledge/versions/rollback',
      { version: 'v1', tenant_id: 'tenant-a' },
    )
    expect(mocks.api.post).toHaveBeenCalledWith(
      '/api/knowledge/v1/datasets/persy-knowledge/index/rebuild',
      { tenant_id: 'tenant-a' },
    )
    expect(mocks.api.post).toHaveBeenCalledWith(
      '/api/knowledge/v1/datasets/persy-knowledge/memories/mem%20%2F%202/reject',
      { reason: '噪声' },
    )
    expect(mocks.api.get).toHaveBeenCalledWith(
      '/api/knowledge/v1/datasets/persy-knowledge/graph?limit=80',
    )
  })

  it('applies omniscientQuery default topK and empty rollback/rebuild tenants', async () => {
    await knowledgeBaseApi.omniscientQuery({ query: 'hello' })
    await knowledgeBaseApi.rollbackVersion('persy-knowledge', { version: 'v9' })
    await knowledgeBaseApi.rebuildIndex('persy-knowledge')
    await knowledgeBaseApi.diffVersions('persy-knowledge')
    await knowledgeBaseApi.deleteMemory('persy-knowledge', 'mem-x')
    await knowledgeBaseApi.graph('persy-knowledge', 5)

    expect(mocks.api.post).toHaveBeenCalledWith(
      '/api/knowledge/v1/omniscient/query',
      expect.objectContaining({ top_k: 8 }),
    )
    expect(mocks.api.post).toHaveBeenCalledWith(
      '/api/knowledge/v1/datasets/persy-knowledge/versions/rollback',
      { version: 'v9', tenant_id: '' },
    )
    expect(mocks.api.post).toHaveBeenCalledWith(
      '/api/knowledge/v1/datasets/persy-knowledge/index/rebuild',
      { tenant_id: '' },
    )
    expect(mocks.api.delete).toHaveBeenCalledWith(
      '/api/knowledge/v1/datasets/persy-knowledge/memories/mem-x',
    )
    expect(mocks.api.get).toHaveBeenCalledWith(
      '/api/knowledge/v1/datasets/persy-knowledge/graph?limit=20',
    )
  })
})
