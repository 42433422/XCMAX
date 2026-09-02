import { computed, ref } from 'vue'
import type { ComputedRef, Ref } from 'vue'
import { useIndustryStore } from '@/stores/industry'
import PersyKnowledgeGraph from '@/components/persy/PersyKnowledgeGraph.vue'
import PersyImportDrawer from '@/components/persy/PersyImportDrawer.vue'
import type { PersyKnowledgeViewMode } from '@/composables/usePersyKnowledgeData'

export type PersyInspectorTab = 'node' | 'recall'

export interface PersyKnowledgeUiState {
  viewMode: Ref<PersyKnowledgeViewMode>
  inspectorTab: Ref<PersyInspectorTab>
  mobileInspectorOpen: Ref<boolean>
  nodeFilter: Ref<string>
  ingestMessage: Ref<string>
  deletingDocumentId: Ref<string>
  graphComponent: Ref<InstanceType<typeof PersyKnowledgeGraph> | null>
  queryInput: Ref<HTMLInputElement | null>
  importDrawer: Ref<InstanceType<typeof PersyImportDrawer> | null>
  knowledgeQueryPlaceholder: ComputedRef<string>
  knowledgeSourcePlaceholder: ComputedRef<string>
  knowledgeTextPlaceholder: ComputedRef<string>
  viewModes: Array<{ value: PersyKnowledgeViewMode; label: string; icon: string }>
  legendItems: Array<{ type: string; label: string; color: string }>
}

/** UI 状态域（由 PersyKnowledgeView.vue 机械切出，行为不变）：视图切换、详情面板、行业占位文案 */
export function usePersyKnowledgeUiState(): PersyKnowledgeUiState {
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
  const inspectorTab = ref<PersyInspectorTab>('node')
  const mobileInspectorOpen = ref(false)
  const nodeFilter = ref('')
  const ingestMessage = ref('')
  const deletingDocumentId = ref('')
  const graphComponent = ref<InstanceType<typeof PersyKnowledgeGraph> | null>(null)
  const queryInput = ref<HTMLInputElement | null>(null)
  const importDrawer = ref<InstanceType<typeof PersyImportDrawer> | null>(null)

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

  return {
    viewMode,
    inspectorTab,
    mobileInspectorOpen,
    nodeFilter,
    ingestMessage,
    deletingDocumentId,
    graphComponent,
    queryInput,
    importDrawer,
    knowledgeQueryPlaceholder,
    knowledgeSourcePlaceholder,
    knowledgeTextPlaceholder,
    viewModes,
    legendItems,
  }
}
