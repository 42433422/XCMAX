<template>
  <div class="persy-brain page-view active">
    <header class="brain-toolbar">
      <div class="brain-identity">
        <span class="brain-identity__mark" aria-hidden="true">
          <span></span>
        </span>
        <div>
          <div class="brain-kicker">
            {{ adminOmniscient ? 'Omniscient Console' : 'Persy Cognitive Map' }}
          </div>
          <strong>{{ adminOmniscient ? '全知知识网络' : '企业知识网络' }}</strong>
        </div>
      </div>

      <div class="view-switch" role="tablist" aria-label="知识视图">
        <button
          v-for="item in viewModes"
          :key="item.value"
          type="button"
          role="tab"
          :aria-selected="viewMode === item.value"
          :class="{ active: viewMode === item.value }"
          @click="viewMode = item.value"
        >
          <i :class="`fa ${item.icon}`" aria-hidden="true"></i>
          <span>{{ item.label }}</span>
        </button>
      </div>

      <div class="toolbar-actions">
        <label v-if="adminOmniscient && datasetOptions.length" class="dataset-switch" title="知识空间">
          <span>空间</span>
          <select v-model="datasetIdInput" @change="applyDataset">
            <option v-for="item in datasetOptions" :key="item.id" :value="item.id">
              {{ item.label }}
            </option>
          </select>
        </label>
        <button
          v-if="adminOmniscient"
          type="button"
          class="icon-button"
          title="重建索引"
          aria-label="重建索引"
          :disabled="rebuildingIndex"
          @click="rebuildActiveIndex"
        >
          <i class="fa fa-database" :class="{ spinning: rebuildingIndex }" aria-hidden="true"></i>
        </button>
        <span class="retrieval-state" :class="{ semantic: semanticAvailable }">
          <span class="retrieval-state__dot" aria-hidden="true"></span>
          {{ retrievalModeText }}
        </span>
        <button
          v-if="viewMode === 'graph'"
          type="button"
          class="icon-button"
          title="复位图谱"
          aria-label="复位图谱"
          @click="resetGraphView"
        >
          <i class="fa fa-crosshairs" aria-hidden="true"></i>
        </button>
        <button
          type="button"
          class="icon-button"
          title="刷新知识网络"
          aria-label="刷新知识网络"
          :disabled="loadingStatus || loadingGraph"
          @click="refreshAll"
        >
          <i class="fa fa-refresh" :class="{ spinning: loadingStatus || loadingGraph }" aria-hidden="true"></i>
        </button>
        <button v-if="pendingMemoryCount" type="button" class="memory-review-button" title="审核待确认记忆" @click="openPendingMemories">
          <i class="fa fa-check-square-o" aria-hidden="true"></i>
          <span>{{ pendingMemoryCount }} 待确认</span>
        </button>
        <button type="button" class="import-button" aria-label="导入知识" title="导入知识" @click="openImport('file')">
          <i class="fa fa-plus" aria-hidden="true"></i>
          <span>导入</span>
        </button>
      </div>
    </header>

    <section v-if="adminOmniscient && omniscient" class="omniscient-strip" aria-label="全知总览">
      <div>
        <strong>{{ omniscient.document_count || 0 }}</strong>
        <span>全库文档</span>
      </div>
      <div>
        <strong>{{ omniscient.chunk_count || 0 }}</strong>
        <span>切片</span>
      </div>
      <div>
        <strong>{{ omniscient.dataset_count || 0 }}</strong>
        <span>知识空间</span>
      </div>
      <div>
        <strong>{{ semanticAvailable ? '语义' : '关键词' }}</strong>
        <span>召回</span>
      </div>
      <p v-if="omniscientHint" class="omniscient-strip__hint">{{ omniscientHint }}</p>
    </section>

    <div class="brain-workspace">
      <main class="brain-stage">
        <template v-if="viewMode === 'graph'">
          <PersyKnowledgeGraph
            ref="graphComponent"
            :graph="graph"
            :selected-node-id="selectedNode?.id || ''"
            :recall="recallState"
            :loading="loadingGraph"
            @select-node="selectNode"
            @onboarding-action="handleOnboardingAction"
          />

          <div class="graph-hud graph-hud--stats" aria-label="图谱状态">
            <div>
              <strong>{{ graphNodeCount }}</strong>
              <span>内容</span>
            </div>
            <div>
              <strong>{{ graphEdgeCount }}</strong>
              <span>关系</span>
            </div>
            <div>
              <strong>{{ documentCount }}</strong>
              <span>来源</span>
            </div>
          </div>

          <div class="graph-legend" aria-label="节点图例">
            <span v-for="item in legendItems" :key="item.type">
              <i :style="{ background: item.color }" aria-hidden="true"></i>
              {{ item.label }}
            </span>
          </div>
        </template>

        <PersyNodeCards
          v-else-if="viewMode === 'cards'"
          v-model:filter="nodeFilter"
          :nodes="filteredNodes"
          :selected-node-id="selectedNode?.id || ''"
          @select="selectNode"
          @import="openImport('file')"
        />

        <PersyMemoryList
          v-else-if="viewMode === 'memories'"
          :memories="orderedMemories"
          :loading="loadingMemories"
          :active-count="activeMemoryCount"
          :pending-count="pendingMemoryCount"
          :selected-memory-id="selectedMemory?.memory_id || ''"
          :mutating="mutatingMemory"
          @select="selectMemory"
          @confirm="confirmMemory"
          @reject="rejectMemory"
        />

        <PersySourceList
          v-else
          :documents="documents"
          :deleting-document-id="deletingDocumentId"
          @select="selectDocument"
          @delete="deleteDocument"
          @import="openImport('file')"
        />

        <form class="ask-dock" role="search" @submit.prevent="queryKnowledge">
          <span class="ask-dock__icon" aria-hidden="true">
            <i class="fa fa-bolt"></i>
          </span>
          <input
            ref="queryInput"
            v-model="queryText"
            type="text"
            autocomplete="off"
            :placeholder="knowledgeQueryPlaceholder"
            aria-label="向 Persy 提问"
          />
          <button type="submit" :disabled="querying" aria-label="发送问题" title="发送问题">
            <i :class="querying ? 'fa fa-circle-o-notch fa-spin' : 'fa fa-arrow-right'" aria-hidden="true"></i>
          </button>
          <p v-if="queryError" class="ask-dock__error" role="alert">{{ queryError }}</p>
        </form>
      </main>

      <aside class="brain-inspector" :class="{ 'is-open': mobileInspectorOpen }">
        <header class="inspector-header">
          <div class="inspector-tabs" role="tablist" aria-label="详情面板">
            <button
              type="button"
              role="tab"
              :aria-selected="inspectorTab === 'node'"
              :class="{ active: inspectorTab === 'node' }"
              @click="inspectorTab = 'node'"
            >
              节点
            </button>
            <button
              type="button"
              role="tab"
              :aria-selected="inspectorTab === 'recall'"
              :class="{ active: inspectorTab === 'recall' }"
              @click="inspectorTab = 'recall'"
            >
              召回 <span v-if="resultChunks.length">{{ resultChunks.length }}</span>
            </button>
          </div>
          <button type="button" class="inspector-mobile-close" aria-label="关闭详情" title="关闭详情" @click="mobileInspectorOpen = false">
            <i class="fa fa-times" aria-hidden="true"></i>
          </button>
        </header>

        <div v-if="inspectorTab === 'node'" class="inspector-scroll">
          <template v-if="selectedNode">
            <div class="node-detail__heading">
              <span class="node-detail__icon" :class="`node-detail__icon--${selectedNode.type}`">
                <i :class="`fa ${nodeIcon(selectedNode.type)}`" aria-hidden="true"></i>
              </span>
              <div>
                <span>{{ nodeTypeLabel(selectedNode.type) }}</span>
                <h3>{{ selectedNode.label }}</h3>
              </div>
            </div>
            <p class="node-detail__summary">{{ selectedNode.summary || '暂无摘要' }}</p>

            <dl v-if="selectedNodeFacts.length" class="fact-list">
              <template v-for="row in selectedNodeFacts" :key="row.label">
                <dt>{{ row.label }}</dt>
                <dd>{{ row.value }}</dd>
              </template>
            </dl>

            <template v-if="selectedMemory">
              <form v-if="memoryEditing" class="memory-editor" @submit.prevent="saveMemoryEdit">
                <label>
                  <span>主体</span>
                  <input v-model.trim="memoryDraftSubject" type="text" maxlength="48" required />
                </label>
                <label>
                  <span>关系</span>
                  <input v-model.trim="memoryDraftPredicate" type="text" maxlength="32" required />
                </label>
                <label>
                  <span>内容</span>
                  <textarea v-model.trim="memoryDraftObject" rows="3" maxlength="160" required></textarea>
                </label>
                <div class="memory-editor__actions">
                  <button type="button" class="secondary-button" @click="cancelMemoryEdit">取消</button>
                  <button type="submit" class="memory-primary-button" :disabled="mutatingMemory">
                    {{ mutatingMemory ? '保存中' : '保存纠正' }}
                  </button>
                </div>
              </form>
              <div v-else class="memory-detail-actions">
                <button
                  v-if="selectedMemory.status === 'pending'"
                  type="button"
                  class="memory-primary-button"
                  :disabled="mutatingMemory"
                  @click="confirmMemory(selectedMemory)"
                >
                  <i class="fa fa-check" aria-hidden="true"></i>
                  确认记忆
                </button>
                <button type="button" class="secondary-button" :disabled="mutatingMemory" @click="startMemoryEdit(selectedMemory)">
                  <i class="fa fa-pencil" aria-hidden="true"></i>
                  纠正
                </button>
                <button
                  v-if="selectedMemory.status === 'pending'"
                  type="button"
                  class="secondary-button"
                  :disabled="mutatingMemory"
                  @click="rejectMemory(selectedMemory)"
                >
                  忽略
                </button>
                <button
                  v-else
                  type="button"
                  class="memory-delete-button"
                  :disabled="mutatingMemory"
                  title="删除记忆"
                  @click="deleteMemory(selectedMemory)"
                >
                  <i class="fa fa-trash-o" aria-hidden="true"></i>
                  删除
                </button>
              </div>
              <p v-if="memoryMessage" class="memory-message" role="status">{{ memoryMessage }}</p>
            </template>

            <button v-if="selectedNode.type !== 'core'" type="button" class="node-question-button" @click="askAboutSelectedNode">
              <i class="fa fa-comment-o" aria-hidden="true"></i>
              围绕此节点提问
            </button>
          </template>
          <div v-else class="inspector-empty">
            <span class="persy-orbit" aria-hidden="true"><i></i></span>
            <strong>Persy</strong>
            <span>{{ documentCount }} 个来源 · {{ chunkCount }} 个知识切片</span>
          </div>
        </div>

        <div v-else class="inspector-scroll recall-panel">
          <template v-if="lastQuery">
            <span class="recall-panel__eyebrow">{{ lastQuery }}</span>
            <div v-if="answerText" class="recall-answer">{{ answerText }}</div>
            <p v-else-if="queryMessage" class="recall-empty">{{ queryMessage }}</p>

            <div v-if="resultChunks.length" class="evidence-list">
              <article v-for="(chunk, index) in resultChunks" :key="evidenceKey(chunk, index)">
                <header>
                  <span :class="{ memory: isMemoryChunk(chunk) }"> {{ isMemoryChunk(chunk) ? 'M' : 'K' }}{{ index + 1 }} </span>
                  <strong>{{ normalizeChunkSource(chunk) }}</strong>
                  <em>{{ formatScore(chunk.score) }}</em>
                </header>
                <p>{{ chunk.text }}</p>
              </article>
            </div>
          </template>
          <div v-else class="inspector-empty">
            <i class="fa fa-bolt" aria-hidden="true"></i>
            <strong>尚无召回轨迹</strong>
            <span>等待第一次知识召回</span>
          </div>
        </div>
      </aside>
    </div>

    <p v-if="pageError" class="page-alert" role="alert">{{ pageError }}</p>
    <p v-if="ingestMessage" class="page-toast" role="status">{{ ingestMessage }}</p>

    <PersyImportDrawer
      ref="importDrawer"
      v-model:dataset-id-input="datasetIdInput"
      :dataset-id="activeDatasetId"
      :source-placeholder="knowledgeSourcePlaceholder"
      :text-placeholder="knowledgeTextPlaceholder"
      @apply-dataset="applyDataset"
      @clear-message="ingestMessage = ''"
      @ingested="handleIngested"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useIndustryStore } from '@/stores/industry'
import PersyKnowledgeGraph from '@/components/persy/PersyKnowledgeGraph.vue'
import PersyImportDrawer from '@/components/persy/PersyImportDrawer.vue'
import PersyMemoryList from '@/components/persy/PersyMemoryList.vue'
import PersyNodeCards from '@/components/persy/PersyNodeCards.vue'
import PersySourceList from '@/components/persy/PersySourceList.vue'
import { knowledgeBaseApi, type KnowledgeBaseDocument, type KnowledgeGraphNode, type PersyMemoryRecord } from '@/api/knowledgeBase'
import { usePersyKnowledgeData, type PersyKnowledgeViewMode } from '@/composables/usePersyKnowledgeData'
import { usePersyRecallQuery } from '@/composables/usePersyRecallQuery'
import { usePersyMemoryGovernance } from '@/composables/usePersyMemoryGovernance'
import {
  errorText,
  evidenceKey,
  formatDate,
  formatScore,
  isMemoryChunk,
  memoryEvidenceSource,
  memoryScopeLabel,
  memoryStatusLabel,
  nodeIcon,
  nodeTypeLabel,
  normalizeChunkSource,
  numberText,
  parserLabel,
  strengthText,
} from '@/composables/persyKnowledgeFormatters'

type ImportMode = 'file' | 'text'
type InspectorTab = 'node' | 'recall'

const industryStore = useIndustryStore()
const isAttendanceIndustry = computed(() => String(industryStore.currentIndustryId || '').trim() === '考勤')
const knowledgeQueryPlaceholder = computed(() =>
  isAttendanceIndustry.value ? '问 Persy：考勤异常处理规则是什么？' : '问 Persy：客户续约需要谁审批？',
)
const knowledgeSourcePlaceholder = computed(() => (isAttendanceIndustry.value ? '例如：考勤管理制度' : '例如：客户续约制度'))
const knowledgeTextPlaceholder = computed(() =>
  isAttendanceIndustry.value ? '粘贴考勤制度、排班规则、请假流程或常见问题' : '粘贴制度、流程、客户资料、产品说明或 FAQ',
)

const viewMode = ref<PersyKnowledgeViewMode>('graph')
const inspectorTab = ref<InspectorTab>('node')
const mobileInspectorOpen = ref(false)
const nodeFilter = ref('')
const ingestMessage = ref('')
const deletingDocumentId = ref('')
const graphComponent = ref<InstanceType<typeof PersyKnowledgeGraph> | null>(null)
const queryInput = ref<HTMLInputElement | null>(null)
const importDrawer = ref<InstanceType<typeof PersyImportDrawer> | null>(null)

const {
  activeDatasetId,
  datasetIdInput,
  adminOmniscient,
  omniscient,
  rebuildingIndex,
  omniscientQueryEnabled,
  status,
  graph,
  memories,
  selectedNode,
  loadingStatus,
  loadingGraph,
  loadingMemories,
  pageError,
  datasetOptions,
  documentCount,
  chunkCount,
  documents,
  graphNodeCount,
  graphEdgeCount,
  semanticAvailable,
  retrievalModeText,
  knowledgeNodes,
  omniscientHint,
  refreshStatus,
  refreshGraph,
  refreshMemories,
  refreshAll,
  applyDataset: switchDataset,
  rebuildActiveIndex,
} = usePersyKnowledgeData({ viewMode })

const { queryText, querying, queryMessage, queryError, answerText, lastQuery, resultChunks, recallState, resetRecall, queryKnowledge } =
  usePersyRecallQuery({
    activeDatasetId,
    adminOmniscient,
    omniscientQueryEnabled,
    refreshMemories,
    refreshGraph,
    onRecallCommitted: () => {
      inspectorTab.value = 'recall'
      mobileInspectorOpen.value = true
      viewMode.value = 'graph'
    },
  })

const {
  mutatingMemory,
  memoryEditing,
  memoryMessage,
  memoryDraftSubject,
  memoryDraftPredicate,
  memoryDraftObject,
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
} = usePersyMemoryGovernance({
  activeDatasetId,
  memories,
  selectedNode,
  refreshMemories,
  refreshGraph,
  selectMemory,
  setIngestMessage: (message) => {
    ingestMessage.value = message
  },
})

const viewModes: Array<{ value: PersyKnowledgeViewMode; label: string; icon: string }> = [
  { value: 'graph', label: '图谱', icon: 'fa-share-alt' },
  { value: 'memories', label: '记忆', icon: 'fa-history' },
  { value: 'cards', label: '卡片', icon: 'fa-th-large' },
  { value: 'sources', label: '来源', icon: 'fa-files-o' },
]

const legendItems = [
  { type: 'topic', label: '主题', color: '#2f6f8f' },
  { type: 'source', label: '来源', color: '#c56f3d' },
  { type: 'knowledge', label: '知识', color: '#268578' },
  { type: 'memory', label: '记忆', color: '#a85667' },
  { type: 'recall', label: '召回', color: '#d39a29' },
]

const filteredNodes = computed(() => {
  const query = nodeFilter.value.trim().toLocaleLowerCase('zh-CN')
  if (!query) return knowledgeNodes.value
  return knowledgeNodes.value.filter((node) =>
    `${node.label} ${node.summary || ''} ${node.source || ''}`.toLocaleLowerCase('zh-CN').includes(query),
  )
})

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

async function applyDataset(): Promise<void> {
  resetRecall()
  await switchDataset()
}

function openImport(mode: ImportMode): void {
  ingestMessage.value = ''
  importDrawer.value?.open(mode)
}

async function handleIngested(message: string): Promise<void> {
  ingestMessage.value = message
  viewMode.value = 'graph'
  await refreshAll()
}

function selectNode(node: KnowledgeGraphNode): void {
  selectedNode.value = node
  memoryEditing.value = false
  memoryMessage.value = ''
  inspectorTab.value = 'node'
  mobileInspectorOpen.value = true
}

function selectMemory(memory: PersyMemoryRecord): void {
  const graphNode = graph.value?.nodes.find((node) => String(node.metadata?.memory_id || '') === memory.memory_id)
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

function selectDocument(doc: KnowledgeBaseDocument): void {
  const node = graph.value?.nodes.find((candidate) => candidate.type === 'source' && candidate.document_id === doc.document_id)
  if (node) selectNode(node)
}

async function deleteDocument(doc: KnowledgeBaseDocument): Promise<void> {
  const documentId = String(doc.document_id || '')
  if (!documentId || deletingDocumentId.value || !window.confirm(`删除资料“${doc.source || '未命名资料'}”及其全部知识节点？`)) {
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
</script>

<style scoped>
.persy-brain {
  position: relative;
  min-height: 0;
  overflow: hidden;
  color: #17211d;
  background: #f4f7f5;
}

.brain-toolbar {
  z-index: 8;
  display: grid;
  grid-template-columns: minmax(210px, 1fr) auto minmax(210px, 1fr);
  align-items: center;
  gap: 16px;
  min-height: 58px;
  padding: 8px 16px;
  border-bottom: 1px solid #dce4e0;
  background: rgba(255, 255, 255, 0.94);
}

.omniscient-strip {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 18px;
  padding: 10px 16px;
  border-bottom: 1px solid #d5e3db;
  background: linear-gradient(90deg, #eef6f2, #f7faf8);
}

.omniscient-strip > div {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 72px;
}

.omniscient-strip strong {
  font-size: 18px;
  line-height: 1.1;
  color: #1f3d32;
}

.omniscient-strip span,
.omniscient-strip__hint {
  font-size: 12px;
  color: #5f7369;
}

.omniscient-strip__hint {
  flex: 1 1 220px;
  margin: 0;
}

.dataset-switch {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #4d6359;
}

.dataset-switch select {
  max-width: 220px;
  height: 30px;
  border: 1px solid #c5d4cc;
  border-radius: 8px;
  background: #fff;
  color: #1f2d27;
  padding: 0 8px;
}

.brain-identity,
.toolbar-actions,
.view-switch,
.inspector-tabs {
  display: flex;
  align-items: center;
}

.brain-identity {
  min-width: 0;
  gap: 10px;
}

.brain-identity__mark {
  position: relative;
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  border: 1px solid #78a58f;
  border-radius: 50%;
}

.brain-identity__mark::before,
.brain-identity__mark::after,
.brain-identity__mark span {
  position: absolute;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #268578;
  content: '';
}

.brain-identity__mark::before {
  top: 6px;
  left: 7px;
}

.brain-identity__mark::after {
  right: 6px;
  bottom: 7px;
  background: #c56f3d;
}

.brain-identity__mark span {
  top: 12px;
  right: 8px;
  width: 5px;
  height: 5px;
  background: #2f6f8f;
}

.brain-identity strong {
  display: block;
  overflow: hidden;
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.brain-kicker {
  color: #738179;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0;
  text-transform: uppercase;
}

.view-switch {
  padding: 3px;
  border: 1px solid #d6dfda;
  border-radius: 8px;
  background: #eef2f0;
}

.view-switch button,
.inspector-tabs button {
  border: 0;
  background: transparent;
  color: #68766f;
  cursor: pointer;
  font: inherit;
}

.view-switch button {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 6px;
  min-height: 32px;
  padding: 0 12px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.view-switch button.active {
  color: #17211d;
  background: #ffffff;
  box-shadow: 0 1px 3px rgba(23, 33, 29, 0.12);
}

.toolbar-actions {
  justify-content: flex-end;
  gap: 8px;
}

.retrieval-state {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #7c5c20;
  font-size: 11px;
  font-weight: 700;
}

.retrieval-state__dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #d39a29;
}

.retrieval-state.semantic {
  color: #1d6259;
}

.retrieval-state.semantic .retrieval-state__dot {
  background: #268578;
}

.icon-button,
.import-button,
.memory-review-button,
.ask-dock button,
.inspector-mobile-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid #d4ded9;
  border-radius: 7px;
  background: #ffffff;
  color: #27352f;
  cursor: pointer;
}

.icon-button,
.inspector-mobile-close {
  width: 34px;
  height: 34px;
}

.icon-button:disabled,
.import-button:disabled,
.memory-review-button:disabled,
.ask-dock button:disabled {
  cursor: not-allowed;
  opacity: 0.58;
}

.import-button {
  gap: 7px;
  min-height: 34px;
  padding: 0 12px;
  border-color: #17211d;
  background: #17211d;
  color: #ffffff;
  font-size: 12px;
  font-weight: 700;
}

.memory-review-button {
  gap: 6px;
  min-height: 34px;
  padding: 0 10px;
  border-color: #d8b7bf;
  color: #7f3446;
  background: #fff5f7;
  font-size: 11px;
  font-weight: 700;
}

.brain-workspace {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 326px;
  flex: 1;
  min-height: 0;
}

.brain-stage {
  position: relative;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.graph-hud,
.graph-legend {
  position: absolute;
  z-index: 3;
  pointer-events: none;
}

.graph-hud--stats {
  top: 14px;
  left: 14px;
  display: flex;
  gap: 1px;
  overflow: hidden;
  border: 1px solid rgba(202, 214, 208, 0.9);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.9);
  box-shadow: 0 8px 24px rgba(35, 52, 44, 0.07);
}

.graph-hud--stats div {
  min-width: 65px;
  padding: 9px 11px;
  border-right: 1px solid #e3e9e6;
}

.graph-hud--stats div:last-child {
  border-right: 0;
}

.graph-hud strong,
.graph-hud span {
  display: block;
}

.graph-hud strong {
  font-size: 16px;
}

.graph-hud span {
  margin-top: 1px;
  color: #738179;
  font-size: 10px;
}

.graph-legend {
  bottom: 76px;
  left: 16px;
  display: flex;
  gap: 12px;
  color: #617068;
  font-size: 10px;
  font-weight: 700;
}

.graph-legend span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.graph-legend i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}

.brain-inspector {
  z-index: 5;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  border-left: 1px solid #dce4e0;
  background: #ffffff;
}

.inspector-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 50px;
  padding: 0 14px;
  border-bottom: 1px solid #e3e9e6;
}

.inspector-tabs {
  gap: 18px;
  align-self: stretch;
}

.inspector-tabs button {
  position: relative;
  padding: 0;
  font-size: 12px;
  font-weight: 700;
}

.inspector-tabs button.active {
  color: #17211d;
}

.inspector-tabs button.active::after {
  position: absolute;
  right: 0;
  bottom: 0;
  left: 0;
  height: 2px;
  background: #268578;
  content: '';
}

.inspector-tabs button span {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  margin-left: 3px;
  border-radius: 50%;
  background: #e6eeea;
  font-size: 10px;
}

.inspector-mobile-close {
  display: none;
}

.inspector-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 18px;
}

.node-detail__heading {
  display: flex;
  align-items: flex-start;
  gap: 11px;
}

.node-detail__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  border-radius: 50%;
}

.node-detail__icon {
  width: 38px;
  height: 38px;
  color: #ffffff;
  background: #268578;
}

.node-detail__icon--core {
  background: #17211d;
}

.node-detail__icon--source {
  background: #c56f3d;
}

.node-detail__icon--topic {
  background: #2f6f8f;
}

.node-detail__icon--recall {
  background: #d39a29;
}

.node-detail__icon--memory {
  background: #a85667;
}

.node-detail__heading span,
.recall-panel__eyebrow {
  color: #748179;
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
}

.node-detail__heading h3 {
  margin: 2px 0 0;
  color: #17211d;
  font-size: 17px;
  line-height: 1.25;
}

.node-detail__summary {
  margin: 18px 0;
  color: #3e4d46;
  font-size: 13px;
  line-height: 1.65;
  overflow-wrap: anywhere;
}

.fact-list {
  display: grid;
  grid-template-columns: 84px minmax(0, 1fr);
  margin: 0;
  border-top: 1px solid #e3e9e6;
}

.fact-list dt,
.fact-list dd {
  margin: 0;
  padding: 10px 0;
  border-bottom: 1px solid #e3e9e6;
  font-size: 12px;
}

.fact-list dt {
  color: #7a8880;
}

.fact-list dd {
  color: #27352f;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.node-question-button {
  border: 0;
  background: transparent;
  color: #1d6259;
  cursor: pointer;
  font: inherit;
  font-weight: 700;
}

.node-question-button {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  margin-top: 18px;
  padding: 0;
  font-size: 12px;
}

.memory-detail-actions,
.memory-editor__actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 18px;
}

.memory-primary-button,
.memory-delete-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 36px;
  padding: 0 12px;
  border: 1px solid #17211d;
  border-radius: 7px;
  color: #ffffff;
  background: #17211d;
  cursor: pointer;
  font: inherit;
  font-size: 12px;
  font-weight: 700;
}

.memory-delete-button {
  border-color: transparent;
  color: #943a34;
  background: transparent;
}

.memory-primary-button:disabled,
.memory-delete-button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.memory-message {
  margin: 11px 0 0;
  color: #52625a;
  font-size: 11px;
  line-height: 1.5;
}

.memory-editor {
  display: grid;
  gap: 10px;
  margin-top: 18px;
  padding-top: 16px;
  border-top: 1px solid #e3e9e6;
}

.memory-editor label {
  display: grid;
  gap: 5px;
  color: #66756d;
  font-size: 10px;
  font-weight: 700;
}

.memory-editor input,
.memory-editor textarea {
  width: 100%;
  min-width: 0;
  padding: 8px 9px;
  border: 1px solid #cbd7d1;
  border-radius: 7px;
  outline: none;
  color: #17211d;
  background: #ffffff;
  font: inherit;
  font-size: 12px;
  line-height: 1.5;
}

.memory-editor textarea {
  resize: vertical;
}

.memory-editor input:focus,
.memory-editor textarea:focus {
  border-color: #4e8e77;
  box-shadow: 0 0 0 3px rgba(78, 142, 119, 0.13);
}

.inspector-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 220px;
  color: #718078;
  text-align: center;
}

.inspector-empty > i {
  color: #9aaba2;
  font-size: 28px;
}

.inspector-empty strong {
  color: #27352f;
  font-size: 14px;
}

.inspector-empty span {
  font-size: 11px;
}

.persy-orbit {
  position: relative;
  width: 54px;
  height: 54px;
  border: 1px solid #a8b9b0;
  border-radius: 50%;
}

.persy-orbit::before,
.persy-orbit::after,
.persy-orbit i {
  position: absolute;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #268578;
  content: '';
}

.persy-orbit::before {
  top: 8px;
  left: 11px;
}

.persy-orbit::after {
  right: 9px;
  bottom: 11px;
  background: #c56f3d;
}

.persy-orbit i {
  top: 21px;
  right: 13px;
  width: 6px;
  height: 6px;
  background: #2f6f8f;
}

.recall-panel__eyebrow {
  display: block;
  line-height: 1.5;
  text-transform: none;
}

.recall-answer {
  margin-top: 12px;
  padding-bottom: 18px;
  border-bottom: 1px solid #e3e9e6;
  color: #27352f;
  font-size: 13px;
  line-height: 1.65;
  white-space: pre-wrap;
}

.recall-empty {
  color: #718078;
  font-size: 12px;
}

.evidence-list {
  display: flex;
  flex-direction: column;
}

.evidence-list article {
  padding: 14px 0;
  border-bottom: 1px solid #e3e9e6;
}

.evidence-list header {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 7px;
}

.evidence-list header span {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  color: #ffffff;
  background: #268578;
  font-size: 9px;
  font-weight: 800;
}

.evidence-list header span.memory {
  background: #a85667;
}

.evidence-list header strong {
  overflow: hidden;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evidence-list header em {
  color: #7b8881;
  font-size: 10px;
  font-style: normal;
}

.evidence-list p {
  display: -webkit-box;
  margin: 8px 0 0 31px;
  overflow: hidden;
  color: #4a5952;
  font-size: 11px;
  line-height: 1.55;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 4;
}

.ask-dock {
  position: absolute;
  z-index: 4;
  right: 18px;
  bottom: 16px;
  left: 18px;
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr) 38px;
  align-items: center;
  width: min(720px, calc(100% - 36px));
  min-height: 52px;
  margin: 0 auto;
  border: 1px solid rgba(185, 199, 192, 0.96);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 12px 34px rgba(23, 33, 29, 0.14);
}

.ask-dock__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #d39a29;
}

.ask-dock input {
  width: 100%;
  min-width: 0;
  border: 0;
  outline: 0;
  color: #17211d;
  background: transparent;
  font: inherit;
  font-size: 13px;
}

.ask-dock button {
  width: 32px;
  height: 32px;
  border-color: #17211d;
  background: #17211d;
  color: #ffffff;
}

.ask-dock__error {
  position: absolute;
  right: 0;
  bottom: calc(100% + 7px);
  margin: 0;
  padding: 7px 9px;
  border-radius: 6px;
  color: #8d2f27;
  background: #fff1ef;
  font-size: 11px;
}

.secondary-button {
  min-height: 36px;
  border: 1px solid #ccd7d2;
  border-radius: 7px;
  background: #ffffff;
  color: #27352f;
  cursor: pointer;
  font: inherit;
  font-size: 12px;
  font-weight: 700;
}

.secondary-button {
  padding: 0 13px;
}

.page-alert,
.page-toast {
  position: absolute;
  z-index: 20;
  top: 68px;
  left: 50%;
  max-width: min(520px, calc(100% - 32px));
  margin: 0;
  padding: 9px 12px;
  border-radius: 7px;
  transform: translateX(-50%);
  box-shadow: 0 8px 24px rgba(23, 33, 29, 0.12);
  font-size: 12px;
  font-weight: 700;
}

.page-alert {
  color: #8d2f27;
  background: #fff1ef;
}

.page-toast {
  color: #1d6259;
  background: #e8f5ef;
}

.spinning {
  animation: spin 0.9s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 980px) {
  .brain-toolbar {
    grid-template-columns: minmax(170px, 1fr) auto;
  }

  .view-switch {
    grid-row: 2;
    grid-column: 1 / -1;
    justify-self: center;
  }

  .brain-workspace {
    grid-template-columns: minmax(0, 1fr) 292px;
  }
}

@media (max-width: 767px) {
  .brain-toolbar {
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 8px;
    min-height: 54px;
    padding: 7px 10px;
  }

  .brain-identity__mark {
    width: 30px;
    height: 30px;
    flex-basis: 30px;
  }

  .brain-kicker,
  .retrieval-state,
  .toolbar-actions .icon-button:first-of-type {
    display: none;
  }

  .brain-identity strong {
    font-size: 13px;
  }

  .view-switch {
    position: absolute;
    z-index: 7;
    top: 62px;
    left: 50%;
    grid-row: auto;
    grid-column: auto;
    transform: translateX(-50%);
    box-shadow: 0 5px 18px rgba(23, 33, 29, 0.1);
  }

  .view-switch button {
    gap: 4px;
    min-height: 30px;
    padding: 0 8px;
  }

  .toolbar-actions {
    gap: 6px;
  }

  .import-button {
    width: 34px;
    padding: 0;
  }

  .import-button span {
    display: none;
  }

  .memory-review-button {
    width: 34px;
    padding: 0;
  }

  .memory-review-button span {
    display: none;
  }

  .brain-workspace {
    display: block;
  }

  .brain-stage {
    width: 100%;
    height: 100%;
  }

  .brain-inspector {
    position: absolute;
    z-index: 12;
    top: 8px;
    right: 8px;
    bottom: 76px;
    left: 42px;
    border: 1px solid #ccd8d2;
    border-radius: 8px;
    box-shadow: 0 16px 42px rgba(23, 33, 29, 0.2);
    transform: translateX(calc(100% + 18px));
    transition: transform 220ms ease;
  }

  .brain-inspector.is-open {
    transform: translateX(0);
  }

  .inspector-mobile-close {
    display: inline-flex;
    width: 30px;
    height: 30px;
  }

  .graph-hud--stats {
    top: 60px;
    left: 10px;
  }

  .graph-hud--stats div {
    min-width: 54px;
    padding: 7px 9px;
  }

  .graph-hud strong {
    font-size: 14px;
  }

  .graph-legend {
    display: none;
  }

  .ask-dock {
    right: 10px;
    bottom: 10px;
    left: 10px;
    width: calc(100% - 20px);
  }
}
</style>
