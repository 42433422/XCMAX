import { computed } from 'vue'
import type { ComputedRef, Ref } from 'vue'
import type { KnowledgeGraphNode, PersyMemoryRecord } from '@/api/knowledgeBase'
import {
  formatDate,
  memoryEvidenceSource,
  memoryScopeLabel,
  memoryStatusLabel,
  numberText,
  parserLabel,
  strengthText,
} from '@/composables/persyKnowledgeFormatters'

export interface PersyKnowledgeInspectorDeps {
  knowledgeNodes: ComputedRef<KnowledgeGraphNode[]>
  nodeFilter: Ref<string>
  selectedNode: Ref<KnowledgeGraphNode | null>
  selectedMemory: ComputedRef<PersyMemoryRecord | null>
}

export interface PersyKnowledgeInspector {
  filteredNodes: ComputedRef<KnowledgeGraphNode[]>
  selectedNodeFacts: ComputedRef<Array<{ label: string; value: string }>>
}

/** 详情面板派生域（由 PersyKnowledgeView.vue 机械切出，行为不变）：节点筛选与事实清单 */
export function usePersyKnowledgeInspector(deps: PersyKnowledgeInspectorDeps): PersyKnowledgeInspector {
  const { knowledgeNodes, nodeFilter, selectedNode, selectedMemory } = deps

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

  return { filteredNodes, selectedNodeFacts }
}
