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

const nodeTheme: Record<
  string,
  { color: string; border: string; category: string; labelColor: string }
> = {
  core: { color: '#17211d', border: '#7ad1a5', category: 'Persy', labelColor: '#17211d' },
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

const graphNodes = computed<KnowledgeGraphNode[]>(() => {
  const base: KnowledgeGraphNode[] = (props.graph?.nodes || []).map((node) => ({
    ...node,
    metadata: { ...node.metadata },
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

  const hasKnowledge = base.some((node) => ['source', 'topic', 'knowledge', 'memory'].includes(node.type))
  if (!hasKnowledge && !props.loading) {
    base.push(
      {
        id: 'onboarding:upload',
        label: '导入资料',
        type: 'onboarding',
        summary: 'PDF、Word、文本与表格',
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
  return base
})

const graphEdges = computed<KnowledgeGraphEdge[]>(() => {
  const base = (props.graph?.edges || []).map((edge) => ({ ...edge }))
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
    const targets = recalledNodeIds.value.size ? Array.from(recalledNodeIds.value) : [root.id]
    for (const target of targets) {
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
  const data = graphNodes.value.map((node) => {
    const theme = nodeTheme[node.type] || nodeTheme.knowledge
    const selected = node.id === props.selectedNodeId
    const recalled = recalledNodeIds.value.has(node.id)
    const pending = node.type === 'memory' && node.metadata?.status === 'pending'
    const showLabel = selected || recalled || node.type !== 'knowledge'
    return {
      id: node.id,
      name: node.label,
      value: Number(node.strength || 0.5),
      category: categoryIndex.get(theme.category) ?? 0,
      symbolSize: Math.max(18, Number(node.size || 24) + (recalled ? 9 : 0)),
      draggable: node.type !== 'core',
      rawNode: node,
      itemStyle: {
        color: theme.color,
        borderColor: recalled ? '#f7c84a' : theme.border,
        borderWidth: selected ? 4 : recalled ? 3 : node.type === 'onboarding' ? 2 : 1.5,
        borderType: node.type === 'onboarding' || pending ? 'dashed' : 'solid',
        opacity: pending && !selected && !recalled ? 0.72 : 1,
        shadowBlur: selected || recalled ? 18 : node.type === 'core' ? 12 : 5,
        shadowColor: selected || recalled ? 'rgba(211, 154, 41, 0.34)' : 'rgba(23, 33, 29, 0.12)',
      },
      label: {
        show: showLabel,
        formatter: compactNodeLabel(node),
        position:
          node.type === 'core'
            ? 'inside'
            : node.type === 'topic' || node.type === 'memory'
              ? 'top'
              : 'right',
        distance: node.type === 'core' ? 0 : 7,
        color: node.type === 'core' ? '#ffffff' : theme.labelColor,
        fontSize: node.type === 'core' ? 15 : 12,
        fontWeight: node.type === 'core' || recalled ? 700 : 600,
      },
    }
  })

  const links = graphEdges.value.map((edge) => {
    const isRecall = edge.type === 'recall'
    const isOnboarding = edge.type === 'onboarding'
    return {
      id: edge.id,
      source: edge.source,
      target: edge.target,
      value: edge.label || edge.type,
      lineStyle: {
        color: isRecall ? '#d39a29' : isOnboarding ? '#aab5af' : '#8fa29a',
        width: isRecall ? 2.6 : Math.max(0.8, Number(edge.weight || 0.5) * 1.8),
        opacity: isRecall ? 0.92 : isOnboarding ? 0.42 : 0.48,
        type: isOnboarding ? 'dashed' : 'solid',
        curveness: 0.08,
      },
    }
  })

  return {
    animationDuration: 620,
    animationDurationUpdate: 520,
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
          repulsion: 330,
          gravity: 0.075,
          edgeLength: [68, 148],
          friction: 0.25,
          layoutAnimation: true,
        },
        lineStyle: { color: '#8fa29a', opacity: 0.48, width: 1.2 },
        emphasis: {
          focus: 'adjacency',
          scale: 1.12,
          label: { show: true, color: '#17211d', fontWeight: 700 },
          lineStyle: { opacity: 0.9, width: 2.2 },
        },
        blur: {
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

function renderGraph(): void {
  if (!chartEl.value) return
  if (!chart) {
    chart = echarts.init(chartEl.value)
    chart.on('click', handleChartClick)
  }
  chart.setOption(buildOption(), true)
  chart.resize()
}

function resetView(): void {
  if (!chart) return
  chart.setOption(buildOption(), true)
  chart.resize()
}

watch(
  () => [props.graph, props.selectedNodeId, props.recall, props.loading],
  () => nextTick(renderGraph),
  { deep: true },
)

onMounted(() => {
  nextTick(renderGraph)
  window.addEventListener('resize', renderGraph)
  if (chartEl.value && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => chart?.resize())
    resizeObserver.observe(chartEl.value)
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', renderGraph)
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
