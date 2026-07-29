<template>
  <div class="persy-brain page-view active">
    <header class="brain-toolbar">
      <div class="brain-identity">
        <span class="brain-identity__mark" aria-hidden="true">
          <span></span>
        </span>
        <div>
          <div class="brain-kicker">{{ adminOmniscient ? 'Omniscient Console' : 'Persy Cognitive Map' }}</div>
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
        <label
          v-if="adminOmniscient && datasetOptions.length"
          class="dataset-switch"
          title="知识空间"
        >
          <span>空间</span>
          <select v-model="datasetIdInput" @change="applyDataset">
            <option
              v-for="item in datasetOptions"
              :key="item.id"
              :value="item.id"
            >
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
          <i
            class="fa fa-refresh"
            :class="{ spinning: loadingStatus || loadingGraph }"
            aria-hidden="true"
          ></i>
        </button>
        <button
          v-if="pendingMemoryCount"
          type="button"
          class="memory-review-button"
          title="审核待确认记忆"
          @click="openPendingMemories"
        >
          <i class="fa fa-check-square-o" aria-hidden="true"></i>
          <span>{{ pendingMemoryCount }} 待确认</span>
        </button>
        <button
          type="button"
          class="import-button"
          aria-label="导入知识"
          title="导入知识"
          @click="openImport('file')"
        >
          <i class="fa fa-plus" aria-hidden="true"></i>
          <span>导入</span>
        </button>
      </div>
    </header>

    <section
      v-if="adminOmniscient && omniscient"
      class="omniscient-strip"
      aria-label="全知总览"
    >
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

        <section v-else-if="viewMode === 'cards'" class="list-view" aria-label="知识卡片">
          <div class="list-view__head">
            <div>
              <span class="section-kicker">Knowledge Nodes</span>
              <h3>知识与主题</h3>
            </div>
            <label class="filter-field">
              <i class="fa fa-search" aria-hidden="true"></i>
              <input v-model.trim="nodeFilter" type="search" placeholder="筛选节点" />
            </label>
          </div>
          <div v-if="filteredNodes.length" class="node-card-grid">
            <button
              v-for="node in filteredNodes"
              :key="node.id"
              type="button"
              class="node-card"
              :class="[`node-card--${node.type}`, { active: selectedNode?.id === node.id }]"
              @click="selectNode(node)"
            >
              <span class="node-card__icon">
                <i :class="`fa ${nodeIcon(node.type)}`" aria-hidden="true"></i>
              </span>
              <span class="node-card__body">
                <span class="node-card__type">{{ nodeTypeLabel(node.type) }}</span>
                <strong>{{ node.label }}</strong>
                <span>{{ node.summary || '等待更多上下文' }}</span>
              </span>
              <i class="fa fa-angle-right node-card__arrow" aria-hidden="true"></i>
            </button>
          </div>
          <div v-else class="view-empty">
            <i class="fa fa-sitemap" aria-hidden="true"></i>
            <strong>还没有知识节点</strong>
            <button type="button" @click="openImport('file')">导入第一份资料</button>
          </div>
        </section>

        <section v-else-if="viewMode === 'memories'" class="list-view" aria-label="长期记忆">
          <div class="list-view__head">
            <div>
              <span class="section-kicker">Governed Memory</span>
              <h3>长期记忆</h3>
            </div>
            <div class="memory-summary" aria-label="记忆状态">
              <span><strong>{{ activeMemoryCount }}</strong> 已确认</span>
              <span :class="{ attention: pendingMemoryCount }">
                <strong>{{ pendingMemoryCount }}</strong> 待确认
              </span>
            </div>
          </div>
          <div v-if="loadingMemories" class="view-loading" role="status">
            <i class="fa fa-circle-o-notch fa-spin" aria-hidden="true"></i>
            正在读取记忆
          </div>
          <div v-else-if="orderedMemories.length" class="memory-list">
            <article
              v-for="memory in orderedMemories"
              :key="memory.memory_id"
              class="memory-row"
              :class="[`memory-row--${memory.status}`, { active: selectedMemory?.memory_id === memory.memory_id }]"
            >
              <button type="button" class="memory-row__main" @click="selectMemory(memory)">
                <span class="memory-row__type">
                  <i :class="`fa ${memoryIcon(memory.memory_type)}`" aria-hidden="true"></i>
                  {{ memoryTypeLabel(memory.memory_type) }}
                </span>
                <strong>{{ memory.statement }}</strong>
                <span class="memory-row__meta">
                  {{ memoryScopeLabel(memory.scope) }} · {{ formatDate(memory.updated_at) }}
                </span>
              </button>
              <div class="memory-strength" :title="`记忆强度 ${strengthText(memory.strength)}`">
                <span><i :style="{ width: strengthText(memory.strength) }"></i></span>
                <strong>{{ strengthText(memory.strength) }}</strong>
              </div>
              <span class="memory-status" :class="`memory-status--${memory.status}`">
                {{ memoryStatusLabel(memory.status) }}
              </span>
              <div v-if="memory.status === 'pending'" class="memory-row__actions">
                <button
                  type="button"
                  class="memory-action memory-action--confirm"
                  title="确认记忆"
                  aria-label="确认记忆"
                  :disabled="mutatingMemory"
                  @click="confirmMemory(memory)"
                >
                  <i class="fa fa-check" aria-hidden="true"></i>
                </button>
                <button
                  type="button"
                  class="memory-action"
                  title="忽略记忆"
                  aria-label="忽略记忆"
                  :disabled="mutatingMemory"
                  @click="rejectMemory(memory)"
                >
                  <i class="fa fa-times" aria-hidden="true"></i>
                </button>
              </div>
              <i v-else class="fa fa-angle-right memory-row__arrow" aria-hidden="true"></i>
            </article>
          </div>
          <div v-else class="view-empty">
            <i class="fa fa-history" aria-hidden="true"></i>
            <strong>还没有可治理的记忆</strong>
            <span>对话中明确表达的人物、地点、偏好和事实会在这里等待确认</span>
          </div>
        </section>

        <section v-else class="list-view" aria-label="资料来源">
          <div class="list-view__head">
            <div>
              <span class="section-kicker">Sources</span>
              <h3>资料来源</h3>
            </div>
            <span class="source-total">{{ documents.length }} 个来源</span>
          </div>
          <div v-if="documents.length" class="source-list">
            <div
              v-for="doc in documents"
              :key="doc.document_id || `${doc.source}-${doc.version_label}`"
              class="source-row"
            >
              <button type="button" class="source-row__select" @click="selectDocument(doc)">
                <span class="source-row__icon">
                  <i class="fa fa-file-text-o" aria-hidden="true"></i>
                </span>
                <span class="source-row__main">
                  <strong>{{ doc.source || '未命名资料' }}</strong>
                  <span>{{ parserLabel(doc.parser) }} · {{ numberText(doc.text_length) }} 字符</span>
                </span>
                <span class="source-row__metric">
                  <strong>{{ numberText(doc.chunk_count) }}</strong>
                  <span>节点</span>
                </span>
                <span class="source-row__version">{{ doc.version_label || versionLabel(doc.version) }}</span>
                <i class="fa fa-angle-right" aria-hidden="true"></i>
              </button>
              <button
                v-if="doc.document_id"
                type="button"
                class="source-row__delete"
                :disabled="deletingDocumentId === doc.document_id"
                title="删除资料"
                aria-label="删除资料"
                @click="deleteDocument(doc)"
              >
                <i
                  :class="deletingDocumentId === doc.document_id ? 'fa fa-circle-o-notch fa-spin' : 'fa fa-trash-o'"
                  aria-hidden="true"
                ></i>
              </button>
            </div>
          </div>
          <div v-else class="view-empty">
            <i class="fa fa-file-text-o" aria-hidden="true"></i>
            <strong>还没有资料来源</strong>
            <button type="button" @click="openImport('file')">导入第一份资料</button>
          </div>
        </section>

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
          <button
            type="button"
            class="inspector-mobile-close"
            aria-label="关闭详情"
            title="关闭详情"
            @click="mobileInspectorOpen = false"
          >
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

            <button
              v-if="selectedNode.type !== 'core'"
              type="button"
              class="node-question-button"
              @click="askAboutSelectedNode"
            >
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
                  <span :class="{ memory: isMemoryChunk(chunk) }">
                    {{ isMemoryChunk(chunk) ? 'M' : 'K' }}{{ index + 1 }}
                  </span>
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

    <Transition name="drawer">
      <div v-if="importOpen" class="drawer-scrim" @click.self="closeImport">
        <aside class="import-drawer" role="dialog" aria-modal="true" aria-labelledby="persy-import-title">
          <header class="drawer-header">
            <div>
              <span class="section-kicker">Grow Persy</span>
              <h3 id="persy-import-title">添加知识来源</h3>
            </div>
            <button type="button" class="icon-button" aria-label="关闭" title="关闭" @click="closeImport">
              <i class="fa fa-times" aria-hidden="true"></i>
            </button>
          </header>

          <div class="import-tabs" role="tablist" aria-label="导入方式">
            <button
              type="button"
              role="tab"
              :aria-selected="importMode === 'file'"
              :class="{ active: importMode === 'file' }"
              @click="importMode = 'file'"
            >
              <i class="fa fa-file-o" aria-hidden="true"></i>
              文件
            </button>
            <button
              type="button"
              role="tab"
              :aria-selected="importMode === 'text'"
              :class="{ active: importMode === 'text' }"
              @click="importMode = 'text'"
            >
              <i class="fa fa-clipboard" aria-hidden="true"></i>
              文本
            </button>
          </div>

          <div class="import-body">
            <label class="field-label" for="persy-source">名称</label>
            <input
              id="persy-source"
              v-model.trim="source"
              class="text-input"
              type="text"
              autocomplete="off"
              :placeholder="knowledgeSourcePlaceholder"
            />

            <template v-if="importMode === 'file'">
              <input
                ref="fileInput"
                class="visually-hidden"
                type="file"
                accept=".pdf,.docx,.xlsx,.xls,.txt,.md,.csv,.json,.log"
                @change="selectFile"
              />
              <button
                type="button"
                class="drop-zone"
                :class="{ 'has-file': selectedFile, dragging: draggingFile }"
                @click="openFilePicker"
                @dragenter.prevent="draggingFile = true"
                @dragover.prevent="draggingFile = true"
                @dragleave.prevent="draggingFile = false"
                @drop.prevent="dropFile"
              >
                <span class="drop-zone__icon">
                  <i :class="selectedFile ? 'fa fa-check' : 'fa fa-cloud-upload'" aria-hidden="true"></i>
                </span>
                <strong>{{ selectedFile?.name || '选择或拖入资料' }}</strong>
                <span v-if="selectedFile">{{ fileSizeText(selectedFile.size) }}</span>
                <span v-else>PDF、Word、Excel、Markdown、CSV、JSON，最大 25 MB</span>
              </button>
              <button
                v-if="selectedFile"
                type="button"
                class="clear-file-button"
                @click="clearSelectedFile"
              >
                移除文件
              </button>
            </template>

            <template v-else>
              <label class="field-label" for="persy-text">内容</label>
              <textarea
                id="persy-text"
                v-model="documentText"
                rows="14"
                :placeholder="knowledgeTextPlaceholder"
              ></textarea>
            </template>

            <details class="advanced-settings">
              <summary>知识空间</summary>
              <div class="advanced-settings__row">
                <input
                  v-model.trim="datasetIdInput"
                  class="text-input"
                  type="text"
                  autocomplete="off"
                  spellcheck="false"
                  aria-label="数据集"
                  @keyup.enter="applyDataset"
                />
                <button type="button" class="secondary-button" @click="applyDataset">切换</button>
              </div>
            </details>

            <p v-if="ingestError" class="form-error" role="alert">{{ ingestError }}</p>
          </div>

          <footer class="drawer-footer">
            <button type="button" class="secondary-button" @click="closeImport">取消</button>
            <button type="button" class="drawer-submit" :disabled="ingesting" @click="ingestDocument">
              <i :class="ingesting ? 'fa fa-circle-o-notch fa-spin' : 'fa fa-arrow-up'" aria-hidden="true"></i>
              {{ ingesting ? '正在形成节点' : '加入 Persy' }}
            </button>
          </footer>
        </aside>
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
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
  type PersyMemoryRecord,
  type PersyMemoryValue,
} from '@/api/knowledgeBase'

type ViewMode = 'graph' | 'memories' | 'cards' | 'sources'
type ImportMode = 'file' | 'text'
type InspectorTab = 'node' | 'recall'

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
const omniscient = ref<KnowledgeOmniscientOverview | null>(null)
const rebuildingIndex = ref(false)
const omniscientQueryEnabled = ref(true)
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
const omniscientHint = computed(() => {
  if (!adminOmniscient.value || !omniscient.value) return ''
  const persyDocs = Number(omniscient.value.datasets?.[PERSY_KNOWLEDGE_DATASET_ID]?.document_count || 0)
  const total = Number(omniscient.value.document_count || 0)
  const activeExpected = Number(
    omniscient.value.datasets?.[activeDatasetId.value]?.document_count || 0,
  )
  if (total <= 0) return '全库仍空：请导入文档或等待员工/对话入库'
  if (persyDocs <= 0 && activeDatasetId.value === PERSY_KNOWLEDGE_DATASET_ID) {
    return `Persy 空间为空，已推荐查看 ${omniscient.value.recommended_dataset_id || '存量空间'}（全库 ${total} 文档）`
  }
  if (activeExpected > 0 && documentCount.value <= 0 && !loadingStatus.value && !loadingGraph.value) {
    return `当前空间全库计 ${activeExpected} 文档，但图谱未加载到内容：请点刷新，或切换空间后再切回`
  }
  return ''
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

const viewModes: Array<{ value: ViewMode; label: string; icon: string }> = [
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

const documentCount = computed(() => status.value?.document_count ?? 0)
const chunkCount = computed(() => status.value?.chunk_count ?? 0)
const documents = computed<KnowledgeBaseDocument[]>(() => status.value?.documents ?? [])
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
    const next = await knowledgeBaseApi.status(datasetId, { includeDocuments })
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
    const nextGraph = await knowledgeBaseApi.graph(datasetId)
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
  if (datasetId !== PERSY_KNOWLEDGE_DATASET_ID) {
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
    const recommended = normalizeKnowledgeDatasetId(overview.recommended_dataset_id)
    const persyDocs = Number(overview.datasets?.[PERSY_KNOWLEDGE_DATASET_ID]?.document_count || 0)
    if (
      persyDocs <= 0 &&
      recommended &&
      recommended !== activeDatasetId.value &&
      Number(overview.datasets?.[recommended]?.document_count || 0) > 0
    ) {
      activeDatasetId.value = recommended
      datasetIdInput.value = recommended
      return true
    }
  } catch (error) {
    console.warn('[PersyKnowledge] omniscient overview failed', error)
  }
  return false
}

async function rebuildActiveIndex(): Promise<void> {
  if (!adminOmniscient.value || rebuildingIndex.value) return
  rebuildingIndex.value = true
  try {
    await knowledgeBaseApi.rebuildIndex(activeDatasetId.value)
    await refreshAll()
  } catch (error) {
    console.warn('[PersyKnowledge] rebuild failed', error)
  } finally {
    rebuildingIndex.value = false
  }
}

async function refreshDatasetViews(epoch: number, datasetId: string): Promise<void> {
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
  await loadOmniscientOverview()
  if (epoch !== refreshEpoch) return
  const datasetId = activeDatasetId.value
  await refreshDatasetViews(epoch, datasetId)
  if (epoch !== refreshEpoch || !adminOmniscient.value || !omniscient.value) return
  const expected = Number(omniscient.value.datasets?.[datasetId]?.document_count || 0)
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

function openImport(mode: ImportMode): void {
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
  ingesting.value = true
  try {
    const result =
      importMode.value === 'file' && selectedFile.value
        ? await knowledgeBaseApi.uploadDocument({
            datasetId: activeDatasetId.value,
            source: source.value.trim() || selectedFile.value.name,
            file: selectedFile.value,
          })
        : await knowledgeBaseApi.ingestDocument({
            datasetId: activeDatasetId.value,
            source: source.value.trim() || 'Persy 手工资料',
            text,
            metadata: {
              scope: 'persy',
              entrypoint: 'persy_knowledge_view',
            },
          })
    if (!result.success) throw new Error(result.message || '资料入库失败')
    const chunks = result.chunk_count ?? result.document?.chunk_count ?? 0
    ingestMessage.value = `已形成 ${chunks} 个知识节点`
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
  querying.value = true
  try {
    const boundedTopK = Math.max(1, Math.min(Number(topK.value) || 6, 20))
    let knowledge: Awaited<ReturnType<typeof knowledgeBaseApi.query>> | null = null
    let memory: Awaited<ReturnType<typeof knowledgeBaseApi.queryMemories>> | null = null
    let knowledgeFailure: unknown = null
    let memoryFailure: unknown = null
    try {
      knowledge =
        adminOmniscient.value && omniscientQueryEnabled.value
          ? await knowledgeBaseApi.omniscientQuery({
              query,
              topK: boundedTopK,
            })
          : await knowledgeBaseApi.query({
              datasetId: activeDatasetId.value,
              query,
              topK: boundedTopK,
              rerank: rerank.value,
            })
    } catch (error) {
      knowledgeFailure = error
    }
    if (
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
.inspector-tabs,
.import-tabs,
.advanced-settings__row {
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

.brain-kicker,
.section-kicker {
  color: #738179;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0;
  text-transform: uppercase;
}

.view-switch,
.import-tabs {
  padding: 3px;
  border: 1px solid #d6dfda;
  border-radius: 8px;
  background: #eef2f0;
}

.view-switch button,
.import-tabs button,
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

.view-switch button.active,
.import-tabs button.active {
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
.ask-dock button:disabled,
.drawer-submit:disabled {
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

.node-detail__icon,
.node-card__icon,
.source-row__icon {
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

.node-detail__heading h3,
.list-view__head h3,
.drawer-header h3 {
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

.node-question-button,
.view-empty button,
.clear-file-button {
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

.inspector-empty,
.view-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 220px;
  color: #718078;
  text-align: center;
}

.inspector-empty > i,
.view-empty > i {
  color: #9aaba2;
  font-size: 28px;
}

.inspector-empty strong,
.view-empty strong {
  color: #27352f;
  font-size: 14px;
}

.inspector-empty span,
.view-empty span {
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

.list-view {
  height: 100%;
  overflow: auto;
  padding: 24px 24px 96px;
  background: #f7f9f8;
}

.list-view__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.filter-field {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: 8px;
  width: min(260px, 44vw);
  min-height: 36px;
  padding: 0 10px;
  border: 1px solid #d4ded9;
  border-radius: 7px;
  background: #ffffff;
  color: #7a8880;
}

.filter-field input {
  min-width: 0;
  border: 0;
  outline: 0;
  background: transparent;
  font: inherit;
  font-size: 12px;
}

.node-card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
  gap: 10px;
}

.node-card {
  display: grid;
  grid-template-columns: 36px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  min-width: 0;
  min-height: 108px;
  padding: 14px;
  border: 1px solid #dce4e0;
  border-radius: 8px;
  background: #ffffff;
  color: #27352f;
  cursor: pointer;
  text-align: left;
}

.node-card:hover,
.node-card.active {
  border-color: #7fa997;
  box-shadow: 0 8px 20px rgba(35, 52, 44, 0.08);
}

.node-card__icon {
  width: 34px;
  height: 34px;
  color: #ffffff;
  background: #268578;
}

.node-card--source .node-card__icon {
  background: #c56f3d;
}

.node-card--topic .node-card__icon {
  background: #2f6f8f;
}

.node-card__body,
.source-row__main {
  display: flex;
  min-width: 0;
  flex-direction: column;
}

.node-card__body {
  gap: 3px;
}

.node-card__type {
  color: #7a8880;
  font-size: 9px;
  font-weight: 700;
  text-transform: uppercase;
}

.node-card__body strong,
.node-card__body > span:last-child {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.node-card__body strong {
  font-size: 13px;
}

.node-card__body > span:last-child {
  color: #6e7c75;
  font-size: 11px;
}

.node-card__arrow,
.source-row > .fa-angle-right {
  color: #a0aea7;
}

.source-total {
  color: #718078;
  font-size: 11px;
  font-weight: 700;
}

.memory-summary {
  display: flex;
  align-items: center;
  gap: 16px;
  color: #718078;
  font-size: 11px;
}

.memory-summary span {
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
}

.memory-summary strong {
  color: #27352f;
  font-size: 15px;
}

.memory-summary .attention,
.memory-summary .attention strong {
  color: #8e3f51;
}

.view-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 220px;
  color: #718078;
  font-size: 12px;
}

.memory-list {
  border-top: 1px solid #dce4e0;
}

.memory-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 116px 64px 72px;
  align-items: center;
  gap: 14px;
  min-width: 0;
  border-bottom: 1px solid #dce4e0;
  background: transparent;
}

.memory-row:hover,
.memory-row.active {
  background: #eef3f0;
}

.memory-row--pending {
  box-shadow: inset 3px 0 #b45e71;
}

.memory-row__main {
  display: flex;
  min-width: 0;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  padding: 14px 8px 14px 12px;
  border: 0;
  color: #27352f;
  background: transparent;
  cursor: pointer;
  text-align: left;
}

.memory-row__main strong {
  max-width: 100%;
  overflow: hidden;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.memory-row__type,
.memory-row__meta {
  color: #748179;
  font-size: 10px;
}

.memory-row__type {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: #895063;
  font-weight: 700;
}

.memory-strength {
  display: grid;
  grid-template-columns: minmax(52px, 1fr) 34px;
  align-items: center;
  gap: 8px;
}

.memory-strength > span {
  height: 5px;
  overflow: hidden;
  border-radius: 3px;
  background: #dce4e0;
}

.memory-strength i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: #a85667;
}

.memory-strength strong {
  color: #637169;
  font-size: 10px;
}

.memory-status {
  justify-self: start;
  padding: 4px 7px;
  border-radius: 5px;
  color: #28675d;
  background: #e3f2ec;
  font-size: 10px;
  font-weight: 700;
}

.memory-status--pending {
  color: #8e3f51;
  background: #f8e8ec;
}

.memory-row__actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
  padding-right: 8px;
}

.memory-action,
.source-row__delete {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border: 1px solid #d2dcd7;
  border-radius: 6px;
  color: #68766f;
  background: #ffffff;
  cursor: pointer;
}

.memory-action--confirm {
  border-color: #8db7a5;
  color: #1d6259;
}

.memory-action:disabled,
.source-row__delete:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.memory-row__arrow {
  justify-self: center;
  color: #a0aea7;
}

.source-list {
  border-top: 1px solid #dce4e0;
}

.source-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 38px;
  align-items: center;
  gap: 6px;
  width: 100%;
  min-width: 0;
  border-bottom: 1px solid #dce4e0;
}

.source-row__select {
  display: grid;
  grid-template-columns: 38px minmax(0, 1fr) 68px 58px 16px;
  align-items: center;
  gap: 12px;
  width: 100%;
  min-width: 0;
  padding: 13px 8px;
  border: 0;
  background: transparent;
  color: #27352f;
  cursor: pointer;
  text-align: left;
}

.source-row:hover,
.source-row__select:hover {
  background: #eef3f0;
}

.source-row__delete {
  color: #943a34;
}

.source-row__icon {
  width: 34px;
  height: 34px;
  color: #8b4a27;
  background: #f6e6dc;
}

.source-row__main {
  gap: 3px;
}

.source-row__main strong,
.source-row__main span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-row__main strong {
  font-size: 13px;
}

.source-row__main span,
.source-row__metric span,
.source-row__version {
  color: #748179;
  font-size: 10px;
}

.source-row__metric {
  text-align: right;
}

.source-row__metric strong,
.source-row__metric span {
  display: block;
}

.source-row__version {
  text-align: center;
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

.drawer-scrim {
  position: absolute;
  z-index: 40;
  inset: 0;
  display: flex;
  justify-content: flex-end;
  background: rgba(23, 33, 29, 0.28);
}

.import-drawer {
  display: flex;
  width: min(430px, 100%);
  min-height: 0;
  flex-direction: column;
  border-left: 1px solid #d1ddd7;
  background: #ffffff;
  box-shadow: -18px 0 42px rgba(23, 33, 29, 0.14);
}

.drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 20px 14px;
  border-bottom: 1px solid #e3e9e6;
}

.import-tabs {
  align-self: flex-start;
  margin: 16px 20px 0;
}

.import-tabs button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 88px;
  min-height: 32px;
  justify-content: center;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 700;
}

.import-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 18px 20px;
}

.field-label {
  display: block;
  margin: 0 0 6px;
  color: #52625a;
  font-size: 11px;
  font-weight: 700;
}

.text-input,
.import-body textarea {
  width: 100%;
  min-width: 0;
  border: 1px solid #cbd7d1;
  border-radius: 7px;
  outline: none;
  color: #17211d;
  background: #ffffff;
  font: inherit;
  font-size: 13px;
}

.text-input {
  min-height: 38px;
  padding: 0 10px;
  margin-bottom: 16px;
}

.import-body textarea {
  min-height: 250px;
  padding: 10px;
  resize: vertical;
  line-height: 1.55;
}

.text-input:focus,
.import-body textarea:focus {
  border-color: #4e8e77;
  box-shadow: 0 0 0 3px rgba(78, 142, 119, 0.13);
}

.drop-zone {
  display: flex;
  width: 100%;
  min-height: 190px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 24px;
  border: 1px dashed #9eafa6;
  border-radius: 8px;
  background: #f7f9f8;
  color: #52625a;
  cursor: pointer;
}

.drop-zone.dragging,
.drop-zone.has-file {
  border-color: #4e8e77;
  background: #eef6f2;
}

.drop-zone__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  color: #ffffff;
  background: #268578;
  font-size: 17px;
}

.drop-zone strong {
  max-width: 100%;
  overflow: hidden;
  color: #27352f;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.drop-zone > span:last-child {
  color: #7a8880;
  font-size: 10px;
}

.clear-file-button {
  margin-top: 9px;
  padding: 0;
  font-size: 11px;
}

.advanced-settings {
  margin-top: 18px;
  border-top: 1px solid #e3e9e6;
  border-bottom: 1px solid #e3e9e6;
}

.advanced-settings summary {
  padding: 11px 0;
  color: #67766e;
  cursor: pointer;
  font-size: 11px;
  font-weight: 700;
}

.advanced-settings__row {
  gap: 8px;
  padding-bottom: 12px;
}

.advanced-settings__row .text-input {
  margin: 0;
}

.secondary-button,
.drawer-submit {
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

.form-error {
  margin: 12px 0 0;
  color: #a43b32;
  font-size: 11px;
}

.drawer-footer {
  display: flex;
  justify-content: flex-end;
  gap: 9px;
  padding: 14px 20px;
  border-top: 1px solid #e3e9e6;
}

.drawer-submit {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 0 16px;
  border-color: #17211d;
  background: #17211d;
  color: #ffffff;
}

.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

.spinning {
  animation: spin 0.9s linear infinite;
}

.drawer-enter-active,
.drawer-leave-active {
  transition: opacity 180ms ease;
}

.drawer-enter-active .import-drawer,
.drawer-leave-active .import-drawer {
  transition: transform 220ms ease;
}

.drawer-enter-from,
.drawer-leave-to {
  opacity: 0;
}

.drawer-enter-from .import-drawer,
.drawer-leave-to .import-drawer {
  transform: translateX(100%);
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

  .list-view {
    padding: 60px 12px 82px;
  }

  .list-view__head {
    align-items: flex-start;
    flex-direction: column;
  }

  .filter-field {
    width: 100%;
  }

  .node-card-grid {
    grid-template-columns: 1fr;
  }

  .node-card {
    min-height: 92px;
  }

  .source-row {
    grid-template-columns: minmax(0, 1fr) 34px;
    gap: 4px;
  }

  .source-row__select {
    grid-template-columns: 34px minmax(0, 1fr) 48px 14px;
    gap: 8px;
  }

  .source-row__version {
    display: none;
  }

  .source-row__metric {
    min-width: 0;
  }

  .memory-summary {
    width: 100%;
    justify-content: space-between;
  }

  .memory-row {
    grid-template-columns: minmax(0, 1fr) 62px 64px;
    gap: 7px;
  }

  .memory-strength {
    grid-template-columns: 1fr;
  }

  .memory-strength > strong {
    text-align: right;
  }

  .memory-strength > span {
    display: none;
  }

  .memory-row__actions,
  .memory-row__arrow {
    display: none;
  }

  .drawer-scrim {
    align-items: flex-end;
  }

  .import-drawer {
    width: 100%;
    max-height: 92%;
    border-top: 1px solid #d1ddd7;
    border-left: 0;
    border-radius: 8px 8px 0 0;
  }

  .drawer-enter-from .import-drawer,
  .drawer-leave-to .import-drawer {
    transform: translateY(100%);
  }
}
</style>
