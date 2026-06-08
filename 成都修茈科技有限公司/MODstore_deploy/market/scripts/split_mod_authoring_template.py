import pathlib
import re

src = pathlib.Path(__file__).resolve().parents[1] / "src/views/ModAuthoringView.vue"
text = src.read_text(encoding="utf-8")
tmpl = re.search(r"<template>(.*?)</template>", text, re.S).group(1)
lines = tmpl.splitlines()

# line numbers in file (1-based) -> index in lines (template starts line 2 in file = index 1 in lines after split)
# template line 1 is empty after split from <template>\n
# File line 42 = section guide -> find in lines
def slice_section(start_file_line: int, end_file_line: int) -> str:
    # file line N -> lines[N-2] because template starts at file line 2
    a = start_file_line - 2
    b = end_file_line - 2
    chunk = lines[a:b]
    # strip outer section wrapper comment if needed
    return "\n".join(chunk).strip() + "\n"

sections = {
    "ExpertTabGuide": (42, 327),
    "ExpertTabManifest": (328, 341),
    "ExpertTabFrontend": (342, 377),
    "ExpertTabFiles": (378, 403),
    "ExpertTabSnapshots": (404, 441),
    "ExpertTabScan": (442, 477),
}
modals = slice_section(480, 565)

wrapper = '''<script setup lang="ts">
import { useModAuthoringContext } from '../composables/useModAuthoringContext'

const ctx = useModAuthoringContext()
const {
{bindings}
} = ctx
</script>

<template>
{body}
</template>
'''

# common bindings - use spread via toRefs alternative: destructure all used in guide
guide_bindings = """  tab,
  modData,
  modDescriptionLine,
  industryPresetList,
  selectedIndustryPreset,
  selectedIndustryScenario,
  savingManifest,
  applyIndustryPresetToManifest,
  aiBlueprint,
  industryCard,
  apiSummary,
  workflowSandboxRows,
  workflowSandboxOk,
  modSandboxChecks,
  modSandboxOk,
  vibeHealReport,
  vibeIndexReport,
  employeeReadiness,
  employeeReadinessGaps,
  readinessSummaryLabel,
  closureBusy,
  patchWorkflowBusy,
  runWorkflowEmployeeClosure,
  patchWorkflowEmployeeNodesRetry,
  workflowEmployeesRows,
  openEmployeePickModal,
  openEmployeeModal,
  confirmDeleteEmployee,
  registerWorkflowEmployeeCatalog,
  registerCatalogBusy,
  goEmployeePrefill,
  openWorkflowSandboxDecompose,
  linkableWorkflows,
  linkPick,
  linkWorkflowBusy,
  applyWorkflowLinkToRow,
  checklist,
  artifactNote,
  suggestedSkills,
  suggestedPricing,
  handleRefineSystemPrompt,
  refinePromptLoading,
  refinePromptError,
  refinePromptDiff,
  applyPricingSuggestion,
  flash,
"""

manifest_bindings = """  manifestText,
  manifestSaveWarnings,
  savingManifest,
  saveManifest,
"""

frontend_bindings = """  frontendConfigPath,
  frontendEntryPath,
  frontendSpecTitle,
  frontendSpecPreview,
  frontendBrief,
  frontendBusy,
  regenerateFrontend,
  fileSet,
"""

files_bindings = """  sortedFiles,
  selectedPath,
  fileContent,
  loadingFile,
  savingFile,
  fileWarnings,
  scaffoldEnvHint,
  onPathSelect,
  loadSelectedFile,
  saveFile,
"""

snapshots_bindings = """  snapshotsRows,
  snapshotsLoadErr,
  snapshotBusy,
  snapshotLabelDraft,
  formatSnapTime,
  refreshSnapshots,
  captureSnapshotManual,
  restoreSnapshot,
  bumpManifestPatch,
"""

scan_bindings = """  loadingSummary,
  refreshSummary,
  summary,
"""

bindings_map = {
    "ExpertTabGuide": guide_bindings,
    "ExpertTabManifest": manifest_bindings,
    "ExpertTabFrontend": frontend_bindings,
    "ExpertTabFiles": files_bindings,
    "ExpertTabSnapshots": snapshots_bindings,
    "ExpertTabScan": scan_bindings,
}

out_dir = pathlib.Path(__file__).resolve().parents[1] / "src/features/mod-authoring/expert"
out_dir.mkdir(parents=True, exist_ok=True)

for name, (start, end) in sections.items():
    body = slice_section(start, end)
    # remove v-show wrapper - keep inner content only
    body = re.sub(r'^\s*<section v-show="tab === \'[^\']+\'" class="panel">\s*\n', "", body)
    body = re.sub(r"\n\s*</section>\s*$", "", body)
    content = wrapper.replace("{bindings}", bindings_map[name]).replace("{body}", body)
    (out_dir / f"{name}.vue").write_text(content, encoding="utf-8")
    print("wrote", name)

modals_bindings = """  empPickOpen,
  empPickLoading,
  empPickError,
  empPickRows,
  empPickSaving,
  closeEmployeePickModal,
  goMyEmployees,
  confirmPickEmployee,
  empModalOpen,
  empScaffoldDone,
  empModalMode,
  empDraft,
  empScaffoldRouter,
  empModalError,
  empModalMergeHint,
  closeEmployeeModal,
  copyMergeHint,
  empModalSaving,
  submitEmployeeModal,
"""
modals_content = wrapper.replace("{bindings}", modals_bindings).replace("{body}", modals.strip())
(out_dir / "ExpertEmployeeModals.vue").write_text(modals_content, encoding="utf-8")
print("wrote ExpertEmployeeModals")
