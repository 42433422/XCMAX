import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia } from 'pinia'
import PersyKnowledgeView from './PersyKnowledgeView.vue'

const mocks = vi.hoisted(() => ({
  status: vi.fn(),
  graph: vi.fn(),
  memories: vi.fn(),
  omniscient: vi.fn(),
  query: vi.fn(),
  queryMemories: vi.fn(),
  confirmMemory: vi.fn(),
  rejectMemory: vi.fn(),
  updateMemory: vi.fn(),
  deleteMemory: vi.fn(),
  deleteDocument: vi.fn(),
  ingestDocument: vi.fn(),
  uploadDocument: vi.fn(),
  rebuildIndex: vi.fn(),
  resetGraphView: vi.fn(),
}))

vi.mock('@/api/knowledgeBase', () => ({
  PERSY_KNOWLEDGE_DATASET_ID: 'persy-knowledge',
  normalizeKnowledgeDatasetId: (value?: string) => value?.trim() || 'persy-knowledge',
  knowledgeBaseApi: mocks,
}))

vi.mock('@/utils/adminConsoleUrl', () => ({
  isAdminConsoleSpa: vi.fn(() => false),
}))

vi.mock('@/components/persy/PersyKnowledgeGraph.vue', () => ({
  default: defineComponent({
    name: 'PersyKnowledgeGraphStub',
    props: ['graph', 'selectedNodeId', 'recall', 'loading'],
    emits: ['selectNode', 'onboardingAction'],
    expose: ['resetView'],
    template: '<div data-testid="graph-stub"></div>',
    methods: { resetView: () => mocks.resetGraphView() },
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

const wrappers: ReturnType<typeof mount>[] = []
async function mountKnowledge() {
  const wrapper = mount(PersyKnowledgeView, { global: { plugins: [createPinia()] } })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}
async function clickLabel(wrapper: ReturnType<typeof mount>, selector: string, text: string) {
  const button = wrapper.findAll(selector).find((item) => item.text().includes(text))
  expect(button, text).toBeTruthy()
  await button!.trigger('click')
  await flushPromises()
}
afterEach(() => {
  wrappers.splice(0).forEach((wrapper) => wrapper.unmount())
  vi.restoreAllMocks()
})

describe('PersyKnowledgeView', () => {
  beforeEach(async () => {
    vi.clearAllMocks()
    const { isAdminConsoleSpa } = await import('@/utils/adminConsoleUrl')
    vi.mocked(isAdminConsoleSpa).mockReturnValue(false)
    mocks.omniscient.mockResolvedValue({
      success: true,
      document_count: 0,
      chunk_count: 0,
      dataset_count: 1,
      recommended_dataset_id: 'persy-knowledge',
      datasets: { 'persy-knowledge': { document_count: 0, chunk_count: 0 } },
    })
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
    for (const action of ['rejectMemory', 'updateMemory', 'deleteMemory', 'deleteDocument', 'rebuildIndex'] as const) mocks[action].mockResolvedValue({ success: true })
    mocks.ingestDocument.mockResolvedValue({ success: true, chunk_count: 2 })
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
    const wrapper = await mountKnowledge()

    const memoryTab = wrapper.findAll('.view-switch button').find((button) => button.text().includes('记忆'))
    expect(memoryTab).toBeTruthy()
    await memoryTab!.trigger('click')

    expect(wrapper.text()).toContain('用户的偏好是下午沟通')
    expect(wrapper.text()).toContain('待确认')
    await wrapper.get('button[aria-label="确认记忆"]').trigger('click')
    await flushPromises()

    expect(mocks.confirmMemory).toHaveBeenCalledWith('persy-knowledge', 'mem-1')
  })

  it('merges governed memory and document evidence in one recall trace', async () => {
    const wrapper = await mountKnowledge()

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

  it('admin omniscient auto-switches to nonempty space and heals empty graph once', async () => {
    const { isAdminConsoleSpa } = await import('@/utils/adminConsoleUrl')
    vi.mocked(isAdminConsoleSpa).mockReturnValue(true)
    mocks.omniscient.mockResolvedValue({
      success: true,
      document_count: 496,
      chunk_count: 496,
      dataset_count: 2,
      recommended_dataset_id: 'user_tenant-a',
      datasets: {
        'persy-knowledge': { document_count: 0, chunk_count: 0 },
        'user_tenant-a': { document_count: 496, chunk_count: 496 },
      },
    })
    mocks.status
      .mockResolvedValueOnce({
        success: true,
        dataset_id: 'user_tenant-a',
        document_count: 0,
        chunk_count: 0,
        documents: [],
        index: { semantic_embedding_available: true },
      })
      .mockResolvedValueOnce({
        success: true,
        dataset_id: 'user_tenant-a',
        document_count: 496,
        chunk_count: 496,
        documents: [],
        index: { semantic_embedding_available: true },
      })
    mocks.graph
      .mockResolvedValueOnce({
        success: true,
        dataset_id: 'user_tenant-a',
        nodes: [{ id: 'persy:user_tenant-a', label: 'Persy', type: 'core' }],
        edges: [],
      })
      .mockResolvedValueOnce({
        success: true,
        dataset_id: 'user_tenant-a',
        nodes: [
          { id: 'persy:user_tenant-a', label: 'Persy', type: 'core' },
          { id: 'document:doc-1', label: '续约制度', type: 'source' },
        ],
        edges: [],
        stats: { edge_count: 1 },
      })
    mocks.memories.mockResolvedValue({ success: true, memories: [] })

    const wrapper = await mountKnowledge()

    expect(mocks.omniscient).toHaveBeenCalled()
    expect(mocks.status).toHaveBeenCalledWith('user_tenant-a', { includeDocuments: false })
    expect(mocks.graph).toHaveBeenCalledWith('user_tenant-a')
    // first empty load + heal retry
    expect(mocks.graph).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('496')
    expect(wrapper.text()).toMatch(/内容/)
  })

  it('opens pending review, cancels a correction, and saves edited memory fields', async () => {
    const wrapper = await mountKnowledge()
    await wrapper.get('.memory-review-button').trigger('click')
    expect(wrapper.get('.brain-inspector').classes()).toContain('is-open')
    expect(wrapper.get('.fact-list').text()).toContain('召回次数')
    await clickLabel(wrapper, '.memory-detail-actions button', '纠正')
    await clickLabel(wrapper, '.memory-editor button', '取消')
    expect(wrapper.find('.memory-editor').exists()).toBe(false)
    expect(mocks.updateMemory).not.toHaveBeenCalled()
    await clickLabel(wrapper, '.memory-detail-actions button', '纠正')
    const fields = wrapper.findAll('.memory-editor input')
    await fields[0].setValue(' 客户 ')
    await fields[1].setValue(' 联系时间 ')
    await wrapper.get('.memory-editor textarea').setValue(' 上午 ')
    await wrapper.get('.memory-editor').trigger('submit')
    await flushPromises()
    expect(mocks.updateMemory).toHaveBeenCalledWith('persy-knowledge', 'mem-1', expect.objectContaining({
      key: '客户.联系时间', value: expect.objectContaining({ subject: '客户', predicate: '联系时间', object: '上午' }),
    }))
    expect(wrapper.get('.memory-message').text()).toBe('记忆已纠正')
    expect(wrapper.find('.memory-editor').exists()).toBe(false)
  })

  it.each([['确认记忆', 'confirmMemory'], ['忽略', 'rejectMemory']] as const)('reports an unsuccessful %s action in the inspector', async (label, action) => {
    mocks[action].mockResolvedValue({ success: false, message: '审核服务离线' })
    const wrapper = await mountKnowledge()
    await wrapper.get('.memory-review-button').trigger('click')
    await clickLabel(wrapper, '.memory-detail-actions button', label)
    expect(mocks[action]).toHaveBeenCalledWith('persy-knowledge', 'mem-1', ...(action === 'rejectMemory' ? ['user_rejected_from_persy'] : []))
    expect(wrapper.get('.memory-message').text()).toBe('审核服务离线')
    expect(wrapper.get('.memory-primary-button').attributes('disabled')).toBeUndefined()
  })

  it('requires confirmation before deleting an active memory and shows the result', async () => {
    mocks.memories.mockResolvedValue({ success: true, memories: [{ ...pendingMemory, status: 'active' }] })
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const wrapper = await mountKnowledge()
    await clickLabel(wrapper, '.view-switch button', '记忆')
    wrapper.findComponent({ name: 'PersyMemoryList' }).vm.$emit('select', { ...pendingMemory, status: 'active' })
    await flushPromises()
    await wrapper.get('button[title="删除记忆"]').trigger('click')
    expect(mocks.deleteMemory).not.toHaveBeenCalled()
    confirm.mockReturnValue(true)
    await wrapper.get('button[title="删除记忆"]').trigger('click')
    await flushPromises()
    expect(mocks.deleteMemory).toHaveBeenCalledWith('persy-knowledge', 'mem-1', 'user_deleted_from_persy')
    expect(wrapper.get('.memory-message').text()).toBe('记忆已删除')
  })

  it('loads source details on demand, asks about a source, and reports deletion failures', async () => {
    const doc = { document_id: 'doc-1', source: '续约制度', chunk_count: 3, parser: 'markdown', version_label: 'v2' }
    const node = { id: 'document:doc-1', type: 'source', label: doc.source, source: '续约.md', document_id: doc.document_id,
      chunk_index: 0, metadata: { ...doc, mention_count: 2 } }
    mocks.graph.mockResolvedValue({ success: true, nodes: [node], edges: [] })
    const wrapper = await mountKnowledge()
    mocks.status.mockResolvedValue({ success: true, document_count: 1, documents: [doc] })
    await clickLabel(wrapper, '.view-switch button', '来源')
    expect(mocks.status).toHaveBeenLastCalledWith('persy-knowledge', { includeDocuments: true })
    await wrapper.get('.source-row__select').trigger('click')
    for (const value of ['续约.md', 'v2', '知识节点', '关联知识', 'K1']) expect(wrapper.get('.fact-list').text()).toContain(value)
    await wrapper.get('.node-question-button').trigger('click')
    expect((wrapper.get('input[aria-label="向 Persy 提问"]').element as HTMLInputElement).value).toContain('续约制度')
    expect(wrapper.get('.brain-inspector').classes()).not.toContain('is-open')
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    mocks.deleteDocument.mockRejectedValueOnce(new Error('资料正在使用'))
    await wrapper.get('button[aria-label="删除资料"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('.page-alert').text()).toBe('资料正在使用')
    await wrapper.get('button[aria-label="删除资料"]').trigger('click')
    await flushPromises()
    expect(mocks.deleteDocument).toHaveBeenLastCalledWith('persy-knowledge', 'doc-1')
    expect(wrapper.get('.page-toast').text()).toContain('已删除')
  })

  it('filters cards and imports pasted knowledge into a switched dataset', async () => {
    const wrapper = await mountKnowledge()
    await clickLabel(wrapper, '.view-switch button', '卡片')
    await wrapper.get('input[placeholder="筛选节点"]').setValue('下午')
    expect(wrapper.findAll('.node-card')).toHaveLength(1)
    await wrapper.get('.node-card').trigger('click')
    expect(wrapper.get('.node-detail__heading').text()).toContain(pendingMemory.statement)
    await wrapper.get('input[placeholder="筛选节点"]').setValue('无匹配')
    expect(wrapper.findAll('.node-card')).toHaveLength(0)
    await clickLabel(wrapper, '.view-empty button', '导入')
    expect(wrapper.find('[role="dialog"]').exists()).toBe(true)
    await clickLabel(wrapper, '.import-tabs button', '文本')
    await wrapper.get('input[aria-label="数据集"]').setValue(' team ')
    await clickLabel(wrapper, '.advanced-settings button', '切换')
    expect(mocks.graph).toHaveBeenLastCalledWith('team')
    await wrapper.get('#persy-source').setValue('制度')
    await wrapper.get('#persy-text').setValue('需要财务审批。')
    await wrapper.get('.drawer-submit').trigger('click')
    await flushPromises()
    expect(mocks.ingestDocument).toHaveBeenCalledWith(expect.objectContaining({ datasetId: 'team', source: '制度', text: '需要财务审批。' }))
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(wrapper.get('.page-toast').text()).toContain('2')
    expect(wrapper.find('[data-testid="graph-stub"]').exists()).toBe(true)
    await wrapper.get('button[aria-label="导入知识"]').trigger('click')
    expect(wrapper.find('.page-toast').exists()).toBe(false)
  })

  it('routes graph onboarding, reset, refresh and inspector controls to visible state', async () => {
    const wrapper = await mountKnowledge()
    const graph = wrapper.findComponent({ name: 'PersyKnowledgeGraphStub' })
    await wrapper.get('button[aria-label="复位图谱"]').trigger('click')
    expect(mocks.resetGraphView).toHaveBeenCalledOnce()
    await wrapper.get('button[aria-label="刷新知识网络"]').trigger('click')
    await flushPromises()
    expect(mocks.graph).toHaveBeenCalledTimes(2)
    graph.vm.$emit('onboardingAction', 'paste')
    await flushPromises()
    expect(wrapper.find('#persy-text').exists()).toBe(true)
    await wrapper.get('button[aria-label="关闭"]').trigger('click')
    graph.vm.$emit('selectNode', { id: 'topic:1', type: 'topic', label: '主题' })
    await flushPromises()
    expect(wrapper.get('.node-detail__summary').text()).toBe('暂无摘要')
    await clickLabel(wrapper, '.inspector-tabs button', '召回')
    expect(wrapper.text()).toContain('尚无召回轨迹')
    await clickLabel(wrapper, '.inspector-tabs button', '节点')
    expect(wrapper.get('.node-detail__heading').text()).toContain('主题')
    await wrapper.get('button[aria-label="关闭详情"]').trigger('click')
    expect(wrapper.get('.brain-inspector').classes()).not.toContain('is-open')
  })


  it('changes the admin knowledge space and rebuilds its index', async () => {
    const { isAdminConsoleSpa } = await import('@/utils/adminConsoleUrl')
    vi.mocked(isAdminConsoleSpa).mockReturnValue(true)
    mocks.omniscient.mockResolvedValue({ success: true, datasets: { 'persy-knowledge': {}, team: {} } })
    const wrapper = await mountKnowledge()
    await wrapper.get('.dataset-switch select').setValue('team')
    await flushPromises()
    expect(mocks.status).toHaveBeenLastCalledWith('team', { includeDocuments: false })
    await wrapper.get('button[aria-label="重建索引"]').trigger('click')
    await flushPromises()
    expect(mocks.rebuildIndex).toHaveBeenCalledWith('team')
    expect(wrapper.get('button[aria-label="重建索引"]').attributes('disabled')).toBeUndefined()
  })

})
