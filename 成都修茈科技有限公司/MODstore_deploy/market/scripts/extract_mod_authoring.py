import pathlib
import re

src = pathlib.Path(__file__).resolve().parents[1] / "src/views/ModAuthoringView.vue"
text = src.read_text(encoding="utf-8")
m = re.search(r'<script setup lang="ts">(.*?)</script>', text, re.S)
script = m.group(1).strip()

script = re.sub(r"import \{ useRoute, useRouter \} from 'vue-router'\n", "", script)
script = re.sub(r"const route = useRoute\(\)\n", "", script)
script = re.sub(r"const router = useRouter\(\)\n", "", script)

script = re.sub(
    r"const tabs = \[.*?\]\n\n",
    "",
    script,
    count=1,
    flags=re.S,
)
script = re.sub(r"const WORKFLOW_SUMMARY_MAX = 280\n\n", "", script)
script = re.sub(r"type LooseRecord = Record<string, any>\n\n", "", script)
script = re.sub(
    r"function asLooseRecord\(value: unknown\): LooseRecord \{.*?\n\}\n\n",
    "",
    script,
    count=1,
    flags=re.S,
)
script = re.sub(
    r"function truncatePlain\(s: unknown, max: number\): string \{.*?\n\}\n\n",
    "",
    script,
    count=1,
    flags=re.S,
)

header = """import { ref, computed, watch, reactive } from 'vue'
import type { RouteLocationNormalizedLoaded, Router } from 'vue-router'
import { api } from '@/api'
import { filterOutPlannedDutyEmployees } from '@/utils/workbenchEmployeeFilter'
import {
  getIndustryPreset,
  listIndustryPresets,
  manifestIndustryFromPreset,
} from '@/constants/industryPresets'
import {
  WORKFLOW_SUMMARY_MAX,
  asLooseRecord,
  truncatePlain,
  type LooseRecord,
  EXPERT_TABS,
} from '../types'

export function useModAuthoring(route: RouteLocationNormalizedLoaded, router: Router) {
"""

footer = """
  const descriptionDraft = ref('')
  watch(
    () => modDescriptionLine.value,
    (v) => { descriptionDraft.value = v },
    { immediate: true },
  )

  async function saveDescriptionFromWizard() {
    const desc = descriptionDraft.value.trim()
    if (!desc) {
      flash('请填写一句话介绍', false)
      return false
    }
    let parsed: LooseRecord
    try {
      parsed = JSON.parse(manifestText.value) as LooseRecord
    } catch (e) {
      flash('JSON 解析失败: ' + ((e as Error)?.message || String(e)), false)
      return false
    }
    parsed.description = desc
    manifestText.value = JSON.stringify(parsed, null, 2)
    await saveManifest()
    return true
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
"""

out = (
    pathlib.Path(__file__).resolve().parents[1]
    / "src/features/mod-authoring/composables/useModAuthoring.ts"
)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(header + script + footer, encoding="utf-8")
print("written", out, "lines", len((header + script + footer).splitlines()))
