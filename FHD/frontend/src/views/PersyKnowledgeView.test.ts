import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia } from 'pinia'
import PersyKnowledgeView from './PersyKnowledgeView.vue'

const mocks = vi.hoisted(() => ({
  status: vi.fn(),
  graph: vi.fn(),
  memories: vi.fn(),
  query: vi.fn(),
  queryMemories: vi.fn(),
  confirmMemory: vi.fn(),
  rejectMemory: vi.fn(),
  updateMemory: vi.fn(),
  deleteMemory: vi.fn(),
  deleteDocument: vi.fn(),
  ingestDocument: vi.fn(),
  uploadDocument: vi.fn(),
}))

vi.mock('@/api/knowledgeBase', () => ({
  PERSY_KNOWLEDGE_DATASET_ID: 'persy-knowledge',
  normalizeKnowledgeDatasetId: (value?: string) => value?.trim() || 'persy-knowledge',
  knowledgeBaseApi: mocks,
}))

vi.mock('@/components/persy/PersyKnowledgeGraph.vue', () => ({
  default: defineComponent({
    name: 'PersyKnowledgeGraphStub',
    props: ['graph', 'selectedNodeId', 'recall', 'loading'],
    emits: ['selectNode', 'onboardingAction'],
    expose: ['resetView'],
    template: '<div data-testid="graph-stub"></div>',
    methods: { resetView: vi.fn() },
  }),
}))

const pendingMemory = {
  memory_id: 'mem-1',
  memory_type: 'preference',
  key: '用户.偏好',
  value: {
    subject: '用户',
    predicate: '偏好',
    object: '下午沟通',
    statement: '用户的偏好是下午沟通',
    entities: [],
  },
  statement: '用户的偏好是下午沟通',
  status: 'pending',
  scope: 'user',
  confidence: 0.94,
  strength: 0.72,
  source: 'chat_trace',
  evidence: [{ source: 'chat', session_id: 'session-1' }],
  updated_at: '2026-07-15T10:00:00Z',
}

describe('PersyKnowledgeView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.status.mockResolvedValue({
      success: true,
      dataset_id: 'persy-knowledge',
      document_count: 1,
      chunk_count: 1,
      documents: [],
      index: { semantic_embedding_available: false },
    })
    mocks.graph.mockResolvedValue({
      success: true,
      dataset_id: 'persy-knowledge',
      nodes: [
        { id: 'persy:persy-knowledge', label: 'Persy', type: 'core' },
        {
          id: 'memory:mem-1',
          label: pendingMemory.statement,
          type: 'memory',
          summary: pendingMemory.statement,
          metadata: { memory_id: 'mem-1', status: 'pending', scope: 'user' },
        },
      ],
      edges: [],
    })
    mocks.memories.mockResolvedValue({ success: true, memories: [pendingMemory] })
    mocks.confirmMemory.mockResolvedValue({
      success: true,
      memory: { ...pendingMemory, status: 'active' },
    })
    mocks.query.mockResolvedValue({
      success: true,
      dataset_id: 'persy-knowledge',
      answer: '下午联系，并遵循续约制度。',
      chunks: [
        {
          text: pendingMemory.statement,
          source: '对话记忆',
          score: 0.96,
          metadata: { memory_id: 'mem-1' },
        },
        {
          text: '续约需要财务审批。',
          source: '续约制度.md',
          score: 0.82,
          chunk_index: 0,
          metadata: { document_id: 'doc-1' },
        },
      ],
      persy_memory: {
        available: true,
        count: 1,
        retriever: 'persy_memory_lexical_strength_v1',
      },
    })
    mocks.queryMemories.mockResolvedValue({
      success: true,
      memories: [],
      chunks: [
        {
          text: pendingMemory.statement,
          source: '对话记忆',
          score: 0.96,
          metadata: { memory_id: 'mem-1' },
        },
      ],
    })
  })

  it('shows pending memories and confirms them from the governance list', async () => {
    const wrapper = mount(PersyKnowledgeView, { global: { plugins: [createPinia()] } })
    await flushPromises()

    const memoryTab = wrapper.findAll('.view-switch button').find((button) =>
      button.text().includes('记忆'),
    )
    expect(memoryTab).toBeTruthy()
    await memoryTab!.trigger('click')

    expect(wrapper.text()).toContain('用户的偏好是下午沟通')
    expect(wrapper.text()).toContain('待确认')
    await wrapper.get('button[aria-label="确认记忆"]').trigger('click')
    await flushPromises()

    expect(mocks.confirmMemory).toHaveBeenCalledWith('persy-knowledge', 'mem-1')
  })

  it('merges governed memory and document evidence in one recall trace', async () => {
    const wrapper = mount(PersyKnowledgeView, { global: { plugins: [createPinia()] } })
    await flushPromises()

    await wrapper.get('input[aria-label="向 Persy 提问"]').setValue('什么时候联系并如何续约？')
    await wrapper.get('form.ask-dock').trigger('submit')
    await flushPromises()

    expect(mocks.query).toHaveBeenCalledOnce()
    expect(mocks.queryMemories).not.toHaveBeenCalled()
    const evidence = wrapper.findAll('.evidence-list article')
    expect(evidence).toHaveLength(2)
    expect(evidence[0].text()).toContain('M1')
    expect(wrapper.text()).toContain('下午联系，并遵循续约制度。')
  })
})
