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
import { onMounted, watch } from 'vue'
import PersyKnowledgeGraph from '@/components/persy/PersyKnowledgeGraph.vue'
import PersyImportDrawer from '@/components/persy/PersyImportDrawer.vue'
import PersyMemoryList from '@/components/persy/PersyMemoryList.vue'
import PersyNodeCards from '@/components/persy/PersyNodeCards.vue'
import PersySourceList from '@/components/persy/PersySourceList.vue'
import type { KnowledgeGraphNode, PersyMemoryRecord } from '@/api/knowledgeBase'
import { usePersyKnowledgeData, type PersyKnowledgeViewMode } from '@/composables/usePersyKnowledgeData'
import { usePersyRecallQuery } from '@/composables/usePersyRecallQuery'
import { usePersyMemoryGovernance } from '@/composables/usePersyMemoryGovernance'
import { evidenceKey, formatScore, isMemoryChunk, nodeIcon, nodeTypeLabel, normalizeChunkSource } from '@/composables/persyKnowledgeFormatters'
import { usePersyKnowledgeUiState } from './persy-knowledge/usePersyKnowledgeUiState'
import { usePersyKnowledgeInspector } from './persy-knowledge/usePersyKnowledgeInspector'
import { usePersyKnowledgeInteractions } from './persy-knowledge/usePersyKnowledgeInteractions'

// 逻辑按领域拆分到 persy-knowledge/ 下的 composables，此处仅组装（模板与拆分前逐字一致）
const ui = usePersyKnowledgeUiState()
const {
  viewMode, inspectorTab, mobileInspectorOpen, nodeFilter, ingestMessage, deletingDocumentId,
  graphComponent, queryInput, importDrawer,
  knowledgeQueryPlaceholder, knowledgeSourcePlaceholder, knowledgeTextPlaceholder,
  viewModes, legendItems,
} = ui

const data = usePersyKnowledgeData({ viewMode })
const {
  activeDatasetId, datasetIdInput, adminOmniscient, omniscient, rebuildingIndex, omniscientQueryEnabled,
  status, graph, memories, selectedNode, loadingStatus, loadingGraph, loadingMemories, pageError,
  datasetOptions, documentCount, chunkCount, documents, graphNodeCount, graphEdgeCount,
  semanticAvailable, retrievalModeText, knowledgeNodes, omniscientHint,
  refreshStatus, refreshGraph, refreshMemories, refreshAll, applyDataset: switchDataset, rebuildActiveIndex,
} = data

const recall = usePersyRecallQuery({
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
const { queryText, querying, queryMessage, queryError, answerText, lastQuery, resultChunks, recallState, queryKnowledge } = recall

// selectNode / selectMemory 与 usePersyMemoryGovernance 互为初始化依赖，保留在此（与拆分前同为提升函数声明）
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

const governance = usePersyMemoryGovernance({
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
const {
  mutatingMemory, memoryEditing, memoryMessage, memoryDraftSubject, memoryDraftPredicate, memoryDraftObject,
  selectedMemory, orderedMemories, pendingMemoryCount, activeMemoryCount,
  startMemoryEdit, cancelMemoryEdit, confirmMemory, rejectMemory, saveMemoryEdit, deleteMemory,
} = governance

const { filteredNodes, selectedNodeFacts } = usePersyKnowledgeInspector({ knowledgeNodes, nodeFilter, selectedNode, selectedMemory })

const {
  applyDataset, openImport, handleIngested, openPendingMemories, selectDocument, deleteDocument,
  askAboutSelectedNode, handleOnboardingAction, resetGraphView,
} = usePersyKnowledgeInteractions({ ui, data, recall, governance, selectNode, selectMemory })

watch(viewMode, (mode) => {
  if (mode !== 'sources') return
  if ((status.value?.documents || []).length > 0) return
  void refreshStatus(undefined, undefined, { includeDocuments: true })
})

onMounted(() => {
  void refreshAll()
})
</script>

<style scoped src="./persy-knowledge/persy-knowledge.css"></style>
