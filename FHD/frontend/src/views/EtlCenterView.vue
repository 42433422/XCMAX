<template src="./EtlCenterView.template.html"></template>
<script setup lang="ts">
/**
 * Facade：数据对接中心装配入口（实现拆分至 etlCenter/ 子模块，行为与拆分前一致）。
 */
import { onBeforeUnmount, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { etlApi } from '@/api/etl'
import { batchFileStatusLabel, ignoredReasonLabel, useEtlFolderBatch } from '@/composables/useEtlFolderBatch'
import { useEtlTemplateSelection } from '@/composables/useEtlTemplateSelection'
import { ETL_FILE_ACCEPT, formatEtlBytes } from '@/utils/etlFileSelection'
import { createEtlCenterState, ETL_CENTER_TABS } from './etlCenter/etlCenterState'
import { createEtlCenterDerived } from './etlCenter/useEtlCenterDerived'
import { createEtlCenterRuns } from './etlCenter/useEtlCenterRuns'
import { createEtlCenterDraftActions } from './etlCenter/useEtlCenterDraftActions'
import { createEtlCenterExtras } from './etlCenter/useEtlCenterExtras'
import { useEtlRollbackPermission } from './etlCenter/useEtlRollbackPermission'
import {
  actionLabel,
  actionReason,
  confidenceClass,
  compactRecord,
  createTargetLabel,
  diffText,
  formatTime,
  latestRecordSelectionText,
  ocrTableRow,
  sheetPlanRows,
  sheetPlanStatusLabel,
  sheetRoleLabel,
  stageLabel,
  statusLabel,
} from './etlCenter/etlCenterShared'

const route = useRoute()
const router = useRouter()

const state = createEtlCenterState()
const derived = createEtlCenterDerived({ state })
const { canRollback, rollbackPermissionMessage } = useEtlRollbackPermission()
const runsApi = createEtlCenterRuns({
  state,
  route,
  router,
  canExecute: derived.canExecute,
  canRollback,
  shipmentTemplateCandidates: derived.shipmentTemplateCandidates,
  bulkNewRows: derived.bulkNewRows,
})
const draftActions = createEtlCenterDraftActions({
  state,
  currentCapability: derived.currentCapability,
  syncDraft: runsApi.syncDraft,
  loadRows: runsApi.loadRows,
  schedulePoll: runsApi.schedulePoll,
  refreshRuns: runsApi.refreshRuns,
})
const extras = createEtlCenterExtras({
  state,
  router,
  shipmentTemplateCandidate: derived.shipmentTemplateCandidate,
  linkedCustomerProductPreview: derived.linkedCustomerProductPreview,
  schedulePoll: runsApi.schedulePoll,
  tryAutoWrite: runsApi.tryAutoWrite,
  markAutoWrite: runsApi.markAutoWrite,
  syncDraft: runsApi.syncDraft,
  loadRows: runsApi.loadRows,
})

const tabs = ETL_CENTER_TABS
const targetLabel = createTargetLabel(state.capabilities)

const {
  activeTab,
  capabilities,
  templates,
  targetConfigs,
  runs,
  currentRun,
  targetType,
  targetConfigId,
  runRows,
  rowPage,
  rowTotal,
  rowActionFilter,
  busy,
  pageError,
  validRowsOnly,
  editableMappings,
  mappingUiTransform,
  mappingUiTransformJson,
  allowedUpdateFields,
  ocrConfirmed,
  hasOcrRows,
  showWebhookForm,
  webhookDraft,
  webhookTestMessage,
  shipmentTemplateMessage,
  customerProductPreviewMessage,
  selectedShipmentTemplateRegionId,
  pollTimer,
} = state

const {
  currentCapability,
  updatableFields,
  allowedActionsForRow,
  bulkNewRows,
  canExecute,
  summaryCards,
  savedShipmentTemplate,
  savedShipmentTemplateName,
  shipmentTemplateCandidates,
  shipmentTemplateCandidate,
  shipmentTemplateCandidateName,
  linkedCustomerProductPreview,
  linkedCustomerNames,
  plannedBusinessRows,
  runOutcomeText,
  regionSummary,
  detectedRegions,
  workbookSheetPlan,
  latestRecordSelection,
  llmPlanningText,
} = derived

const {
  bootstrap,
  loadRows,
  setRowActionFilter,
  onRowActionFilterChange,
  overrideRow,
  bulkOverride,
  executeCurrentRun,
  refreshRuns,
  selectRun,
  retryRun,
  rollbackRun,
} = runsApi

const { saveMappings, targetField, applyCommonTransform, mappingSample } = draftActions
const { saveWebhook, testWebhook, saveCurrentAsTemplate, saveCurrentAsShipmentTemplate, previewCustomerProductsFromShipment } = extras

const { templateSelection, compatibleTemplates, compatiblePresets, templateId, compatibilityPresetId, selectedCompatibilityPreset } =
  useEtlTemplateSelection({ capabilities, templates, targetType })

const {
  selectedFiles,
  ignoredFiles,
  selectionFolderName,
  fileInput,
  folderInput,
  maxFileBytes,
  selectedTotalBytes,
  incompatibleFiles,
  batchFinishedCount,
  batchFailedCount,
  batchProgress,
  selectionHeadline,
  startButtonText,
  onFileChange,
  onFolderChange,
  onDrop,
  clearSelection,
  removeSelectedFile,
  startPreview,
  openBatchRun,
} = useEtlFolderBatch({
  capabilities,
  targetType,
  templateId,
  compatibilityPresetId,
  targetConfigId,
  runs,
  currentRun,
  activeTab,
  busy,
  pageError,
  router,
  autoWriteEnabled: state.autoWriteEnabled,
  markAutoWrite: runsApi.markAutoWrite,
  tryAutoWrite: runsApi.tryAutoWrite,
  syncDraft: runsApi.syncDraft,
  schedulePoll: runsApi.schedulePoll,
  loadRows: runsApi.loadRows,
})

onMounted(bootstrap)
onBeforeUnmount(() => {
  if (pollTimer.value) clearTimeout(pollTimer.value)
})
</script>

<style scoped src="./EtlCenterView.css"></style>
