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
  hiddenFieldCount,
  recordValue,
  resultNeedsVerification,
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
const { canRollback, canExecutePermission, canManageTemplate, canManageTarget, rollbackPermissionMessage } = useEtlRollbackPermission()
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
  sourceSheetFilter,
  sourceRowFilter,
  sourceSheetInput,
  sourceRowInput,
  requestedRowPage,
  rowsLoading,
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
  draftChanged,
  canReplay,
  canRetry,
  operation,
  recoveryMessage,
  sourceColumns,
  sourceSheets,
  rowPageCount,
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
  goToRowPage,
  locateSourceRow,
  setRowActionFilter,
  onRowActionFilterChange,
  overrideRow,
  bulkOverride,
  executeCurrentRun,
  refreshRuns,
  selectRun,
  retryRun,
  replayRun,
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
  syncDraft: runsApi.syncDraft,
  schedulePoll: runsApi.schedulePoll,
  loadRows: runsApi.loadRows,
  captureReadContext: state.captureReadContext,
  beginBusy: state.beginBusy,
  selectRun: runsApi.selectRun,
})

onMounted(bootstrap)
onBeforeUnmount(() => {
  if (pollTimer.value) clearTimeout(pollTimer.value)
})
</script>

<style scoped src="./EtlCenterView.css"></style>
