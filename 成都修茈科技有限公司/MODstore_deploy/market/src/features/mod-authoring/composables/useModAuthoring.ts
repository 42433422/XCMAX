// 兼容 façade：useModAuthoring 已按关注点拆分至 ./use-mod-authoring/，导出面与原单体完全一致。
// 本文件仅负责组装各子模块、按原顺序注册 watch，并原样返回原有键集合（顺序不变）。
import { computed, ref, watch } from 'vue'
import type { RouteLocationNormalizedLoaded, Router } from 'vue-router'
import type { LooseRecord } from '../types'
import { EXPERT_TABS } from '../types'
import { createModAuthoringCore } from './use-mod-authoring/core'
import { createViewModels } from './use-mod-authoring/viewModels'
import { createFiles } from './use-mod-authoring/files'
import { createSnapshots } from './use-mod-authoring/snapshots'
import { createWorkflowLink } from './use-mod-authoring/workflowLink'
import { createEmployeeModal } from './use-mod-authoring/employeeModal'
import { createRefine } from './use-mod-authoring/refine'
import { createLoadSave } from './use-mod-authoring/loadSave'
import { createIndustry } from './use-mod-authoring/industry'
import { createWizard } from './use-mod-authoring/wizard'

export function useModAuthoring(route: RouteLocationNormalizedLoaded, router: Router) {
  // ── 核心共享状态与 flash ─────────────────────────────────────────────────────
  const core = createModAuthoringCore()
  const { modData, summary, aiBlueprint, manifestText, manifestSaveWarnings, loading, loadError, message, messageOk, flash } = core

  const modId = computed(() => String(route.params.modId || ''))

  // ── 派生视图模型 ─────────────────────────────────────────────────────────────
  const viewModels = createViewModels({ modData, summary, aiBlueprint, modId })
  const {
    modDescriptionLine,
    employeeReadiness,
    employeeReadinessGaps,
    readinessSummaryLabel,
    workflowEmployeesRows,
    frontendConfigPath,
    frontendEntryPath,
    frontendSpecTitle,
    frontendSpecPreview,
    industryCard,
    manifestSidebarStatus,
    apiSummary,
    workflowSandboxRows,
    workflowSandboxOk,
    modSandboxChecks,
    modSandboxOk,
    vibeHealReport,
    vibeIndexReport,
  } = viewModels

  // ── 各关注点子模块（reload 经闭包晚绑定到 loadSave，与原单体同一函数语义）───
  const files = createFiles({ modData, modId, flash, reload: () => loadSave.reload() })
  const {
    selectedPath,
    fileContent,
    loadingFile,
    savingFile,
    fileWarnings,
    normPath,
    fileSet,
    scaffoldEnvHint,
    sortedFiles,
    backendEntryRel,
    checklist,
    artifactNote,
    loadSelectedFile,
    onPathSelect,
    saveFile,
  } = files

  const snapshots = createSnapshots({ modId, flash, reload: () => loadSave.reload(), manifestSaveWarnings })
  const {
    snapshotsRows,
    snapshotsLoadErr,
    snapshotBusy,
    snapshotLabelDraft,
    formatSnapTime,
    refreshSnapshots,
    captureSnapshotManual,
    restoreSnapshot,
    bumpManifestPatch,
  } = snapshots

  const workflowLink = createWorkflowLink({ modData, modId, router, flash, reload: () => loadSave.reload(), manifestSaveWarnings })
  const {
    linkableWorkflows,
    linkPick,
    linkWorkflowBusy,
    registerCatalogBusy,
    patchWorkflowBusy,
    closureBusy,
    openWorkflowSandboxDecompose,
    loadLinkableWorkflows,
    applyWorkflowLinkToRow,
    runWorkflowEmployeeClosure,
    patchWorkflowEmployeeNodesRetry,
    registerWorkflowEmployeeCatalog,
  } = workflowLink

  const employeeModal = createEmployeeModal({
    modData,
    modId,
    router,
    flash,
    reload: () => loadSave.reload(),
    manifestSaveWarnings,
    workflowEmployeesRows,
  })
  const {
    empModalOpen,
    empModalMode,
    empEditIndex,
    empDraft,
    empScaffoldRouter,
    empModalSaving,
    empModalError,
    empModalMergeHint,
    empScaffoldDone,
    empPickOpen,
    empPickRows,
    empPickLoading,
    empPickError,
    empPickSaving,
    openEmployeePickModal,
    closeEmployeePickModal,
    goMyEmployees,
    confirmPickEmployee,
    goEmployeePrefill,
    getWorkflowEmployeesArray,
    openEmployeeModal,
    closeEmployeeModal,
    persistWorkflowEmployees,
    copyMergeHint,
    submitEmployeeModal,
    confirmDeleteEmployee,
  } = employeeModal

  const refine = createRefine({ modData, modId, flash, reload: () => loadSave.reload() })
  const {
    suggestedSkills,
    suggestedPricing,
    refinePromptLoading,
    refinePromptError,
    refinePromptDiff,
    handleRefineSystemPrompt,
    applyPricingSuggestion,
  } = refine

  const loadSave = createLoadSave({
    modData,
    summary,
    aiBlueprint,
    manifestText,
    manifestSaveWarnings,
    loading,
    loadError,
    modId,
    flash,
    fileSet,
    normPath,
    selectedPath,
    fileContent,
    fileWarnings,
    loadSelectedFile,
    refreshSnapshots,
    loadLinkableWorkflows,
    manifestSidebarStatus,
  })
  const { savingManifest, loadingSummary, frontendBusy, frontendBrief, refreshSummary, reload, saveManifest, regenerateFrontend } =
    loadSave

  const industry = createIndustry({ manifestText, saveManifest, flash })
  const { industryPresetList, selectedIndustryPreset, selectedIndustryScenario, applyIndustryPresetToManifest } = industry

  const wizard = createWizard({ manifestText, saveManifest, flash })
  const { nameDraft, descriptionDraft, saveDescriptionFromWizard } = wizard

  const tab = ref('guide')

  // ── watch（与原单体保持相同注册顺序与 immediate 行为）────────────────────────
  watch(
    () => modData.value?.manifest?.industry,
    (ind) => {
      const id = ind && typeof ind === 'object' ? String((ind as LooseRecord).id || '').trim() : ''
      if (id && industryPresetList.some((p) => p.id === id)) {
        selectedIndustryPreset.value = id
      }
    },
    { immediate: true },
  )

  watch(
    modId,
    (id) => {
      if (!id) {
        loadError.value = '缺少 modId'
        loading.value = false
        modData.value = null
        return
      }
      reload()
    },
    { immediate: true },
  )

  watch(
    () => [String(route.query.mode || '').toLowerCase(), modId.value],
    ([mode]) => {
      if (mode === 'edit' && modId.value) tab.value = 'snapshots'
    },
    { immediate: true },
  )

  watch(
    () => String(modData.value?.manifest?.name || modId.value || '').trim(),
    (v) => {
      nameDraft.value = v
    },
    { immediate: true },
  )

  watch(
    () => modDescriptionLine.value,
    (v) => {
      descriptionDraft.value = v
    },
    { immediate: true },
  )

  function goRepo() {
    router.push({ name: 'workbench-repository' })
  }

  return {
    EXPERT_TABS,
    tab,
    loading,
    loadError,
    modData,
    summary,
    aiBlueprint,
    manifestText,
    manifestSaveWarnings,
    message,
    messageOk,
    savingManifest,
    selectedPath,
    fileContent,
    loadingFile,
    savingFile,
    fileWarnings,
    loadingSummary,
    frontendBusy,
    frontendBrief,
    snapshotsRows,
    snapshotsLoadErr,
    snapshotBusy,
    snapshotLabelDraft,
    modId,
    modDescriptionLine,
    nameDraft,
    descriptionDraft,
    saveDescriptionFromWizard,
    employeeReadiness,
    employeeReadinessGaps,
    readinessSummaryLabel,
    workflowEmployeesRows,
    frontendConfigPath,
    frontendEntryPath,
    frontendSpecTitle,
    frontendSpecPreview,
    suggestedSkills,
    suggestedPricing,
    refinePromptLoading,
    refinePromptError,
    refinePromptDiff,
    handleRefineSystemPrompt,
    applyPricingSuggestion,
    industryCard,
    industryPresetList,
    selectedIndustryPreset,
    selectedIndustryScenario,
    applyIndustryPresetToManifest,
    manifestSidebarStatus,
    apiSummary,
    workflowSandboxRows,
    workflowSandboxOk,
    modSandboxChecks,
    modSandboxOk,
    vibeHealReport,
    vibeIndexReport,
    linkableWorkflows,
    linkPick,
    linkWorkflowBusy,
    registerCatalogBusy,
    patchWorkflowBusy,
    closureBusy,
    empModalOpen,
    empModalMode,
    empEditIndex,
    empDraft,
    empScaffoldRouter,
    empModalSaving,
    empModalError,
    empModalMergeHint,
    empScaffoldDone,
    empPickOpen,
    empPickRows,
    empPickLoading,
    empPickError,
    empPickSaving,
    openEmployeePickModal,
    closeEmployeePickModal,
    goMyEmployees,
    confirmPickEmployee,
    runWorkflowEmployeeClosure,
    patchWorkflowEmployeeNodesRetry,
    registerWorkflowEmployeeCatalog,
    goEmployeePrefill,
    openEmployeeModal,
    closeEmployeeModal,
    submitEmployeeModal,
    copyMergeHint,
    confirmDeleteEmployee,
    sortedFiles,
    scaffoldEnvHint,
    checklist,
    artifactNote,
    flash,
    openWorkflowSandboxDecompose,
    applyWorkflowLinkToRow,
    formatSnapTime,
    refreshSnapshots,
    captureSnapshotManual,
    restoreSnapshot,
    bumpManifestPatch,
    goRepo,
    refreshSummary,
    reload,
    saveManifest,
    regenerateFrontend,
    loadSelectedFile,
    onPathSelect,
    saveFile,
    fileSet,
    backendEntryRel,
    getWorkflowEmployeesArray,
    persistWorkflowEmployees,
  }
}
