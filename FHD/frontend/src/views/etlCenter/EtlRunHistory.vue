<template src="./EtlRunHistory.template.html"></template>
<script setup lang="ts">
/**
 * 已存在的业务导入任务：保留审核、回执及撤销，不再提供新文件导入入口。
 */
import { onBeforeUnmount, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { etlApi } from '@/api/etl'
import { createEtlCenterState, ETL_RUN_TABS } from './etlCenterState'
import { createEtlCenterDerived } from './useEtlCenterDerived'
import { createEtlCenterRuns } from './useEtlCenterRuns'
import { createEtlCenterDraftActions } from './useEtlCenterDraftActions'
import { createEtlCenterExtras } from './useEtlCenterExtras'
import { useEtlRollbackPermission } from './useEtlRollbackPermission'
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
} from './etlCenterShared'

const route = useRoute()
const router = useRouter()

const state = createEtlCenterState()
const derived = createEtlCenterDerived({ state })
const { canRollback, canExecutePermission, canManageTemplate, rollbackPermissionMessage } = useEtlRollbackPermission()
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

const tabs = ETL_RUN_TABS
const targetLabel = createTargetLabel(state.capabilities)

const {
  activeTab,
  capabilities,
  templates,
  runs,
  currentRun,
  targetType,
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
const { saveCurrentAsTemplate, saveCurrentAsShipmentTemplate, previewCustomerProductsFromShipment } = extras

onMounted(bootstrap)
onBeforeUnmount(() => {
  if (pollTimer.value) clearTimeout(pollTimer.value)
})
</script>

<style scoped src="./EtlRunHistory.css"></style>
