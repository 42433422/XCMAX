<template>
  <div class="persy-graph" aria-label="Persy 知识关系图">
    <div ref="chartEl" class="persy-graph__canvas" data-testid="persy-graph-canvas"></div>
    <div v-if="loading" class="persy-graph__loading" role="status">
      <i class="fa fa-circle-o-notch fa-spin" aria-hidden="true"></i>
      <span>正在整理知识关系</span>
    </div>
    <p class="visually-hidden">{{ accessibleGraphSummary }}</p>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { GraphChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsCoreOption } from 'echarts/core'
import type {
  KnowledgeBaseChunk,
  KnowledgeGraphEdge,
  KnowledgeGraphNode,
  KnowledgeGraphResponse,
} from '@/api/knowledgeBase'

echarts.use([GraphChart, TooltipComponent, CanvasRenderer])

export interface PersyGraphRecall {
  query: string
  chunks: KnowledgeBaseChunk[]
}

const props = withDefaults(
  defineProps<{
    graph: KnowledgeGraphResponse | null
    selectedNodeId?: string
    recall?: PersyGraphRecall | null
    loading?: boolean
  }>(),
  {
    selectedNodeId: '',
    recall: null,
    loading: false,
  },
)

const emit = defineEmits<{
  selectNode: [node: KnowledgeGraphNode]
  onboardingAction: [action: 'upload' | 'paste' | 'chat']
}>()

const chartEl = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null
let resizeObserver: ResizeObserver | null = null
let renderTimer: ReturnType<typeof setTimeout> | null = null
let lastRenderKey = ''
/** Above this, turn off continuous force animation — main source of UI jank. */
const FORCE_ANIMATION_NODE_LIMIT = 36
/** Soft cap for rendered content nodes (core/onboarding/recall still kept). */
const MAX_RENDERED_CONTENT_NODES = 56

const nodeTheme: Record<
  string,
  { color: string; border: string; category: string; labelColor: string }
> = {
  core: { color: '#17211d', border: '#7ad1a5', category: 'Persy', labelColor: '#17211d' },
  erp_ontology: { color: '#2f3327', border: '#b9c982', category: 'ERP 本体', labelColor: '#2f3327' },
  erp_domain: { color: '#5f6d3f', border: '#c9d69c', category: 'ERP 领域', labelColor: '#48522f' },
  erp_entity: { color: '#60798d', border: '#bdd2df', category: 'ERP 实体', labelColor: '#3e5768' },
  erp_rule: { color: '#786a9d', border: '#d6caef', category: 'ERP 规则', labelColor: '#554775' },
  erp_constraint: { color: '#9c4b46', border: '#efc0bb', category: 'ERP 约束', labelColor: '#70302c' },
  topic: { color: '#2f6f8f', border: '#b9dfef', category: '主题', labelColor: '#244c60' },
  source: { color: '#c56f3d', border: '#f2c6a7', category: '来源', labelColor: '#7a3f20' },
  knowledge: { color: '#268578', border: '#a9ddd5', category: '知识', labelColor: '#1d6259' },
  memory: { color: '#a85667', border: '#efbdc8', category: '记忆', labelColor: '#763846' },
  recall: { color: '#d39a29', border: '#ffe08d', category: '召回', labelColor: '#7f5a13' },
  onboarding: { color: '#ffffff', border: '#9ba9a2', category: '开始', labelColor: '#52625a' },
}

const categories = Object.values(nodeTheme).map((item) => ({ name: item.category }))
const categoryIndex = new Map(categories.map((item, index) => [item.name, index]))

function normalizeSource(value: unknown): string {
  return String(value || '').replace(/\+rerank$/i, '').trim()
}

function matchesRecall(node: KnowledgeGraphNode, chunk: KnowledgeBaseChunk): boolean {
  if (node.type === 'memory') {
    const memoryId = String(chunk.metadata?.memory_id || '')
    return Boolean(memoryId) && String(node.metadata?.memory_id || '') === memoryId
  }
  if (node.type !== 'knowledge') return false
  const chunkDocumentId = String(chunk.metadata?.document_id || '')
  if (chunkDocumentId && node.document_id === chunkDocumentId) {
    return Number(node.chunk_index) === Number(chunk.chunk_index)
  }
  return (
    normalizeSource(node.source) === normalizeSource(chunk.source) &&
    Number(node.chunk_index) === Number(chunk.chunk_index)
  )
}

const recalledNodeIds = computed(() => {
  const ids = new Set<string>()
  for (const node of props.graph?.nodes || []) {
    if ((props.recall?.chunks || []).some((chunk) => matchesRecall(node, chunk))) ids.add(node.id)
  }
  return ids
})

function prioritizeGraphNodes(nodes: KnowledgeGraphNode[]): KnowledgeGraphNode[] {
  const stickyTypes = new Set([
    'core',
    'erp_constraint',
    'erp_domain',
    'erp_ontology',
    'erp_rule',
    'onboarding',
    'recall',
    'topic',
    'memory',
  ])
  const sticky = nodes.filter((node) => stickyTypes.has(node.type))
  const rest = nodes
    .filter((node) => !stickyTypes.has(node.type))
    .sort((a, b) => Number(b.strength || 0) - Number(a.strength || 0))
  const room = Math.max(0, MAX_RENDERED_CONTENT_NODES - sticky.length)
  return sticky.concat(rest.slice(0, room))
}

const graphNodes = computed<KnowledgeGraphNode[]>(() => {
  const base: KnowledgeGraphNode[] = (props.graph?.nodes || []).map((node) => ({
    ...node,
    metadata: { ...(node.metadata || {}) },
  }))
  const rootId = `persy:${props.graph?.dataset_id || 'persy-knowledge'}`
  if (!base.some((node) => node.type === 'core')) {
    base.unshift({
      id: rootId,
      label: 'Persy',
      type: 'core',
      summary: '等待资料进入后形成企业知识网络',
      size: 72,
      strength: 1,
    })
  }

  const hasKnowledge = base.some((node) =>
    ['source', 'topic', 'knowledge', 'memory', 'erp_ontology'].includes(node.type),
  )
  if (!hasKnowledge && !props.loading) {
    base.push(
      {
        id: 'onboarding:upload',
        label: '导入资料',
        type: 'onboarding',
        summary: 'PDF、Word、Excel、文本与表格',
        size: 34,
        metadata: { action: 'upload' },
      },
      {
        id: 'onboarding:paste',
        label: '粘贴知识',
        type: 'onboarding',
        summary: '制度、流程、产品说明与 FAQ',
        size: 34,
        metadata: { action: 'paste' },
      },
      {
        id: 'onboarding:chat',
        label: '对话记忆',
        type: 'onboarding',
        summary: '有价值的对话会形成长期记忆',
        size: 34,
        metadata: { action: 'chat' },
      },
    )
  }

  const query = String(props.recall?.query || '').trim()
  if (query) {
    base.push({
      id: 'recall:current-query',
      label: query.length > 28 ? `${query.slice(0, 27)}…` : query,
      type: 'recall',
      summary: '本次提问',
      size: 42,
      strength: 0.9,
      metadata: { query },
    })
  }
  if (base.length <= MAX_RENDERED_CONTENT_NODES + 8) return base
  return prioritizeGraphNodes(base)
})

const graphEdges = computed<KnowledgeGraphEdge[]>(() => {
  const nodeIds = new Set(graphNodes.value.map((node) => node.id))
  const base = (props.graph?.edges || [])
    .filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target))
    .map((edge) => ({ ...edge }))
  const root = graphNodes.value.find((node) => node.type === 'core')
  if (!root) return base

  for (const node of graphNodes.value.filter((item) => item.type === 'onboarding')) {
    base.push({
      id: `edge:${root.id}:${node.id}`,
      source: root.id,
      target: node.id,
      type: 'onboarding',
      label: '开始',
      weight: 0.4,
    })
  }

  const queryNode = graphNodes.value.find((node) => node.id === 'recall:current-query')
  if (queryNode) {
    const targets = recalledNodeIds.value.size
      ? Array.from(recalledNodeIds.value).filter((id) => nodeIds.has(id))
      : [root.id]
    for (const target of targets.length ? targets : [root.id]) {
      base.push({
        id: `edge:${queryNode.id}:${target}`,
        source: queryNode.id,
        target,
        type: 'recall',
        label: '召回',
        weight: 1,
      })
    }
  }
  return base
})

const accessibleGraphSummary = computed(() => {
  const contentCount = graphNodes.value.filter(
    (node) => !['core', 'onboarding', 'recall'].includes(node.type),
  ).length
  if (!contentCount) {
    return '当前没有知识内容，图中显示导入资料、粘贴知识和对话记忆三个开始入口。'
  }
  const contentEdges = graphEdges.value.filter((edge) => edge.type !== 'onboarding').length
  return `当前显示 ${contentCount} 个知识节点与 ${contentEdges} 条关系。`
})

function escapeHtml(value: unknown): string {
  return String(value || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;')
}

function compactNodeLabel(node: KnowledgeGraphNode): string {
  const characters = Array.from(String(node.label || ''))
  const limit = node.type === 'recall' ? 12 : node.type === 'knowledge' ? 14 : 18
  return characters.length > limit ? `${characters.slice(0, limit).join('')}…` : characters.join('')
}

function buildOption(): EChartsCoreOption {
  const nodes = graphNodes.value
  const heavy = nodes.length >= FORCE_ANIMATION_NODE_LIMIT
  const data = nodes.map((node) => {
    const theme = nodeTheme[node.type] || nodeTheme.knowledge
    const selected = node.id === props.selectedNodeId
    const recalled = recalledNodeIds.value.has(node.id)
    const pending = node.type === 'memory' && node.metadata?.status === 'pending'
    const showLabel =
      selected ||
      recalled ||
      node.type === 'core' ||
      node.type === 'topic' ||
      node.type === 'onboarding' ||
      node.type === 'erp_ontology' ||
      node.type === 'erp_domain' ||
      node.type === 'erp_constraint'
    return {
      id: node.id,
      name: node.label,
      value: Number(node.strength || 0.5),
      category: categoryIndex.get(theme.category) ?? 0,
      symbolSize: Math.max(16, Number(node.size || 24) + (recalled ? 8 : 0) - (heavy ? 2 : 0)),
      draggable: !heavy && node.type !== 'core',
      rawNode: node,
      itemStyle: {
        color: theme.color,
        borderColor: recalled ? '#f7c84a' : theme.border,
        borderWidth: selected ? 3 : recalled ? 2 : node.type === 'onboarding' ? 2 : 1,
        borderType: node.type === 'onboarding' || pending ? 'dashed' : 'solid',
        opacity: pending && !selected && !recalled ? 0.72 : 1,
        shadowBlur: selected || recalled ? 12 : node.type === 'core' ? 8 : 0,
        shadowColor: selected || recalled ? 'rgba(211, 154, 41, 0.34)' : 'rgba(23, 33, 29, 0.12)',
      },
      label: {
        show: showLabel,
        formatter: compactNodeLabel(node),
        position:
          node.type === 'core'
            ? 'inside'
            : node.type === 'topic' ||
                node.type === 'memory' ||
                node.type === 'erp_ontology' ||
                node.type === 'erp_domain' ||
                node.type === 'erp_constraint'
              ? 'top'
              : 'right',
        distance: node.type === 'core' ? 0 : 7,
        color: node.type === 'core' ? '#ffffff' : theme.labelColor,
        fontSize: node.type === 'core' ? 15 : 11,
        fontWeight: node.type === 'core' || recalled ? 700 : 600,
      },
    }
  })

  const links = graphEdges.value.map((edge) => {
    const isRecall = edge.type === 'recall'
    const isOnboarding = edge.type === 'onboarding'
    const isErp = String(edge.type || '').startsWith('erp_')
    return {
      id: edge.id,
      source: edge.source,
      target: edge.target,
      value: edge.label || edge.type,
      lineStyle: {
        color: isRecall ? '#d39a29' : isErp ? '#8a6b36' : isOnboarding ? '#aab5af' : '#8fa29a',
        width: isRecall || isErp ? 2 : Math.max(0.7, Number(edge.weight || 0.5) * 1.4),
        opacity: isRecall ? 0.9 : isErp ? 0.62 : isOnboarding ? 0.4 : 0.42,
        type: isOnboarding ? 'dashed' : 'solid',
        curveness: 0.06,
      },
    }
  })

  return {
    animation: !heavy,
    animationDuration: heavy ? 0 : 420,
    animationDurationUpdate: heavy ? 0 : 280,
    tooltip: {
      trigger: 'item',
      borderWidth: 0,
      backgroundColor: 'rgba(23, 33, 29, 0.94)',
      textStyle: { color: '#ffffff', fontSize: 12 },
      padding: [10, 12],
      formatter: (params: unknown) => {
        const payload = params as {
          dataType?: string
          data?: { rawNode?: KnowledgeGraphNode; value?: string }
        }
        if (payload.dataType === 'edge') return escapeHtml(payload.data?.value || '关系')
        const node = payload.data?.rawNode
        if (!node) return ''
        const theme = nodeTheme[node.type] || nodeTheme.knowledge
        return `<strong>${escapeHtml(node.label)}</strong><br/><span style="color:#c7d2cc">${escapeHtml(theme.category)}</span>${
          node.summary ? `<br/>${escapeHtml(node.summary)}` : ''
        }`
      },
    },
    series: [
      {
        type: 'graph',
        layout: 'force',
        data,
        links,
        categories,
        roam: true,
        scaleLimit: { min: 0.42, max: 3.4 },
        selectedMode: 'single',
        edgeSymbol: ['none', 'none'],
        labelLayout: { hideOverlap: true },
        force: {
          initLayout: 'circular',
          repulsion: heavy ? 220 : 300,
          gravity: heavy ? 0.1 : 0.08,
          edgeLength: heavy ? [48, 110] : [68, 140],
          friction: heavy ? 0.55 : 0.35,
          // Continuous force ticks are the main jank source on large graphs.
          layoutAnimation: !heavy,
        },
        lineStyle: { color: '#8fa29a', opacity: 0.42, width: 1 },
        emphasis: {
          focus: heavy ? 'none' : 'adjacency',
          scale: heavy ? 1.04 : 1.1,
          label: { show: true, color: '#17211d', fontWeight: 700 },
          lineStyle: { opacity: 0.85, width: 2 },
        },
        blur: heavy
          ? undefined
          : {
              itemStyle: { opacity: 0.2 },
              lineStyle: { opacity: 0.08 },
              label: { show: false },
            },
      },
    ],
  }
}

function handleChartClick(params: unknown): void {
  const payload = params as { dataType?: string; data?: { rawNode?: KnowledgeGraphNode } }
  if (payload.dataType !== 'node' || !payload.data?.rawNode) return
  const node = payload.data.rawNode
  if (node.type === 'onboarding') {
    const action = String(node.metadata?.action || '')
    if (action === 'upload' || action === 'paste' || action === 'chat') {
      emit('onboardingAction', action)
    }
    return
  }
  emit('selectNode', node)
}

function graphRenderKey(): string {
  const nodes = props.graph?.nodes || []
  const edges = props.graph?.edges || []
  const recall = props.recall
  return [
    props.graph?.dataset_id || '',
    props.loading ? '1' : '0',
    props.selectedNodeId || '',
    nodes.length,
    edges.length,
    nodes[0]?.id || '',
    nodes[nodes.length - 1]?.id || '',
    recall?.query || '',
    recall?.chunks?.length || 0,
  ].join('|')
}

function renderGraph(force = false): void {
  if (!chartEl.value) return
  const key = graphRenderKey()
  if (!force && key === lastRenderKey && chart) return
  lastRenderKey = key
  if (!chart) {
    chart = echarts.init(chartEl.value, undefined, { renderer: 'canvas' })
    chart.on('click', handleChartClick)
  }
  chart.setOption(buildOption(), { notMerge: true, lazyUpdate: true })
}

function scheduleRender(force = false): void {
  if (renderTimer) clearTimeout(renderTimer)
  renderTimer = setTimeout(() => {
    renderTimer = null
    renderGraph(force)
  }, 16)
}

function handleWindowResize(): void {
  chart?.resize()
}

function resetView(): void {
  lastRenderKey = ''
  renderGraph(true)
  chart?.resize()
}

watch(
  () => [
    props.graph?.dataset_id,
    props.graph?.nodes?.length,
    props.graph?.edges?.length,
    props.selectedNodeId,
    props.recall?.query,
    props.recall?.chunks?.length,
    props.loading,
  ],
  () => nextTick(() => scheduleRender()),
)

onMounted(() => {
  nextTick(() => renderGraph(true))
  window.addEventListener('resize', handleWindowResize)
  if (chartEl.value && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => chart?.resize())
    resizeObserver.observe(chartEl.value)
  }
})

onBeforeUnmount(() => {
  if (renderTimer) clearTimeout(renderTimer)
  renderTimer = null
  window.removeEventListener('resize', handleWindowResize)
  resizeObserver?.disconnect()
  resizeObserver = null
  chart?.off('click', handleChartClick)
  chart?.dispose()
  chart = null
})

defineExpose({ resetView })
</script>

<style scoped>
.persy-graph {
  position: absolute;
  inset: 0;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  background-color: #f4f7f5;
  background-image: radial-gradient(circle, rgba(59, 82, 72, 0.15) 1px, transparent 1px);
  background-size: 22px 22px;
}

.persy-graph__canvas {
  width: 100%;
  height: 100%;
  min-height: 420px;
}

.persy-graph__loading {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: #52625a;
  background: rgba(244, 247, 245, 0.74);
  font-size: 13px;
  font-weight: 700;
  pointer-events: none;
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
</style>
