import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { useBatchAnalyzeStore, type SheetGroup } from '@/stores/batchAnalyze'
import { useBatchAnalyze } from '@/composables/useBatchAnalyze'
import { pushErpPage } from '@/utils/erpPagePaths'
import { useBaTemplates } from './useBaTemplates'
import { useBaPreview } from './useBaPreview'
import { useBaMoveSheet } from './useBaMoveSheet'
import { useBaGroupSelection } from './useBaGroupSelection'
import { useBaSave } from './useBaSave'
import { useBaNameDialog } from './useBaNameDialog'

// 组装 BatchAnalyzeView 的全部状态与动作（拆分自原 script，逻辑逐字迁移，行为不变）。
export function assembleBatchAnalyze() {
  const router = useRouter()
  const store = useBatchAnalyzeStore()
  const { phase, groups, extractedSheets } = storeToRefs(store)
  const { startBatchAnalyze, analyzeAndGroup, extractGridForSheet } = useBatchAnalyze()

  const templates = useBaTemplates()
  const preview = useBaPreview()
  const moveSheet = useBaMoveSheet()
  const selection = useBaGroupSelection()
  const save = useBaSave()
  const nameDialog = useBaNameDialog()

  const showAllGroups = ref(false)
  const showFailedFiles = ref(false)
  const fileMap = ref<Map<string, File>>(new Map())

  const matchedTemplatesCount = computed(() => {
    return groups.value.filter(g => g.recommendedTemplateId).length
  })

  const matchedGroups = computed(() => {
    return groups.value.filter(g => g.category !== 'unknown')
  })

  const unknownGroups = computed(() => {
    return groups.value.filter(g => g.category === 'unknown')
  })

  const scoreClass = (score: number) => {
    if (score >= 80) return 'score-high'
    if (score >= 60) return 'score-medium'
    return 'score-low'
  }

  function goToBusinessDocking() {
    pushErpPage(router, { name: 'business-docking' })
  }

  function selectGroup(groupId: string) {
    store.selectGroup(store.selectedGroupId === groupId ? null : groupId)
  }

  function onTemplateChange(group: SheetGroup) {
    const tmpl = templates.availableTemplates.value.find(t => t.id === group.recommendedTemplateId)
    if (tmpl) {
      group.recommendedTemplateName = tmpl.name
      store.updateGroupTemplate(group.id, tmpl.id, tmpl.name, group.matchScore)
    }
  }

  function viewGroupDetail(group: SheetGroup) {
    store.selectGroup(group.id)
    showAllGroups.value = true
  }

  function exportReport() {
    const report = {
      totalSheets: extractedSheets.value.length,
      totalGroups: groups.value.length,
      groups: groups.value.map(g => ({
        name: g.name,
        template: g.recommendedTemplateName,
        matchScore: g.matchScore,
        sheetCount: g.matchedSheets.length,
        sources: g.matchedSheets.map(s => `${s.fileName} > ${s.sheetName}`),
        commonFields: g.commonFields,
        differenceFields: g.differenceFields
      })),
      generatedAt: new Date().toISOString()
    }

    const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `batch-analyze-report-${Date.now()}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  function startNewAnalysis() {
    store.reset()
    sessionStorage.removeItem('batch_analyze_pending_files')
    pushErpPage(router, { name: 'business-docking' })
  }

  function retry() {
    store.setError('')
    store.setPhase('idle')
  }

  onMounted(async () => {
    await templates.loadTemplates()

    if (extractedSheets.value.length > 0 && groups.value.length === 0 && phase.value === 'idle') {
      store.setPhase('extracting')
      store.updateProgress({ progress: 50 })
      await analyzeAndGroup()
    }
  })

  return {
    store,
    showAllGroups,
    showFailedFiles,
    fileMap,
    matchedTemplatesCount,
    matchedGroups,
    unknownGroups,
    scoreClass,
    goToBusinessDocking,
    selectGroup,
    onTemplateChange,
    viewGroupDetail,
    exportReport,
    startNewAnalysis,
    retry,
    ...templates,
    ...preview,
    ...moveSheet,
    ...selection,
    ...save,
    ...nameDialog,
  }
}

export type BatchAnalyzeCtx = ReturnType<typeof assembleBatchAnalyze>
