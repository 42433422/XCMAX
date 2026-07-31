import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useIndustryStore } from '@/stores/industry'
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'
import PersyKnowledgeGraph, {
  type PersyGraphRecall,
} from '@/components/persy/PersyKnowledgeGraph.vue'
import {
  PERSY_KNOWLEDGE_DATASET_ID,
  knowledgeBaseApi,
  normalizeKnowledgeDatasetId,
  type KnowledgeBaseChunk,
  type KnowledgeBaseDocument,
  type KnowledgeBaseStatus,
  type KnowledgeGraphNode,
  type KnowledgeGraphResponse,
  type KnowledgeOmniscientOverview,
  type KnowledgeTenant,
  type PersyMemoryRecord,
  type PersyMemoryValue,
} from '@/api/knowledgeBase'


export function usePersyKnowledgePage() {
type ViewMode = 'graph' | 'memories' | 'cards' | 'sources'
type ImportMode = 'file' | 'text'
type InspectorTab = 'node' | 'recall'
type KnowledgeScopeMode = 'public' | 'private'

const industryStore = useIndustryStore()
const isAttendanceIndustry = computed(
  () => String(industryStore.currentIndustryId || '').trim() === '考勤',
)
const knowledgeQueryPlaceholder = computed(() =>
  isAttendanceIndustry.value
    ? '问 Persy：考勤异常处理规则是什么？'
    : '问 Persy：客户续约需要谁审批？',
)
const knowledgeSourcePlaceholder = computed(() =>
  isAttendanceIndustry.value ? '例如：考勤管理制度' : '例如：客户续约制度',
)
const knowledgeTextPlaceholder = computed(() =>
  isAttendanceIndustry.value
    ? '粘贴考勤制度、排班规则、请假流程或常见问题'
    : '粘贴制度、流程、客户资料、产品说明或 FAQ',
)

const activeDatasetId = ref(PERSY_KNOWLEDGE_DATASET_ID)
const datasetIdInput = ref(PERSY_KNOWLEDGE_DATASET_ID)
const adminOmniscient = computed(() => isAdminConsoleSpa())
const knowledgeScope = ref<KnowledgeScopeMode>('public')
const privateTenantId = ref('')
const tenantDirectory = ref<KnowledgeTenant[]>([])
const tenantDirectoryError = ref('')
const omniscient = ref<KnowledgeOmniscientOverview | null>(null)
const rebuildingIndex = ref(false)
const datasetOptions = computed(() => {
  const map = omniscient.value?.datasets || {}
  const rows = Object.entries(map).map(([id, item]) => ({
    id,
    label: `${id} · ${Number(item?.document_count || 0)} 文档`,
    docs: Number(item?.document_count || 0),
  }))
  rows.sort((a, b) => b.docs - a.docs || a.id.localeCompare(b.id))
  if (!rows.some((row) => row.id === PERSY_KNOWLEDGE_DATASET_ID)) {
    rows.unshift({ id: PERSY_KNOWLEDGE_DATASET_ID, label: `${PERSY_KNOWLEDGE_DATASET_ID} · 0 文档`, docs: 0 })
  }
  return rows
})
const status = ref<KnowledgeBaseStatus | null>(null)
const graph = ref<KnowledgeGraphResponse | null>(null)
const memories = ref<PersyMemoryRecord[]>([])
const graphComponent = ref<InstanceType<typeof PersyKnowledgeGraph> | null>(null)
const queryInput = ref<HTMLInputElement | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const selectedFile = ref<File | null>(null)
const selectedNode = ref<KnowledgeGraphNode | null>(null)
const viewMode = ref<ViewMode>('graph')
const importMode = ref<ImportMode>('file')
const inspectorTab = ref<InspectorTab>('node')
const importOpen = ref(false)
const mobileInspectorOpen = ref(false)
const draggingFile = ref(false)
const loadingStatus = ref(false)
const loadingGraph = ref(false)
const loadingMemories = ref(false)
const ingesting = ref(false)
const querying = ref(false)
const mutatingMemory = ref(false)
const memoryEditing = ref(false)
const deletingDocumentId = ref('')
const publishingDocumentId = ref('')
const source = ref('Persy 系统资料')
const documentText = ref('')
const queryText = ref('')
const nodeFilter = ref('')
const topK = ref(6)
const rerank = ref(true)
const ingestMessage = ref('')
const ingestError = ref('')
const queryMessage = ref('')
const queryError = ref('')
const pageError = ref('')
const memoryMessage = ref('')
const answerText = ref('')
const lastQuery = ref('')
const resultChunks = ref<KnowledgeBaseChunk[]>([])
const memoryDraftSubject = ref('')
const memoryDraftPredicate = ref('')
const memoryDraftObject = ref('')

const viewModes = computed<Array<{ value: ViewMode; label: string; icon: string }>>(() => [
  { value: 'graph', label: '图谱', icon: 'fa-share-alt' },
  ...(!adminOmniscient.value
    ? [{ value: 'memories' as ViewMode, label: '记忆', icon: 'fa-history' }]
    : []),
  { value: 'cards', label: '卡片', icon: 'fa-th-large' },
  { value: 'sources', label: '来源', icon: 'fa-files-o' },
])

const legendItems = [
  { type: 'topic', label: '主题', color: '#2f6f8f' },
  { type: 'source', label: '来源', color: '#c56f3d' },
  { type: 'knowledge', label: '知识', color: '#268578' },
  { type: 'memory', label: '记忆', color: '#a85667' },
  { type: 'recall', label: '召回', color: '#d39a29' },
]

const documentCount = computed(() => status.value?.document_count ?? 0)
const chunkCount = computed(() => status.value?.chunk_count ?? 0)
const documents = computed<KnowledgeBaseDocument[]>(() => status.value?.documents ?? [])
const allDatasetDocuments = computed<KnowledgeBaseDocument[]>(() => {
  const rows = omniscient.value?.datasets?.[activeDatasetId.value]?.documents
  return Array.isArray(rows) ? rows : []
})
const publicDocuments = computed(() =>
  allDatasetDocuments.value.filter((doc) => String(doc.tenant_id || '') === 'public'),
)
const privateDocuments = computed(() =>
  allDatasetDocuments.value.filter((doc) => String(doc.tenant_id || '') !== 'public'),
)
const publicDocumentCount = computed(() => publicDocuments.value.length)
const privateDocumentCount = computed(() => privateDocuments.value.length)
const publishedPublicCount = computed(
  () =>
    publicDocuments.value.filter((doc) => documentPublicationStatus(doc) === 'published').length,
)
const draftPublicCount = computed(() => publicDocumentCount.value - publishedPublicCount.value)
const privateTenantOptions = computed(() => {
  const counts = new Map<string, number>()
  for (const doc of privateDocuments.value) {
    const tenantId = String(doc.tenant_id || '').trim()
    if (!tenantId) continue
    counts.set(tenantId, (counts.get(tenantId) || 0) + 1)
  }
  const options = new Map<
    string,
    { id: string; name: string; code: string; documentCount: number }
  >()
  for (const tenant of tenantDirectory.value) {
    const id = String(tenant.tenant_id || tenant.id || '').trim()
    if (!id) continue
    const code = String(tenant.code || '').trim()
    options.set(id, {
      id,
      name: String(tenant.name || code || `企业 ${id}`),
      code,
      documentCount: counts.get(id) || 0,
    })
  }
  for (const [id, documentCount] of counts.entries()) {
    if (options.has(id)) continue
    options.set(id, {
      id,
      name: `未登记企业 ${id}`,
      code: '',
      documentCount,
    })
  }
  return [...options.values()].sort(
    (left, right) =>
      left.name.localeCompare(right.name, 'zh-CN') ||
      left.id.localeCompare(right.id),
  )
})
const privateTenantCount = computed(() => privateTenantOptions.value.length)
const selectedKnowledgeTenantId = computed(() => {
  if (!adminOmniscient.value) return ''
  return knowledgeScope.value === 'public' ? 'public' : privateTenantId.value.trim()
})
const scopeReady = computed(
  () => !adminOmniscient.value || knowledgeScope.value === 'public' || Boolean(privateTenantId.value.trim()),
)
const knowledgeConsoleTitle = computed(() => {
  if (!adminOmniscient.value) return '企业知识网络'
  return knowledgeScope.value === 'public' ? '公开知识库' : '企业私有知识库'
})
const activeScopeHint = computed(() => {
  if (knowledgeScope.value === 'public') {
    if (!documentCount.value) return '公开库为空，导入资料后先进入待发布状态'
    return `${publishedPublicCount.value} 份已上线，${draftPublicCount.value} 份待审核发布`
  }
  if (!privateTenantId.value.trim()) return '从企业目录选择租户后管理其私有资料'
  return documentCount.value
    ? `仅 ${privateTenantId.value.trim()} 可读取，其他企业不可见`
    : `当前企业暂无私有资料，可直接导入到 ${privateTenantId.value.trim()}`
})
const importTargetDescription = computed(() =>
  knowledgeScope.value === 'public'
    ? '导入后保存为草稿，审核发布后全部企业可检索'
    : privateTenantId.value.trim()
      ? `仅 ${privateTenantId.value.trim()} 可检索`
      : '请先从企业目录选择租户',
)
const graphNodeCount = computed(
  () => graph.value?.nodes.filter((node) => node.type !== 'core').length ?? 0,
)
const graphEdgeCount = computed(() => graph.value?.stats?.edge_count ?? graph.value?.edges.length ?? 0)
const pendingMemoryCount = computed(
  () => memories.value.filter((memory) => memory.status === 'pending').length,
)
const activeMemoryCount = computed(
  () => memories.value.filter((memory) => memory.status === 'active').length,
)
const semanticAvailable = computed(
  () =>
    status.value?.index?.semantic_embedding_available === true ||
    omniscient.value?.semantic_embedding_available === true ||
    omniscient.value?.embedder_available === true,
)
const retrievalModeText = computed(() =>
  semanticAvailable.value ? '语义召回' : '关键词召回',
)
const recallState = computed<PersyGraphRecall | null>(() =>
  lastQuery.value
    ? {
        query: lastQuery.value,
        chunks: resultChunks.value,
      }
    : null,
)
const knowledgeNodes = computed(() =>
  (graph.value?.nodes || []).filter((node) => node.type !== 'core'),
)
const filteredNodes = computed(() => {
  const query = nodeFilter.value.trim().toLocaleLowerCase('zh-CN')
  if (!query) return knowledgeNodes.value
  return knowledgeNodes.value.filter((node) =>
    `${node.label} ${node.summary || ''} ${node.source || ''}`.toLocaleLowerCase('zh-CN').includes(query),
  )
})
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
const selectedNodeFacts = computed(() => {
  if (!selectedNode.value) return []
  const node = selectedNode.value
  const metadata = node.metadata || {}
  const rows: Array<{ label: string; value: string }> = []
  if (selectedMemory.value) {
    const memory = selectedMemory.value
    rows.push({ label: '状态', value: memoryStatusLabel(memory.status) })
    rows.push({ label: '范围', value: memoryScopeLabel(memory.scope) })
    rows.push({ label: '记忆强度', value: strengthText(memory.strength) })
    rows.push({ label: '置信度', value: strengthText(memory.confidence) })
    rows.push({ label: '来源', value: memoryEvidenceSource(memory) })
    rows.push({ label: '更新时间', value: formatDate(memory.updated_at) })
    rows.push({ label: '召回次数', value: numberText(memory.recall_count || 0) })
    return rows
  }
  if (node.source) rows.push({ label: '来源', value: node.source })
  if (metadata.erp_domain_label) rows.push({ label: 'ERP 领域', value: String(metadata.erp_domain_label) })
  if (metadata.severity) rows.push({ label: '约束级别', value: String(metadata.severity) })
  if (metadata.symbolic_expression) {
    rows.push({ label: '符号表达', value: String(metadata.symbolic_expression) })
  }
  if (metadata.ontology_version) {
    rows.push({ label: '本体版本', value: String(metadata.ontology_version) })
  }
  if (metadata.version_label) rows.push({ label: '版本', value: String(metadata.version_label) })
  if (metadata.parser) rows.push({ label: '解析', value: parserLabel(metadata.parser) })
  if (metadata.chunk_count !== undefined) {
    rows.push({ label: '知识节点', value: numberText(metadata.chunk_count) })
  }
  if (metadata.mention_count !== undefined) {
    rows.push({ label: '关联知识', value: numberText(metadata.mention_count) })
  }
  if (node.chunk_index !== undefined) {
    rows.push({ label: '切片位置', value: `K${Number(node.chunk_index) + 1}` })
  }
  return rows.slice(0, 7)
})

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error || '操作失败')
}

function numberText(value: unknown): string {
  const n = Number(value)
  return Number.isFinite(n) ? n.toLocaleString('zh-CN') : '-'
}

function versionLabel(value: unknown): string {
  const n = Number(value)
  return Number.isFinite(n) && n > 0 ? `v${n}` : '-'
}

function formatScore(value: unknown): string {
  const n = Number(value)
  if (!Number.isFinite(n)) return '-'
  return n >= 1 ? n.toFixed(2) : `${Math.round(n * 100)}%`
}

function strengthText(value: unknown): string {
  const n = Number(value)
  if (!Number.isFinite(n)) return '-'
  return `${Math.round(Math.max(0, Math.min(n, 1)) * 100)}%`
}

function formatDate(value: unknown): string {
  const date = new Date(String(value || ''))
  if (!Number.isFinite(date.getTime())) return '-'
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

function memoryValue(memory: PersyMemoryRecord): PersyMemoryValue {
  return memory.value && typeof memory.value === 'object'
    ? (memory.value as PersyMemoryValue)
    : {}
}

function memoryStatusLabel(status: string): string {
  return (
    {
      pending: '待确认',
      active: '已确认',
      rejected: '已忽略',
      deleted: '已删除',
    }[status] || status || '未知'
  )
}

function memoryScopeLabel(scope: string): string {
  return scope === 'tenant' ? '企业共享' : '仅自己'
}

function memoryTypeLabel(type: string): string {
  return (
    {
      preference: '偏好',
      entity: '人物与事实',
      episodic: '经历',
    }[type] || '记忆'
  )
}

function memoryIcon(type: string): string {
  return (
    {
      preference: 'fa-heart-o',
      entity: 'fa-link',
      episodic: 'fa-clock-o',
    }[type] || 'fa-history'
  )
}

function memoryEvidenceSource(memory: PersyMemoryRecord): string {
  const first = Array.isArray(memory.evidence) ? memory.evidence[0] : null
  if (first && typeof first === 'object') {
    const sourceName = String(first.source || '').trim()
    if (sourceName) return sourceName === 'chat' ? '可信对话' : sourceName
  }
  return memory.source === 'chat_trace' ? '可信对话' : String(memory.source || '受控记忆')
}

function buildMemoryStatement(subject: string, predicate: string, object: string): string {
  return ['负责', '属于', '位于', '使用', '采用'].includes(predicate)
    ? `${subject}${predicate}${object}`
    : `${subject}的${predicate}是${object}`
}

function normalizeChunkSource(chunk: KnowledgeBaseChunk): string {
  const source = chunk.metadata?.source || chunk.source || '知识来源'
  const normalized = String(source).replace(/\+rerank$/i, '').trim()
  if (normalized.toLowerCase() === 'bm25') return '关键词召回'
  return normalized || '知识来源'
}

function normalizeAnswer(value: unknown, evidenceCount: number): string {
  const answer = String(value || '').trim()
  if (!answer) return ''
  if (/^Based on the retrieved dataset evidence\b/i.test(answer)) {
    return `已召回 ${evidenceCount} 条相关知识证据。`
  }
  return answer
}

function evidenceKey(chunk: KnowledgeBaseChunk, index: number): string {
  return `${chunk.metadata?.memory_id || chunk.metadata?.document_id || chunk.source || 'chunk'}-${chunk.chunk_index ?? index}`
}

function isMemoryChunk(chunk: KnowledgeBaseChunk): boolean {
  return Boolean(chunk.metadata?.memory_id)
}

function parserLabel(value: unknown): string {
  const parser = String(value || '')
  if (parser === 'inline_text') return '直接文本'
  if (parser === 'pdfplumber') return 'PDF'
  if (parser === 'python-docx') return 'Word'
  return parser || '文本'
}

function documentPublicationStatus(doc: KnowledgeBaseDocument): 'draft' | 'published' | 'archived' {
  const status = String(doc.metadata?.publication_status || 'draft').trim().toLowerCase()
  if (status === 'published' || status === 'archived') return status
  return 'draft'
}

function documentScopeLabel(doc: KnowledgeBaseDocument): string {
  if (String(doc.tenant_id || '') === 'public') {
    const status = documentPublicationStatus(doc)
    if (status === 'published') return '公开 · 已发布'
    if (status === 'archived') return '公开 · 已下线'
    return '公开 · 待发布'
  }
  return `企业私有 · ${String(doc.tenant_id || '当前企业')}`
}

function nodeTypeLabel(type: string): string {
  return (
    {
      core: 'Persy 核心',
      erp_ontology: 'ERP 本体',
      erp_domain: 'ERP 领域',
      erp_entity: 'ERP 实体',
      erp_rule: 'ERP 规则',
      erp_constraint: 'ERP 约束',
      topic: '主题',
      source: '资料来源',
      knowledge: '知识',
      memory: '长期记忆',
      recall: '召回',
      onboarding: '开始',
    }[type] || '知识节点'
  )
}

function nodeIcon(type: string): string {
  return (
    {
      core: 'fa-circle-o',
      erp_ontology: 'fa-sitemap',
      erp_domain: 'fa-cubes',
      erp_entity: 'fa-database',
      erp_rule: 'fa-code-fork',
      erp_constraint: 'fa-balance-scale',
      topic: 'fa-tag',
      source: 'fa-file-text-o',
      knowledge: 'fa-lightbulb-o',
      memory: 'fa-history',
      recall: 'fa-bolt',
      onboarding: 'fa-plus',
    }[type] || 'fa-circle'
  )
}

let refreshEpoch = 0

async function refreshStatus(
  expectedDatasetId?: string,
  epoch?: number,
  options: { includeDocuments?: boolean } = {},
): Promise<void> {
  const datasetId = expectedDatasetId || activeDatasetId.value
  const token = epoch ?? refreshEpoch
  const includeDocuments = options.includeDocuments === true || viewMode.value === 'sources'
  loadingStatus.value = true
  try {
    const next = await knowledgeBaseApi.status(datasetId, {
      includeDocuments,
      tenantId: selectedKnowledgeTenantId.value,
    })
    if (token !== refreshEpoch || datasetId !== activeDatasetId.value) return
    status.value = next
  } finally {
    if (token === refreshEpoch) loadingStatus.value = false
  }
}

async function refreshGraph(expectedDatasetId?: string, epoch?: number): Promise<void> {
  const datasetId = expectedDatasetId || activeDatasetId.value
  const token = epoch ?? refreshEpoch
  loadingGraph.value = true
  try {
    const nextGraph = await knowledgeBaseApi.graph(datasetId, 80, {
      tenantId: selectedKnowledgeTenantId.value,
    })
    if (token !== refreshEpoch || datasetId !== activeDatasetId.value) return
    if (!nextGraph.success) throw new Error(nextGraph.message || '知识图谱加载失败')
    graph.value = nextGraph
    const selectedId = selectedNode.value?.id
    selectedNode.value =
      nextGraph.nodes.find((node) => node.id === selectedId) ||
      nextGraph.nodes.find((node) => node.type === 'core') ||
      null
  } finally {
    if (token === refreshEpoch) loadingGraph.value = false
  }
}

async function refreshMemories(expectedDatasetId?: string, epoch?: number): Promise<void> {
  const datasetId = expectedDatasetId || activeDatasetId.value
  const token = epoch ?? refreshEpoch
  if (adminOmniscient.value || datasetId !== PERSY_KNOWLEDGE_DATASET_ID) {
    if (token === refreshEpoch && datasetId === activeDatasetId.value) memories.value = []
    return
  }
  loadingMemories.value = true
  try {
    const result = await knowledgeBaseApi.memories(datasetId, { limit: 1000 })
    if (token !== refreshEpoch || datasetId !== activeDatasetId.value) return
    if (!result.success) throw new Error(result.message || '记忆加载失败')
    memories.value = (Array.isArray(result.memories) ? result.memories : []).filter((memory) =>
      ['pending', 'active'].includes(memory.status),
    )
  } finally {
    if (token === refreshEpoch) loadingMemories.value = false
  }
}

async function loadOmniscientOverview(): Promise<boolean> {
  if (!adminOmniscient.value) {
    omniscient.value = null
    return false
  }
  try {
    const overview = await knowledgeBaseApi.omniscient()
    omniscient.value = overview
  } catch (error) {
    console.warn('[PersyKnowledge] omniscient overview failed', error)
  }
  return false
}

async function loadTenantDirectory(): Promise<void> {
  if (!adminOmniscient.value) {
    tenantDirectory.value = []
    tenantDirectoryError.value = ''
    return
  }
  tenantDirectoryError.value = ''
  try {
    const result = await knowledgeBaseApi.tenants()
    if (!result.success) throw new Error(result.message || '企业目录加载失败')
    tenantDirectory.value = Array.isArray(result.data)
      ? result.data.filter((tenant) => tenant.is_active !== false)
      : []
  } catch (error) {
    tenantDirectory.value = []
    tenantDirectoryError.value =
      error instanceof Error ? error.message : '企业目录加载失败，请检查管理数据库'
  }
}

async function rebuildActiveIndex(): Promise<void> {
  if (!adminOmniscient.value || rebuildingIndex.value) return
  if (!scopeReady.value) {
    pageError.value = '请先从企业目录选择租户'
    return
  }
  rebuildingIndex.value = true
  try {
    await knowledgeBaseApi.rebuildIndex(activeDatasetId.value, {
      tenantId: selectedKnowledgeTenantId.value,
    })
    await refreshAll()
  } catch (error) {
    console.warn('[PersyKnowledge] rebuild failed', error)
  } finally {
    rebuildingIndex.value = false
  }
}

async function refreshDatasetViews(epoch: number, datasetId: string): Promise<void> {
  if (!scopeReady.value) {
    status.value = {
      success: true,
      dataset_id: datasetId,
      document_count: 0,
      chunk_count: 0,
      documents: [],
    }
    graph.value = {
      success: true,
      dataset_id: datasetId,
      tenant_id: '',
      nodes: [],
      edges: [],
    }
    memories.value = []
    return
  }
  const results = await Promise.allSettled([
    refreshStatus(datasetId, epoch),
    refreshGraph(datasetId, epoch),
    refreshMemories(datasetId, epoch),
  ])
  if (epoch !== refreshEpoch) return
  const rejected = results.find((result) => result.status === 'rejected')
  if (rejected?.status === 'rejected') pageError.value = errorText(rejected.reason)
}

async function refreshAll(): Promise<void> {
  pageError.value = ''
  const epoch = ++refreshEpoch
  await Promise.all([loadOmniscientOverview(), loadTenantDirectory()])
  if (epoch !== refreshEpoch) return
  if (!privateTenantId.value && privateTenantOptions.value.length) {
    privateTenantId.value = privateTenantOptions.value[0].id
  }
  const datasetId = activeDatasetId.value
  await refreshDatasetViews(epoch, datasetId)
  if (epoch !== refreshEpoch || !adminOmniscient.value || !omniscient.value) return
  const expected = adminOmniscient.value
    ? allDatasetDocuments.value.filter(
        (doc) => String(doc.tenant_id || '') === selectedKnowledgeTenantId.value,
      ).length
    : Number(omniscient.value.datasets?.[datasetId]?.document_count || 0)
  const loadedDocs = Number(status.value?.document_count || 0)
  const loadedNodes = Number(
    graph.value?.nodes?.filter((node) => node.type !== 'core' && node.type !== 'onboarding')
      .length || 0,
  )
  if (expected > 0 && (loadedDocs <= 0 || loadedNodes <= 0) && datasetId === activeDatasetId.value) {
    await refreshDatasetViews(epoch, datasetId)
  }
}

async function applyDataset(): Promise<void> {
  activeDatasetId.value = normalizeKnowledgeDatasetId(datasetIdInput.value)
  datasetIdInput.value = activeDatasetId.value
  answerText.value = ''
  lastQuery.value = ''
  resultChunks.value = []
  queryMessage.value = ''
  queryError.value = ''
  await refreshAll()
}

async function switchKnowledgeScope(scope: KnowledgeScopeMode): Promise<void> {
  if (knowledgeScope.value === scope) return
  knowledgeScope.value = scope
  if (scope === 'private' && !privateTenantId.value && privateTenantOptions.value.length) {
    privateTenantId.value = privateTenantOptions.value[0].id
  }
  await applyKnowledgeScope()
}

async function applyKnowledgeScope(): Promise<void> {
  answerText.value = ''
  lastQuery.value = ''
  resultChunks.value = []
  queryMessage.value = ''
  queryError.value = ''
  selectedNode.value = null
  await refreshAll()
}

function openImport(mode: ImportMode): void {
  if (adminOmniscient.value && !scopeReady.value) {
    pageError.value = '请先从企业目录选择租户'
    return
  }
  importMode.value = mode
  ingestError.value = ''
  ingestMessage.value = ''
  importOpen.value = true
}

function closeImport(): void {
  if (ingesting.value) return
  importOpen.value = false
  draggingFile.value = false
}

async function ingestDocument(): Promise<void> {
  const text = documentText.value.trim()
  ingestMessage.value = ''
  ingestError.value = ''
  if (importMode.value === 'file' && !selectedFile.value) {
    ingestError.value = '请选择资料文件'
    return
  }
  if (importMode.value === 'text' && !text) {
    ingestError.value = '请输入资料内容'
    return
  }
  if (adminOmniscient.value && !scopeReady.value) {
    ingestError.value = '请先从企业目录选择租户'
    return
  }
  const tenantId = selectedKnowledgeTenantId.value
  const scopeMetadata =
    adminOmniscient.value && knowledgeScope.value === 'public'
      ? {
          audience: 'public',
          visibility: 'public',
          publication_status: 'draft',
          entrypoint: 'admin_public_knowledge',
        }
      : {
          audience: 'tenant',
          visibility: 'private',
          publication_status: 'active',
          entrypoint: adminOmniscient.value
            ? 'admin_private_knowledge'
            : 'persy_knowledge_view',
        }
  ingesting.value = true
  try {
    const result =
      importMode.value === 'file' && selectedFile.value
        ? await knowledgeBaseApi.uploadDocument({
            datasetId: activeDatasetId.value,
            source: source.value.trim() || selectedFile.value.name,
            file: selectedFile.value,
            tenantId,
            metadata: scopeMetadata,
          })
        : await knowledgeBaseApi.ingestDocument({
            datasetId: activeDatasetId.value,
            source: source.value.trim() || 'Persy 手工资料',
            text,
            tenantId,
            metadata: {
              scope: 'persy',
              ...scopeMetadata,
            },
          })
    if (!result.success) throw new Error(result.message || '资料入库失败')
    const chunks = result.chunk_count ?? result.document?.chunk_count ?? 0
    ingestMessage.value =
      adminOmniscient.value && knowledgeScope.value === 'public'
        ? `公开资料草稿已保存，形成 ${chunks} 个知识节点，审核发布后对企业生效`
        : `已形成 ${chunks} 个知识节点`
    documentText.value = ''
    clearSelectedFile()
    importOpen.value = false
    viewMode.value = 'graph'
    await refreshAll()
  } catch (error) {
    ingestError.value = errorText(error)
  } finally {
    ingesting.value = false
  }
}

function openFilePicker(): void {
  fileInput.value?.click()
}

function setSelectedFile(file: File | null): void {
  selectedFile.value = file
  if (file && (source.value === 'Persy 系统资料' || !source.value.trim())) source.value = file.name
}

function validateKnowledgeFile(file: File): string {
  const extension = file.name.includes('.') ? `.${file.name.split('.').pop()?.toLowerCase()}` : ''
  if (!['.pdf', '.docx', '.xlsx', '.xls', '.txt', '.md', '.csv', '.json', '.log'].includes(extension)) {
    return `不支持的资料类型：${extension || '无扩展名'}`
  }
  if (file.size > 25 * 1024 * 1024) {
    return '资料文件不能超过 25 MB'
  }
  return ''
}

function selectFile(event: Event): void {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0] || null
  if (!file) {
    setSelectedFile(null)
    return
  }
  const error = validateKnowledgeFile(file)
  if (error) {
    ingestError.value = error
    clearSelectedFile()
    return
  }
  ingestError.value = ''
  setSelectedFile(file)
}

function dropFile(event: DragEvent): void {
  draggingFile.value = false
  const file = event.dataTransfer?.files?.[0] || null
  if (!file) return
  const error = validateKnowledgeFile(file)
  if (error) {
    ingestError.value = error
    return
  }
  ingestError.value = ''
  setSelectedFile(file)
}

function clearSelectedFile(): void {
  selectedFile.value = null
  if (fileInput.value) fileInput.value.value = ''
}

function fileSizeText(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
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
  if (adminOmniscient.value && !scopeReady.value) {
    queryError.value = '请先从企业目录选择租户'
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
      knowledge = await knowledgeBaseApi.query({
        datasetId: activeDatasetId.value,
        query,
        topK: boundedTopK,
        rerank: rerank.value,
        tenantId: selectedKnowledgeTenantId.value,
        includePublic: !adminOmniscient.value,
        metadataFilter:
          adminOmniscient.value && knowledgeScope.value === 'public'
            ? { publication_status: 'published' }
            : {},
      })
    } catch (error) {
      knowledgeFailure = error
    }
    if (
      !adminOmniscient.value &&
      activeDatasetId.value === PERSY_KNOWLEDGE_DATASET_ID &&
      knowledge?.persy_memory === undefined
    ) {
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
    inspectorTab.value = 'recall'
    mobileInspectorOpen.value = true
    viewMode.value = 'graph'
    if (recalledMemoryCount) {
      await Promise.allSettled([refreshMemories(), refreshGraph()])
    }
  } catch (error) {
    queryError.value = errorText(error)
  } finally {
    querying.value = false
  }
}

function selectNode(node: KnowledgeGraphNode): void {
  selectedNode.value = node
  memoryEditing.value = false
  memoryMessage.value = ''
  inspectorTab.value = 'node'
  mobileInspectorOpen.value = true
}

function selectMemory(memory: PersyMemoryRecord): void {
  const graphNode = graph.value?.nodes.find(
    (node) => String(node.metadata?.memory_id || '') === memory.memory_id,
  )
  selectNode(
    graphNode || {
      id: `memory:${memory.memory_id}`,
      label: memory.statement,
      type: 'memory',
      summary: memory.statement,
      strength: memory.strength,
      metadata: {
        memory_id: memory.memory_id,
        status: memory.status,
        scope: memory.scope,
      },
    },
  )
}

function openPendingMemories(): void {
  viewMode.value = 'memories'
  const pending = orderedMemories.value.find((memory) => memory.status === 'pending')
  if (pending) selectMemory(pending)
}

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
  ingestMessage.value = message
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
    const result = await knowledgeBaseApi.rejectMemory(
      activeDatasetId.value,
      memory.memory_id,
      'user_rejected_from_persy',
    )
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
        { name: subject, type: String(previous.entities?.[0]?.type || 'concept'), role: 'subject' },
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
    const result = await knowledgeBaseApi.deleteMemory(
      activeDatasetId.value,
      memory.memory_id,
      'user_deleted_from_persy',
    )
    if (!result.success) throw new Error(result.message || '删除记忆失败')
    await refreshAfterMemoryMutation(memory.memory_id, '记忆已删除')
  } catch (error) {
    memoryMessage.value = errorText(error)
  } finally {
    mutatingMemory.value = false
  }
}

function selectDocument(doc: KnowledgeBaseDocument): void {
  const node = graph.value?.nodes.find(
    (candidate) => candidate.type === 'source' && candidate.document_id === doc.document_id,
  )
  if (node) selectNode(node)
}

async function setDocumentPublication(doc: KnowledgeBaseDocument): Promise<void> {
  const documentId = String(doc.document_id || '')
  if (!documentId || publishingDocumentId.value) return
  const isPublished = documentPublicationStatus(doc) === 'published'
  const nextStatus = isPublished ? 'archived' : 'published'
  const actionLabel = isPublished ? '下线' : '发布'
  const reason = window.prompt(
    `请输入${actionLabel}公开资料“${doc.source || '未命名资料'}”的原因（至少 4 个字符）`,
    isPublished ? '资料已过期或需要修订' : '内容已完成审核，可以公开检索',
  )?.trim()
  if (!reason) return
  if (reason.length < 4) {
    pageError.value = '发布原因至少需要 4 个字符'
    return
  }

  publishingDocumentId.value = documentId
  ingestMessage.value = ''
  pageError.value = ''
  try {
    const result = await knowledgeBaseApi.setDocumentPublication(
      activeDatasetId.value,
      documentId,
      nextStatus,
      reason,
      documentPublicationStatus(doc),
    )
    if (!result.success) throw new Error(result.message || `${actionLabel}资料失败`)
    ingestMessage.value = isPublished
      ? '公开资料已下线，企业检索将不再召回'
      : '公开资料已发布，企业检索现在可以召回'
    await refreshAll()
  } catch (error) {
    pageError.value = errorText(error)
  } finally {
    publishingDocumentId.value = ''
  }
}

async function deleteDocument(doc: KnowledgeBaseDocument): Promise<void> {
  const documentId = String(doc.document_id || '')
  if (
    !documentId ||
    deletingDocumentId.value ||
    !window.confirm(`删除资料“${doc.source || '未命名资料'}”及其全部知识节点？`)
  ) {
    return
  }
  deletingDocumentId.value = documentId
  ingestMessage.value = ''
  try {
    const result = await knowledgeBaseApi.deleteDocument(activeDatasetId.value, documentId)
    if (!result.success) throw new Error(result.message || '删除资料失败')
    ingestMessage.value = '资料及其知识节点已删除'
    await refreshAll()
  } catch (error) {
    pageError.value = errorText(error)
  } finally {
    deletingDocumentId.value = ''
  }
}

function askAboutSelectedNode(): void {
  if (!selectedNode.value) return
  queryText.value = `关于“${selectedNode.value.label}”，请结合已有知识说明关键事实。`
  mobileInspectorOpen.value = false
  nextTick(() => queryInput.value?.focus())
}

function handleOnboardingAction(action: 'upload' | 'paste' | 'chat'): void {
  if (action === 'upload') openImport('file')
  if (action === 'paste') openImport('text')
  if (action === 'chat') nextTick(() => queryInput.value?.focus())
}

function resetGraphView(): void {
  graphComponent.value?.resetView()
}

watch(viewMode, (mode) => {
  if (mode !== 'sources') return
  if ((status.value?.documents || []).length > 0) return
  void refreshStatus(undefined, undefined, { includeDocuments: true })
})

onMounted(() => {
  void refreshAll()
})
  return {
    activeDatasetId,
    activeMemoryCount,
    activeScopeHint,
    adminOmniscient,
    allDatasetDocuments,
    answerText,
    applyDataset,
    applyKnowledgeScope,
    askAboutSelectedNode,
    buildMemoryStatement,
    cancelMemoryEdit,
    chunkCount,
    clearSelectedFile,
    closeImport,
    confirmMemory,
    datasetIdInput,
    datasetOptions,
    deleteDocument,
    deleteMemory,
    deletingDocumentId,
    documentCount,
    documentPublicationStatus,
    documentScopeLabel,
    documentText,
    documents,
    draftPublicCount,
    draggingFile,
    dropFile,
    errorText,
    evidenceKey,
    fileInput,
    fileSizeText,
    filteredNodes,
    formatDate,
    formatScore,
    graph,
    graphComponent,
    graphEdgeCount,
    graphNodeCount,
    handleOnboardingAction,
    importMode,
    importOpen,
    importTargetDescription,
    industryStore,
    ingestDocument,
    ingestError,
    ingestMessage,
    ingesting,
    inspectorTab,
    isAttendanceIndustry,
    isMemoryChunk,
    knowledgeConsoleTitle,
    knowledgeNodes,
    knowledgeQueryPlaceholder,
    knowledgeScope,
    knowledgeSourcePlaceholder,
    knowledgeTextPlaceholder,
    lastQuery,
    legendItems,
    loadOmniscientOverview,
    loadTenantDirectory,
    loadingGraph,
    loadingMemories,
    loadingStatus,
    memories,
    memoryDraftObject,
    memoryDraftPredicate,
    memoryDraftSubject,
    memoryEditing,
    memoryEvidenceSource,
    memoryIcon,
    memoryMessage,
    memoryScopeLabel,
    memoryStatusLabel,
    memoryTypeLabel,
    memoryValue,
    mobileInspectorOpen,
    mutatingMemory,
    nodeFilter,
    nodeIcon,
    nodeTypeLabel,
    normalizeAnswer,
    normalizeChunkSource,
    numberText,
    omniscient,
    openFilePicker,
    openImport,
    openPendingMemories,
    orderedMemories,
    pageError,
    parserLabel,
    pendingMemoryCount,
    privateDocumentCount,
    privateDocuments,
    privateTenantCount,
    privateTenantId,
    privateTenantOptions,
    publicDocumentCount,
    publicDocuments,
    publishedPublicCount,
    publishingDocumentId,
    queryError,
    queryInput,
    queryKnowledge,
    queryMessage,
    queryText,
    querying,
    rebuildActiveIndex,
    rebuildingIndex,
    recallState,
    refreshAfterMemoryMutation,
    refreshAll,
    refreshDatasetViews,
    refreshEpoch,
    refreshGraph,
    refreshMemories,
    refreshStatus,
    rejectMemory,
    rerank,
    resetGraphView,
    resultChunks,
    retrievalModeText,
    saveMemoryEdit,
    scopeReady,
    selectDocument,
    selectFile,
    selectMemory,
    selectNode,
    selectedFile,
    selectedKnowledgeTenantId,
    selectedMemory,
    selectedNode,
    selectedNodeFacts,
    semanticAvailable,
    setDocumentPublication,
    setSelectedFile,
    source,
    startMemoryEdit,
    status,
    strengthText,
    switchKnowledgeScope,
    tenantDirectory,
    tenantDirectoryError,
    topK,
    validateKnowledgeFile,
    versionLabel,
    viewMode,
    viewModes,
  }
}
